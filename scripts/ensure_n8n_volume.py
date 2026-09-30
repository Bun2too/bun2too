"""Ensure environment-scoped n8n storage without the provider's nested-volume update."""
import os
import sys
import time

if __package__:
    from .check_deployment import request_json
else:
    from check_deployment import request_json

ENDPOINT = 'https://backboard.railway.com/graphql/v2'
MOUNT = '/home/node/.n8n'


def lookup(env, request=request_json, pending_id=None):
    for name in ('RAILWAY_PROJECT_ID', 'RAILWAY_ENVIRONMENT_ID', 'N8N_SERVICE_ID', 'RAILWAY_API_TOKEN'):
        if not env.get(name, '').strip():
            raise ValueError('Missing ' + name + ' for n8n storage provisioning')
    result = request(ENDPOINT, env['RAILWAY_API_TOKEN'], {
        'query': 'query($id: String!) { project(id: $id) { '
                 'services { edges { node { id } } } environments { edges { node { id } } } '
                 'volumes { edges { node { id name volumeInstances { edges { node { '
                 'environmentId serviceId mountPath } } } } } } } }',
        'variables': {'id': env['RAILWAY_PROJECT_ID']},
    })
    project = (result.get('data') or {}).get('project')
    if result.get('errors') or not project:
        raise ValueError('Cannot inspect Railway n8n volumes')
    if env['N8N_SERVICE_ID'] not in {e['node']['id'] for e in project['services']['edges']}:
        raise ValueError('n8n service does not belong to the selected project')
    if env['RAILWAY_ENVIRONMENT_ID'] not in {e['node']['id'] for e in project['environments']['edges']}:
        raise ValueError('n8n environment does not belong to the selected project')
    matches, orphans = [], []
    for edge in project['volumes']['edges']:
        volume = edge['node']
        instances = [e['node'] for e in volume['volumeInstances']['edges']]
        if volume['name'] == 'n8n-data' and not instances and volume['id'] != pending_id:
            orphans.append(volume['id'])
        for instance in instances:
            if instance['environmentId'] != env['RAILWAY_ENVIRONMENT_ID']:
                continue
            if instance['serviceId'] == env['N8N_SERVICE_ID']:
                matches.append(dict(id=volume['id'], mount=instance['mountPath']))
            elif instance['serviceId'] is None and volume['id'] != pending_id and (volume['name'] == 'n8n-data' or instance['mountPath'] == MOUNT):
                orphans.append(volume['id'])
    if len(matches) > 1:
        raise ValueError('Multiple n8n volumes found; reconcile attachments without deleting data')
    if matches:
        if matches[0]['mount'] != MOUNT:
            raise ValueError('Existing n8n volume uses another mount path; migrate it without creating a replacement')
        return matches[0]['id']
    if orphans:
        raise ValueError('An unattached n8n volume may contain existing data. Reattach it in Railway before retrying; no new volume created')
    return None


def ensure(env, request=request_json, sleep=time.sleep, verify_only=False):
    volume_id = lookup(env, request)
    if volume_id:
        print('Existing n8n volume verified for the selected service/environment.', flush=True)
        return volume_id
    if verify_only:
        raise ValueError('No n8n volume attached to the selected service/environment')
    if env.get('N8N_VOLUME_READY', '').lower() != 'true':
        raise ValueError('Back up and prepare restoration of existing n8n data (or confirm it is empty), '
                         'then set N8N_VOLUME_READY=true before attaching storage')
    # Never retry a mutation blindly: a timeout can occur after successful creation.
    result = request(ENDPOINT, env['RAILWAY_API_TOKEN'], {
        'query': 'mutation($input: VolumeCreateInput!) { volumeCreate(input: $input) { volume { id } } }',
        'variables': {'input': {'projectId': env['RAILWAY_PROJECT_ID'],
                                'environmentId': env['RAILWAY_ENVIRONMENT_ID'],
                                'serviceId': env['N8N_SERVICE_ID'], 'mountPath': MOUNT}},
    })
    created = ((result.get('data') or {}).get('volumeCreate') or {}).get('volume')
    if result.get('errors') or not created or not created.get('id'):
        raise ValueError('Railway volume creation was not confirmed. Inspect existing volumes before retrying')
    for attempt in range(12):
        volume_id = lookup(env, request, pending_id=created['id'])
        if volume_id:
            if volume_id != created['id']:
                raise ValueError('Volume attachment changed during provisioning; inspect Railway before deploying')
            print('Created n8n volume and verified its environment-specific attachment.', flush=True)
            return volume_id
        if attempt < 11:
            sleep(5)
    raise ValueError('Volume created but attachment is not visible yet. Inspect Railway; no second volume was created')


if __name__ == '__main__':
    try:
        ensure(os.environ, verify_only='--verify-only' in sys.argv[1:])
    except ValueError as exc:
        raise SystemExit('::error::' + str(exc))
    except Exception as exc:
        raise SystemExit('::error::n8n volume operation failed: ' + type(exc).__name__ +
                         '. Inspect Railway volumes before retrying; creation may have succeeded.')
