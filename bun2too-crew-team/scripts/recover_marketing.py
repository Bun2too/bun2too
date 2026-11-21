"""Inspect publishing or explicitly clear a repaired billing pause; never send posts."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RecoveryError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_json(url, headers, method='GET', payload=None):
    request = Request(url, headers={**headers, 'Accept': 'application/json',
                      'Content-Type': 'application/json',
                      'User-Agent': 'crew-team-deployment-preflight/1.0'}, method=method,
                      data=json.dumps(payload).encode() if payload is not None else None)
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise RecoveryError('Diagnostic response exceeds the bounded response limit')
    return json.loads(raw)


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise RecoveryError('Service origins must be HTTPS without credentials, paths, queries or fragments')
    return value.rstrip('/')


def fields(value, names):
    return {name: value[name] for name in names if name in value}


def diagnostic(value):
    if not isinstance(value, dict):
        return None
    return {'causes': [fields(cause, ('type', 'kind', 'status_code', 'provider_code', 'provider_type'))
                       for cause in (value.get('causes') or [value])[:5] if isinstance(cause, dict)]}


def run_summary(run):
    result = fields(run, ('id', 'run_id', 'status', 'created_at', 'updated_at', 'attempt', 'attempts',
                         'scheduled', 'publish_after', 'publish_before', 'failure_category', 'retryable'))
    result['error'] = diagnostic(run.get('error_details') or run.get('error'))
    result['completed_roles'] = [task.get('agent') for task in run.get('tasks', [])[-12:]]
    result['model_routes'] = fields(run.get('generation_settings') or {}, ('model', 'role_models'))
    return result


def clean(value, env):
    # Defense in depth for all selected strings; never serialize raw API responses.
    secrets = [env.get(key) for key in ('MARKETING_API_KEY', 'N8N_API_KEY') if env.get(key)]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value[:500]
    if isinstance(value, list):
        return [clean(item, env) for item in value]
    if isinstance(value, dict):
        return {key: clean(item, env) for key, item in value.items()}
    return value


def recover(env, action, request=http_json):
    if action not in {'inspect', 'resume'}:
        raise RecoveryError('Choose inspect or resume')
    for name in ('CREWAI_BASE_URL', 'MARKETING_API_KEY', 'N8N_BASE_URL', 'N8N_API_KEY'):
        if not env.get(name):
            raise RecoveryError('Missing ' + name)
    crew, n8n = origin(env['CREWAI_BASE_URL']), origin(env['N8N_BASE_URL'])
    crew_headers = {'Authorization': 'Bearer ' + env['MARKETING_API_KEY']}
    n8n_headers = {'X-N8N-API-KEY': env['N8N_API_KEY']}

    def call(base, headers, path, method='GET', payload=None):
        try:
            return request(base + path, headers, method, payload)
        except HTTPError as exc:
            raise RecoveryError(f'{method} {path.split("?")[0]} failed HTTP {exc.code}; '
                                'response body withheld; no automatic mutation retry') from None
        except RecoveryError:
            raise
        except Exception as exc:
            raise RecoveryError(f'{method} {path.split("?")[0]} failed ({type(exc).__name__}); '
                                'no automatic mutation retry') from None

    ready = call(crew, crew_headers, '/ready')
    operations = call(crew, crew_headers, '/automation/operations/status')
    campaigns = call(crew, crew_headers, '/automation/status')
    circuit = operations.get('generation_circuit')
    report = {'action': action, 'ready': fields(ready, ('model_configured', 'worker_ready',
              'publishing_enabled', 'automation_enabled', 'missing_configuration', 'queued_runs')),
              'before': {'generation_circuit': fields(circuit, ('status', 'category', 'run_id', 'opened_at'))
                         if circuit else None, 'watchdog': operations.get('watchdog')},
              'runs': [run_summary(run) for run in campaigns.get('runs', [])[:12]],
              'publications': [fields(post, ('id', 'run_id', 'status', 'created_at', 'remote_id', 'post_id'))
                               for post in campaigns.get('publications', [])[:8]]}
    print(json.dumps(clean(report, env), sort_keys=True), flush=True)
    targets = [circuit['run_id']] if circuit and circuit.get('run_id') else []
    targets += [run.get('id') or run.get('run_id') for run in campaigns.get('runs', [])[:2]]
    report['run_evidence'] = []
    for run_id in dict.fromkeys(targets):
        if not run_id:
            continue
        path = '/runs/' + quote(str(run_id), safe='')
        run = call(crew, crew_headers, path)
        work = call(crew, crew_headers, path + '/work')
        evidence = run_summary(run)
        evidence['events'] = []
        for event in work.get('events', [])[-12:]:
            summary = fields(event, ('kind', 'at', 'agent', 'status', 'operation', 'attempt', 'category'))
            if event.get('error'):
                summary['error'] = diagnostic(event['error'])
            evidence['events'].append(summary)
        report['run_evidence'].append(evidence)

    workflows, path = [], '/api/v1/workflows?limit=100'
    for _ in range(5):
        page = call(n8n, n8n_headers, path)
        workflows.extend(page.get('data', []))
        if not page.get('nextCursor'):
            break
        path = '/api/v1/workflows?limit=100&cursor=' + quote(page['nextCursor'], safe='')
    else:
        raise RecoveryError('Workflow discovery exceeded five pages; inspection is incomplete')
    report['workflows'] = []
    for workflow in workflows:
        record = fields(workflow, ('id', 'name', 'active', 'updatedAt'))
        record['settings'] = fields(workflow.get('settings') or {}, ('timezone', 'errorWorkflow'))
        record['schedules'] = [node.get('parameters', {}).get('rule') for node in workflow.get('nodes', [])
                               if node.get('type') == 'n8n-nodes-base.scheduleTrigger']
        report['workflows'].append(record)
    executions = call(n8n, n8n_headers, '/api/v1/executions?limit=12&includeData=false')
    report['executions'] = [fields(item, ('id', 'workflowId', 'status', 'finished', 'startedAt',
                                          'stoppedAt', 'waitTill')) for item in executions.get('data', [])]
    for execution in executions.get('data', [])[:3]:
        detail = call(n8n, n8n_headers, '/api/v1/executions/' + quote(str(execution['id']), safe='') + '?includeData=true')
        result = (detail.get('data') or {}).get('resultData') or {}
        report.setdefault('execution_evidence', []).append({
            'id': execution['id'], 'last_node': result.get('lastNodeExecuted'),
            'error': fields(result.get('error') or {}, ('name', 'type', 'httpCode', 'statusCode'))})

    # Print inspection before a mutation, so failures retain the relevant safe evidence.
    report = clean(report, env)
    print(json.dumps(report, sort_keys=True), flush=True)
    if action == 'resume' and circuit:
        if circuit.get('category') != 'provider_billing':
            raise RecoveryError('Resume requires a diagnosed provider billing pause after billing repair')
        reviewer = 'GitHub operator ' + env.get('GITHUB_ACTOR', 'local-operator') + ': billing restored'
        call(crew, crew_headers, '/automation/recovery/resume', 'POST', {'reviewer': reviewer[:200]})
        after = call(crew, crew_headers, '/automation/operations/status')
        if after.get('generation_circuit'):
            raise RecoveryError('Generation circuit remains open after resume; inspect provider access')
        report['after'] = {'generation_circuit': None, 'status': 'ready_for_future_scheduled_generation'}
        print(json.dumps({'after': report['after']}, sort_keys=True), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'resume'))
    args = parser.parse_args()
    try:
        recover(os.environ, args.action)
    except RecoveryError as exc:
        print('Recovery failed: ' + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print('Recovery failed: ' + type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
