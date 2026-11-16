"""Validate production state, or explicitly import existing Railway resources.

Run from terraform/ after init. Imports write HCP state, never apply configuration.
"""
import argparse
import os
import re
import subprocess
import sys

if __package__:
    from .check_deployment import api_check, request_json, trace
    from .run_deployment_step import run
else:
    from check_deployment import api_check, request_json, trace
    from run_deployment_step import run

SHARED = ('railway_project.fb_pipeline', 'railway_service.postgres_db',
          'railway_service.crewai_service', 'railway_service.n8n_engine')


def clean_diagnostic(value):
    # Terraform emits ANSI colors even when stdout/stderr are captured.
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    for name, secret in os.environ.items():
        if secret and any(marker in name.upper() for marker in ('TOKEN', 'PASSWORD', 'SECRET')):
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'(?i)Bearer\s+[^\s"\']+', 'Bearer [REDACTED]', value)
    return value.strip()


def state_addresses():
    trace('Terraform state inspection', command='terraform state list -no-color')
    result = subprocess.run(['terraform', 'state', 'list', '-no-color'], capture_output=True, text=True)
    trace('Terraform state inspection result', exit_code=result.returncode)
    if result.returncode:
        diagnostic = clean_diagnostic(result.stderr)
        # State-list diagnostics contain no state values. Log them as JSON fields
        # to escape newlines/workflow commands, and redact known credentials first.
        trace('Terraform state error', stderr=diagnostic[:8000],
              stdout=clean_diagnostic(result.stdout)[:8000])
        # Do not treat authentication, backend or network errors as empty state.
        if diagnostic.startswith('No state file was found!'):
            trace('Terraform state absent; initial migration or import is required')
            return set()
        raise ValueError('Cannot read Terraform state; see the Terraform state error diagnostic above. '
                         'No imports or apply were attempted.')
    return set(result.stdout.splitlines())


def missing_shared(addresses):
    return [address for address in SHARED
            if address not in addresses and address + '[0]' not in addresses]


def import_targets(env, request=request_json):
    for name in ('RAILWAY_API_TOKEN', 'RAILWAY_PROJECT_ID', 'RAILWAY_ENVIRONMENT_ID',
                 'POSTGRES_SERVICE_ID', 'CREWAI_SERVICE_ID'):
        if not env.get(name, '').strip():
            raise ValueError(f'Missing {name}; cannot prepare imports')
    endpoint = 'https://backboard.railway.com/graphql/v2'
    with api_check('Railway import target discovery'):
        result = request(endpoint, env['RAILWAY_API_TOKEN'], {
            'query': 'query($id: String!) { project(id: $id) { services { edges { node { id name } } } environments { edges { node { id name } } } } }',
            'variables': {'id': env['RAILWAY_PROJECT_ID']}})
        if result.get('errors'):
            raise ValueError('Railway import target lookup failed')
        project = result['data']['project']
        services = {edge['node']['id']: edge['node']['name'] for edge in project['services']['edges']}
        environments = {edge['node']['id']: edge['node']['name'] for edge in project['environments']['edges']}
        if environments.get(env['RAILWAY_ENVIRONMENT_ID']) != 'production':
            raise ValueError('Import target is not the production Railway environment')
        n8n = env.get('N8N_SERVICE_ID', '').strip()
        if not n8n:
            matches = [key for key, name in services.items() if name == 'n8n-orchestrator']
            if len(matches) != 1:
                raise ValueError('Cannot uniquely find n8n-orchestrator. Set production variable N8N_SERVICE_ID to its existing service ID.')
            n8n = matches[0]
        ids = [env['POSTGRES_SERVICE_ID'], env['CREWAI_SERVICE_ID'], n8n]
        if len(set(ids)) != 3 or not set(ids).issubset(services):
            raise ValueError('Postgres, CrewAI and n8n must be distinct services in the selected project')
    targets = dict(zip((address + '[0]' for address in SHARED), [env['RAILWAY_PROJECT_ID'], *ids]))
    # Read only known variable names; do not log values or raw response bodies.
    for service, resources in (
        (env['POSTGRES_SERVICE_ID'], {'POSTGRES_PASSWORD': 'railway_variable.postgres_password',
                                     **{key: f'railway_variable.postgres_config["{key}"]'
                                        for key in ('POSTGRES_USER', 'POSTGRES_DB', 'PGDATA')}}),
        (env['CREWAI_SERVICE_ID'], {'DATA_DIR': 'railway_variable.crewai_data_dir'}),
    ):
        with api_check('Railway existing variable discovery for import'):
            result = request(endpoint, env['RAILWAY_API_TOKEN'], {
                'query': 'query($projectId: String!, $environmentId: String!, $serviceId: String!) { variablesForServiceDeployment(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) }',
                'variables': {'projectId': env['RAILWAY_PROJECT_ID'],
                              'environmentId': env['RAILWAY_ENVIRONMENT_ID'], 'serviceId': service}})
            variables = (result.get('data') or {}).get('variablesForServiceDeployment')
            if result.get('errors') or not isinstance(variables, dict):
                raise ValueError('Cannot inspect existing variables for import')
            for name, address in resources.items():
                if name in variables:
                    targets[address] = f'{service}:production:{name}'
    return targets


def prepare(env, import_existing=False, read_state=state_addresses, request=request_json, execute=run):
    if env.get('DEPLOY_ENVIRONMENT') != 'production' or env.get('GITHUB_REF_NAME') != 'main':
        raise ValueError('Production state preparation requires main and the production environment')
    trace("Terraform state preparation", operation="import-state" if import_existing else "deploy",
          organization=env.get("TF_CLOUD_ORGANIZATION"), workspace=env.get("TF_WORKSPACE"))
    addresses = read_state()
    if not import_existing:
        missing = missing_shared(addresses)
        if missing:
            raise ValueError('Production HCP state is empty or incomplete. Missing: ' + ', '.join(missing)
                             + '. Migrate original state, or run this workflow manually on main with '
                             'operation=import-state to adopt existing resources. No apply was attempted.')
        trace('Production state guard passed')
        return
    # Discover/validate every import before the first write. Safe to resume partial imports.
    targets = import_targets(env, request)
    for address, resource_id in targets.items():
        legacy = address[:-3] if address.endswith('[0]') else address
        if address in addresses or legacy in addresses:
            trace('Import skipped; address already managed', address=address)
            continue
        code = execute(['terraform', 'import', '-input=false', '-no-color', '-lock-timeout=60s',
                        address, resource_id])
        if code:
            raise ValueError(f'Import failed for {address} (exit {code}); no apply attempted. '
                             'Completed imports remain in HCP state; rerun import-state after correcting the failure.')
    if missing_shared(read_state()):
        raise ValueError('Production state is still incomplete after imports; no apply attempted')
    trace('Existing resources imported; review the following plan before deploying')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-existing', action='store_true')
    args = parser.parse_args()
    try:
        prepare(os.environ, args.import_existing)
    except ValueError as exc:
        print('::error::' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
