"""Upload CrewAI and wait for that exact Railway deployment before HTTP readiness."""
import json
import os
import subprocess
import sys
import time

from scripts.check_deployment import request_json


def deploy(env, run=subprocess.run, request=request_json, sleep=time.sleep,
           monotonic=time.monotonic, timeout=900):
    command = ['railway', 'up', '--project', env['RAILWAY_PROJECT_ID'],
               '--service', env['CREWAI_SERVICE_ID'], '--environment',
               env['RAILWAY_ENVIRONMENT_ID'], '--detach', '--json']
    result = run(command, check=True, capture_output=True, text=True, timeout=300)
    deployment_id = json.loads(result.stdout)['deploymentId']
    if not isinstance(deployment_id, str) or not deployment_id:
        raise ValueError('Railway did not return a deployment ID')
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
