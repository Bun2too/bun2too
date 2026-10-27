"""Upload CrewAI and wait for that exact Railway deployment before HTTP readiness."""
import json
import os
import subprocess
import sys
import time

from scripts.check_deployment import request_json


def cli_failure(exc):
    """Classify captured CLI failures without exposing arbitrary provider output."""
    output = ((exc.stderr or '') + '\n' + (exc.stdout or '')).lower()
    categories = [
        (('unauthorized', 'invalid token', 'not authorized', 'authentication'),
         'authentication rejected; verify account-token access to the selected project'),
        (('unexpected argument', 'unrecognized option'),
         'installed CLI does not support the upload arguments; inspect the recorded CLI version'),
        (('service not found', 'project not found', 'environment not found'),
         'selected deployment target was not found or is inaccessible'),
        (('timed out', 'timeout', 'connection', 'dns'),
         'network connection failed or timed out'),
    ]
    for markers, description in categories:
        if any(marker in output for marker in markers):
            return f'Railway upload failed (exit {exc.returncode}): {description}'
    return (f'Railway upload failed (exit {exc.returncode}); CLI error did not match a safe '
            'diagnostic category. Inspect Railway service activity; raw output is withheld.')


def deploy(env, run=subprocess.run, request=request_json, sleep=time.sleep,
           monotonic=time.monotonic, timeout=900):
    command = ['railway', 'up', '--project', env['RAILWAY_PROJECT_ID'],
               '--service', env['CREWAI_SERVICE_ID'], '--environment',
               env['RAILWAY_ENVIRONMENT_ID'], '--detach', '--json']
    # Terraform's provider uses RAILWAY_TOKEN for account tokens. The CLI instead
    # interprets it as a project token and prefers it over RAILWAY_API_TOKEN.
    cli_env = dict(env)
    cli_env.pop('RAILWAY_TOKEN', None)
    if not cli_env.get('RAILWAY_API_TOKEN'):
        raise RuntimeError('RAILWAY_API_TOKEN is required for the account-token upload')
    print('Uploading fresh CrewAI source: project=' + env['RAILWAY_PROJECT_ID']
          + ' environment=' + env['RAILWAY_ENVIRONMENT_ID']
          + ' service=' + env['CREWAI_SERVICE_ID']
          + ' authentication=account-token', flush=True)
    try:
        result = run(command, check=True, capture_output=True, text=True, timeout=300,
                     env=cli_env)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(cli_failure(exc)) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError('Railway upload timed out; reconcile service deployments before retrying') from None
    deployment_id = json.loads(result.stdout)['deploymentId']
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ValueError('Railway did not return a deployment ID')
    print('Uploaded Railway deployment ID: ' + deployment_id, flush=True)
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = request('https://backboard.railway.com/graphql/v2', env['RAILWAY_API_TOKEN'], {
            'query': 'query($id: String!) { deployment(id: $id) { id status } }',
            'variables': {'id': deployment_id},
        })
        deployment = (result.get('data') or {}).get('deployment')
        if result.get('errors') or not deployment or deployment.get('id') != deployment_id:
            raise RuntimeError('Cannot read the uploaded Railway deployment status')
        status = deployment.get('status')
        if status == 'SUCCESS':
            print('Uploaded Railway deployment reached SUCCESS; HTTP readiness can now run.', flush=True)
            return
        if status in {'FAILED', 'CRASHED', 'REMOVED', 'SKIPPED', 'CANCELED', 'CANCELLED'}:
            raise RuntimeError('Uploaded Railway deployment failed: ' + status)
        print('Waiting for uploaded Railway deployment to reach SUCCESS.', flush=True)
        sleep(5)
    raise RuntimeError('Timed out waiting for the uploaded Railway deployment; inspect Railway build/deploy logs')


if __name__ == '__main__':
    try:
        deploy(os.environ)
    except RuntimeError as exc:
        print('::error::' + str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # CLI/API output may contain secrets. Do not print captured output or exception text.
        print('::error::Railway upload/status check failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
