"""Create/update version-controlled n8n workflows; activate only when explicitly configured."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(base, key, path, method='GET', payload=None):
    request = Request(base + '/api/v1' + path, method=method,
                      headers={'X-N8N-API-KEY': key, 'Content-Type': 'application/json',
                               'User-Agent': 'bun2too-workflow-deployer/1.0'},
                      data=None if payload is None else json.dumps(payload).encode())
    started = time.monotonic()
    print(f'n8n request method={method} path=/api/v1{path}', flush=True)
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            body = response.read()
            print(f'n8n response status={response.status} duration_seconds={time.monotonic()-started:.3f}', flush=True)
            return json.loads(body) if body else {}
    except HTTPError as exc:
        print(f'n8n response status={exc.code} duration_seconds={time.monotonic()-started:.3f}', flush=True)
        raise


def render(template, base, credential_id, environment, timezone):
    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, str):
            return value.replace('__CREWAI_BASE_URL__', base).replace('__MARKETING_CREDENTIAL_ID__', credential_id).replace('__DEPLOY_ENVIRONMENT__', environment)
        return value
    result = replace(template)
    result['settings']['timezone'] = timezone
    return result


def marketing_credential(env, base, key, request):
    """Provision encrypted n8n credential data, never embed the secret in workflows."""
    from urllib.parse import quote
    supplied = env.get('N8N_MARKETING_CREDENTIAL_ID', '')
    token = env.get('MARKETING_API_KEY', '')
    if not token:
        if supplied in ('', 'MARKETING_API_KEY', 'N8N_MARKETING_CREDENTIAL_ID'):
            raise ValueError('Pass MARKETING_API_KEY to provision the n8n Header Auth credential; a secret name is not a credential ID')
        # Legacy manually managed credentials remain supported.
        return supplied
    name = 'Bun2too Marketing API (' + env.get('DEPLOY_ENVIRONMENT', 'production') + ')'
    matches = []
    path = '/credentials?limit=100'
    while path:
        try:
            result = request(base, key, path)
        except HTTPError as exc:
            raise ValueError(f'n8n credential discovery failed HTTP {exc.code}; requires a version supporting '
                             'public credential list/update APIs and an owner/admin API key with credential permissions') from None
        matches.extend(c for c in result['data'] if c.get('name') == name or c.get('id') == supplied)
        cursor = result.get('nextCursor')
        path = '/credentials?limit=100&cursor=' + quote(cursor, safe='') if cursor else None
    explicit = [c for c in matches if c.get('id') == supplied]
    selected = explicit or [c for c in matches if c.get('name') == name]
    if len(selected) > 1:
        raise ValueError('Duplicate managed Marketing API credentials; reconcile them before deployment')
    payload = {'name': name, 'type': 'httpHeaderAuth',
               'data': {'name': 'Authorization', 'value': 'Bearer ' + token}}
    if selected:
        credential = selected[0]
        if credential.get('type') != 'httpHeaderAuth':
            raise ValueError('Selected n8n marketing credential must have type httpHeaderAuth')
        credential_id = credential['id']
        request(base, key, '/credentials/' + quote(credential_id, safe=''), 'PATCH', payload)
    else:
        credential_id = request(base, key, '/credentials', 'POST', payload)['id']
    if not isinstance(credential_id, str) or not credential_id:
        raise ValueError('n8n did not return a credential ID')
    print('Provisioned n8n Header Auth credential; secret omitted.', flush=True)
    return credential_id


def alert_credentials(env, base, key, request):
    """Provision optional independent fallback destinations as encrypted credentials."""
    from urllib.parse import quote
    configs = []
    if env.get('ALERT_SLACK_BOT_TOKEN') and env.get('ALERT_SLACK_CHANNEL'):
        configs.append(('slack', 'httpHeaderAuth', {'name': 'Authorization', 'value': 'Bearer ' + env['ALERT_SLACK_BOT_TOKEN']}))
    if env.get('SMTP_HOST') and env.get('ALERT_EMAIL_FROM') and env.get('ALERT_EMAIL_TO'):
        configs.append(('smtp', 'smtp', {'host': env['SMTP_HOST'], 'port': int(env.get('SMTP_PORT', '587')),
            'user': env.get('SMTP_USER', ''), 'password': env.get('SMTP_PASSWORD', ''),
            'secure': env.get('SMTP_PORT', '587') == '465', 'disableStartTls': False}))
    result = {}
    if not configs:
        return result
    existing, path = [], '/credentials?limit=100'
    while path:
        page = request(base, key, path)
        existing.extend(page['data'])
        cursor = page.get('nextCursor')
        path = '/credentials?limit=100&cursor=' + quote(cursor, safe='') if cursor else None
    for channel, kind, data in configs:
        name = 'Bun2too operational ' + channel + ' (' + env.get('DEPLOY_ENVIRONMENT', 'production') + ')'
        matches = [record for record in existing if record['name'] == name]
        if len(matches) > 1:
            raise ValueError('Duplicate operational notification credentials')
        payload = {'name': name, 'type': kind, 'data': data}
        if matches:
            if matches[0]['type'] != kind:
                raise ValueError('Operational credential type mismatch')
            identity = matches[0]['id']
            request(base, key, '/credentials/' + quote(identity, safe=''), 'PATCH', payload)
        else:
            identity = request(base, key, '/credentials', 'POST', payload)['id']
        result[channel] = identity
    return result


def render_alerts(payload, credentials, env):
    if 'errors' not in payload['name']:
        return payload
    replacements = {
        '__ALERT_SLACK_CREDENTIAL_ID__': credentials.get('slack', ''),
        '__ALERT_SMTP_CREDENTIAL_ID__': credentials.get('smtp', ''),
        '__ALERT_SLACK_CHANNEL__': env.get('ALERT_SLACK_CHANNEL', ''),
        '__ALERT_EMAIL_FROM__': env.get('ALERT_EMAIL_FROM', ''),
        '__ALERT_EMAIL_TO__': env.get('ALERT_EMAIL_TO', ''),
    }
    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, str):
            for old, new in replacements.items():
                value = value.replace(old, new)
        return value
    payload = replace(payload)
    remove = set()
    if not credentials.get('slack'):
        remove.update({'Slack fallback notification', 'Remember Slack fallback', 'Gate slack fallback'})
    if not credentials.get('smtp'):
        remove.update({'Email fallback notification', 'Gate email fallback', 'Remember email fallback'})
    if not credentials:
        remove.add('Prepare independent fallback')
    payload['nodes'] = [node for node in payload['nodes'] if node['name'] not in remove]
    payload['connections'] = {source: {'main': [[edge for edge in edges if edge['node'] not in remove] for edges in outputs['main']]}
                              for source, outputs in payload['connections'].items() if source not in remove}
    return payload


def notification_environment(env):
    """CI already owns the runtime JSON secret; reuse only notification fields."""
    result = dict(env)
    try:
        runtime = json.loads(env.get('MARKETING_RUNTIME_CONFIG') or '{}')
    except ValueError:
        raise ValueError('MARKETING_RUNTIME_CONFIG must contain valid JSON') from None
    if not isinstance(runtime, dict):
        raise ValueError('MARKETING_RUNTIME_CONFIG must be an object')
    for key in ('ALERT_SLACK_BOT_TOKEN', 'ALERT_SLACK_CHANNEL', 'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER',
                'SMTP_PASSWORD', 'ALERT_EMAIL_FROM', 'ALERT_EMAIL_TO'):
        if not result.get(key) and runtime.get(key):
            if not isinstance(runtime[key], str):
                raise ValueError('Notification configuration values must be strings')
            result[key] = runtime[key]
    return result


def deploy(env, request=api):
    env = notification_environment(env)
    required = ('N8N_BASE_URL', 'N8N_API_KEY', 'CREWAI_BASE_URL')
    for name in required:
        if not env.get(name):
            raise ValueError('Missing ' + name)
    base, crew = env['N8N_BASE_URL'].rstrip('/'), env['CREWAI_BASE_URL'].rstrip('/')
    for url in (base, crew):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Service URLs must be HTTPS without embedded credentials')
    key = env['N8N_API_KEY']
    workflows = []
    path = '/workflows?limit=100'
    while path:
        result = request(base, key, path)
        workflows.extend(result['data'])
        from urllib.parse import quote
        cursor = result.get('nextCursor')
        path = '/workflows?limit=100&cursor=' + quote(cursor, safe='') if cursor else None
    credential_id = marketing_credential(env, base, key, request)
    alerts = alert_credentials(env, base, key, request)
    error_workflow_id = None
    verified_workflows = []
    for source in sorted((ROOT / 'n8n').glob('*.json')):
        payload = render(json.loads(source.read_text()), crew, credential_id,
                         env.get('DEPLOY_ENVIRONMENT', 'production'), env.get('MARKETING_TIMEZONE', 'America/Chicago'))
        payload = render_alerts(payload, alerts, env)
        if error_workflow_id:
            payload['settings']['errorWorkflow'] = error_workflow_id
        matches = [workflow for workflow in workflows if workflow['name'] == payload['name']]
        if len(matches) > 1:
            raise ValueError('Duplicate managed n8n workflow names; resolve before deploying')
        if matches:
            workflow_id = matches[0]['id']
            if matches[0].get('active'):
                request(base, key, f'/workflows/{workflow_id}/deactivate', 'POST')
            result = request(base, key, f'/workflows/{workflow_id}', 'PUT', payload)
        else:
            result = request(base, key, '/workflows', 'POST', payload)
        workflow_id = result['id']
        is_error = source.name == '00-error-handler.json'
        if is_error:
            error_workflow_id = workflow_id
        if not is_error and env.get('N8N_ACTIVATE_WORKFLOWS', 'false').lower() == 'true':
            request(base, key, f'/workflows/{workflow_id}/activate', 'POST')
        observed = request(base, key, f'/workflows/{workflow_id}')
        if observed.get('name') != payload['name']:
            raise ValueError('n8n workflow readback did not match the deployed workflow')
        should_activate = not is_error and env.get('N8N_ACTIVATE_WORKFLOWS', 'false').lower() == 'true'
        if should_activate and observed.get('active') is not True:
            raise ValueError('n8n schedule is not active after deployment')
        if not is_error and (observed.get('settings') or {}).get('errorWorkflow') != error_workflow_id:
            raise ValueError('n8n error workflow link was not saved')
        record = dict(name=payload['name'], id=workflow_id, active=observed.get('active') is True,
                      url=base + '/workflow/' + workflow_id)
        verified_workflows.append(record)
        print('Verified n8n workflow ' + json.dumps(record), flush=True)
        if env.get('GITHUB_STEP_SUMMARY'):
            with Path(env['GITHUB_STEP_SUMMARY']).open('a') as output:
                output.write(f"\nWorkflow [{record['name']}]({record['url']}): active={record['active']} (read back from n8n).\n")
    return verified_workflows


if __name__ == '__main__':
    try:
        deploy(os.environ)
    except (ValueError, KeyError, HTTPError, URLError, TimeoutError) as exc:
        detail = f'HTTP {exc.code}' if isinstance(exc, HTTPError) else str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print('n8n deployment failed: ' + detail, file=sys.stderr)
        sys.exit(1)
