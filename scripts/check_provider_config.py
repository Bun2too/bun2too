"""Read back configured provider credentials without printing values or hashes."""
import json
import os
import sys

from scripts.check_deployment import request_json

KEYS = ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY')


def verify(env, request=request_json):
    config = json.loads(env['TF_VAR_marketing_runtime_config'])
    expected = {name: config[name] for name in KEYS if config.get(name)}
    if not expected:
        print('No provider credentials declared in the runtime map; nothing to compare.')
        return
    result = request('https://backboard.railway.com/graphql/v2', env['RAILWAY_API_TOKEN'], {
        'query': 'query($projectId: String!, $environmentId: String!, $serviceId: String!) { '
                 'variablesForServiceDeployment(projectId: $projectId, environmentId: $environmentId, '
                 'serviceId: $serviceId) }',
        'variables': {'projectId': env['RAILWAY_PROJECT_ID'],
                      'environmentId': env['RAILWAY_ENVIRONMENT_ID'],
                      'serviceId': env['CREWAI_SERVICE_ID']},
    })
    actual = (result.get('data') or {}).get('variablesForServiceDeployment')
    if result.get('errors') or not isinstance(actual, dict):
        raise ValueError('Cannot read Railway provider configuration; verify target IDs and API access')
    mismatches = [name for name, value in expected.items() if actual.get(name) != value]
    if mismatches:
        raise ValueError('Railway provider credentials differ from prepared GitHub configuration or are '
                         'unavailable for read-back: ' + ', '.join(mismatches))
    print('Railway provider credentials match prepared GitHub configuration: ' + ', '.join(expected)
          + '. This verifies configuration equality, not provider authorization.')


if __name__ == '__main__':
    try:
        verify(os.environ)
    except Exception as exc:
        # Only locally authored ValueError messages are safe; network responses are not.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print('::error::Provider configuration verification failed: ' + message, file=sys.stderr)
        sys.exit(1)
