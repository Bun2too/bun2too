"""Merge CI authentication into the Terraform runtime map without logging secrets."""
import json
import os


def prepare(env):
    config = json.loads(env.get('MARKETING_RUNTIME_CONFIG') or '{}')
    if not isinstance(config, dict) or any(not isinstance(v, str) for v in config.values()):
        raise ValueError('MARKETING_RUNTIME_CONFIG must be a JSON object of strings')
    key = env.get('MARKETING_API_KEY', '')
    if env.get('DEPLOY_OPERATION', 'deploy') == 'deploy' and not key.strip():
        raise ValueError('MARKETING_API_KEY is required for deployment')
    if key:
        config['MARKETING_API_KEY'] = key
    return json.dumps(config, ensure_ascii=True)


if __name__ == '__main__':
    try:
        config = prepare(os.environ)
    except (ValueError, TypeError):
        raise SystemExit('Invalid runtime configuration; expected a JSON string map and deployment API key')
    with open(os.environ['GITHUB_ENV'], 'a') as output:
        output.write('TF_VAR_marketing_runtime_config=' + config + '\n')
