"""Reject destructive n8n storage changes before applying a saved Terraform plan.

Terraform JSON contains secrets. Capture it in memory; never print its contents.
"""
import json
import os
import subprocess
import sys

if __package__:
    from .check_deployment import request_json
    from .ensure_n8n_volume import ensure
else:
    from check_deployment import request_json
    from ensure_n8n_volume import ensure

PROTECTED = ('N8N_ENCRYPTION_KEY', 'N8N_USER_FOLDER', 'DB_TYPE', 'DB_SQLITE_DATABASE',
             'DB_POSTGRESDB_HOST', 'DB_POSTGRESDB_PORT', 'DB_POSTGRESDB_DATABASE',
             'DB_POSTGRESDB_SCHEMA', 'N8N_ENCRYPTION_KEY_FILE')
DEFAULTS = {'N8N_USER_FOLDER': '/home/node', 'DB_TYPE': 'sqlite',
            'DB_SQLITE_DATABASE': 'database.sqlite'}


def current_variables(env, request=request_json):
    """Protect settings that predate Terraform or were written by a failed apply."""
    if not env.get('N8N_SERVICE_ID'):
        raise ValueError('Set N8N_SERVICE_ID to verify existing n8n storage configuration')
    result = request('https://backboard.railway.com/graphql/v2', env['RAILWAY_API_TOKEN'], {
        'query': 'query($projectId: String!, $environmentId: String!, $serviceId: String!) { '
                 'variablesForServiceDeployment(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) }',
        'variables': {'projectId': env['RAILWAY_PROJECT_ID'], 'environmentId': env['RAILWAY_ENVIRONMENT_ID'],
                      'serviceId': env['N8N_SERVICE_ID']},
    })
    values = (result.get('data') or {}).get('variablesForServiceDeployment')
    if result.get('errors') or not isinstance(values, dict):
        raise ValueError('Cannot verify existing n8n storage settings through Railway; no apply attempted')
    return values


def validate(plan, env, existing=None, volume_verified=False):
    old_variables, new_variables = {}, {}
    for resource in plan.get('resource_changes', []):
        change = resource['change']
        before, after = change.get('before') or {}, change.get('after') or {}
        actions = change['actions']
        if resource['type'] == 'railway_service' and resource['name'] == 'n8n_engine':
            if 'delete' in actions:
                raise ValueError('Refusing to delete or replace the n8n service and its persistent data')
            old_volume, new_volume = before.get('volume'), after.get('volume')
            if not new_volume and not old_volume and volume_verified:
                continue  # Provider can miss an attachment that the scoped API verified.
            if not new_volume or new_volume.get('mount_path') != '/home/node/.n8n':
                raise ValueError('n8n must retain a volume mounted at /home/node/.n8n')
            if old_volume:
                if any(old_volume.get(k) != new_volume.get(k) for k in ('name', 'mount_path')):
                    raise ValueError('Refusing to rename or move the existing n8n volume; migrate data separately')
            elif before and env.get('N8N_VOLUME_READY', '').lower() != 'true':
                raise ValueError('Existing n8n service has no persistent volume. Back up and prepare restoration of '
                                 '/home/node/.n8n (or confirm the instance is empty), then set N8N_VOLUME_READY=true '
                                 'for the storage migration. No apply has run.')
        if resource['name'] != 'n8n_runtime':
            continue
        if resource['type'] == 'railway_variable':
            if before.get('name'):
                old_variables[before['name']] = before.get('value')
        elif resource['type'] == 'railway_variable_collection':
            if 'delete' in actions:
                raise ValueError('Refusing to delete or replace the n8n runtime collection; this could remove its encryption key')
            old_variables.update({v['name']: v['value'] for v in before.get('variables', [])})
            new_variables.update({v['name']: v['value'] for v in after.get('variables', [])})
    if new_variables:
        if not new_variables.get('N8N_ENCRYPTION_KEY', '').strip():
            raise ValueError('N8N_RUNTIME_CONFIG must preserve the existing N8N_ENCRYPTION_KEY')
        for name in PROTECTED:
            if name in old_variables and old_variables[name] != new_variables.get(name, DEFAULTS.get(name)):
                raise ValueError('Refusing to change or remove ' + name + '; back up and migrate n8n separately')
            if existing is not None and name in existing and name in new_variables and existing[name] != new_variables[name]:
                raise ValueError('Refusing to overwrite the live n8n ' + name + '; preserve the existing value')
        for name, default in DEFAULTS.items():
            if name not in old_variables and new_variables.get(name, default) != default and (existing or {}).get(name) != new_variables.get(name):
                raise ValueError('Refusing an unverified n8n database/path migration via ' + name)
    # Production owns service volumes. QA volumes must be provisioned separately.
    if env.get('DEPLOY_ENVIRONMENT') == 'qa' and new_variables and not volume_verified and env.get('N8N_VOLUME_READY', '').lower() != 'true':
        raise ValueError('Confirm QA has its own volume at /home/node/.n8n and set N8N_VOLUME_READY=true before updating n8n')


if __name__ == '__main__':
    try:
        result = subprocess.run(['terraform', 'show', '-json', sys.argv[1]],
                                capture_output=True, text=True, check=True)
        plan = json.loads(result.stdout)
        has_runtime = any(r['type'] == 'railway_variable_collection' and r['name'] == 'n8n_runtime'
                          for r in plan.get('resource_changes', []))
        ensure(os.environ, verify_only=True)
        validate(plan, os.environ, current_variables(os.environ) if has_runtime else None, volume_verified=True)
    except ValueError as exc:
        # JSON parsing errors are kept generic; schema validation messages use fixed field names only.
        message = 'Cannot parse Terraform plan JSON' if isinstance(exc, json.JSONDecodeError) else str(exc)
        raise SystemExit('::error::' + message)
    except Exception:
        raise SystemExit('::error::Cannot inspect the saved Terraform plan; no apply attempted')
    print('n8n storage/key migration checks passed; applying the inspected plan is permitted.')
