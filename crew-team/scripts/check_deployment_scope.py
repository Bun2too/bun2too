"""Fail before infrastructure changes when a full application deployment is incomplete."""
import os
from pathlib import Path
import sys


def check(env):
    operation = env.get('DEPLOY_OPERATION', 'deploy')
    if operation not in {'deploy', 'infrastructure-only', 'import-state'}:
        raise ValueError('Unknown DEPLOY_OPERATION')
    if operation != 'deploy':
        return f'{operation}: does not install or activate marketing workflows.'
    missing = [name for name in ('CREWAI_BASE_URL', 'MARKETING_API_KEY', 'N8N_BASE_URL',
                                 'N8N_API_KEY')
               if not env.get(name, '').strip()]
    problems = ['Missing GitHub environment settings: ' + ', '.join(missing)] if missing else []
    if env.get('N8N_ACTIVATE_WORKFLOWS', '').lower() != 'true':
        problems.append('Set N8N_ACTIVATE_WORKFLOWS=true for scheduled operation')
    if env.get('MARKETING_DEPLOY_ENABLED', '').lower() == 'false':
        problems.append('Remove the legacy MARKETING_DEPLOY_ENABLED=false setting or select infrastructure-only')
    if problems:
        raise ValueError('; '.join(problems) + '. Full deploy requires CrewAI readiness and active n8n workflows. '
                         'Use operation=infrastructure-only only when that limited scope is intended.')
    return 'deploy: infrastructure + CrewAI application + verified active n8n schedule; agent runtime is Railway.'


if __name__ == '__main__':
    try:
        message = check(os.environ)
        print(message)
        if os.getenv('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as output:
                output.write('\nDeployment scope: ' + message + '\n')
    except ValueError as exc:
        print('::error::' + str(exc), file=sys.stderr)
        sys.exit(1)
