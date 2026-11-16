"""Ship deployment outcome to Datadog without including command output or secrets."""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SITES = {'datadoghq.com', 'us3.datadoghq.com', 'us5.datadoghq.com', 'datadoghq.eu',
         'ap1.datadoghq.com', 'ap2.datadoghq.com', 'ddog-gov.com'}


def report(env, send=urlopen):
    key = env.get('DD_API_KEY')
    if not key:
        print('Datadog deployment logs disabled: DD_API_KEY is not configured')
        return
    site = env.get('DD_SITE') or 'us5.datadoghq.com'
    if site not in SITES:
        raise ValueError('Unsupported DD_SITE')
    record = {'ddsource': 'github', 'service': 'bun2too-deployment',
              'message': 'Deployment ' + env.get('DEPLOY_STATUS', 'unknown'),
              'ddtags': 'env:' + env.get('DEPLOY_ENVIRONMENT', 'unknown'),
              'git_sha': env.get('GITHUB_SHA'), 'github_run_id': env.get('GITHUB_RUN_ID'),
              'operation': env.get('DEPLOY_OPERATION'), 'status': env.get('DEPLOY_STATUS')}
    request = Request(f'https://http-intake.logs.{site}/api/v2/logs', method='POST',
                      headers={'DD-API-KEY': key, 'Content-Type': 'application/json'},
                      data=json.dumps([record]).encode())
    with send(request, timeout=15) as response:
        print('Datadog deployment log accepted HTTP', response.status)


if __name__ == '__main__':
    try:
        report(os.environ)
    except Exception as exc:
        status = f' HTTP {exc.code}' if isinstance(exc, HTTPError) else ''
        print('Datadog deployment log failed: ' + type(exc).__name__ + status, file=sys.stderr)
        sys.exit(1)
