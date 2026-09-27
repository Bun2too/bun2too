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


def deploy(env, request=api):
    required = ('N8N_BASE_URL', 'N8N_API_KEY', 'CREWAI_BASE_URL', 'N8N_MARKETING_CREDENTIAL_ID')
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
    error_workflow_id = None
    verified_workflows = []
    for source in sorted((ROOT / 'n8n').glob('*.json')):
        payload = render(json.loads(source.read_text()), crew, env['N8N_MARKETING_CREDENTIAL_ID'],
                         env.get('DEPLOY_ENVIRONMENT', 'production'), env.get('MARKETING_TIMEZONE', 'America/Chicago'))
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
