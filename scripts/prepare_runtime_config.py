"""Merge CI authentication into the Terraform runtime map without logging secrets."""
import json
import os
import re
from urllib.parse import urlsplit


def validate_telemetry_config(config):
    if config.get('TELEMETRY_ENABLED', 'false').lower() != 'true':
        return
    if config.get('OTEL_SDK_DISABLED', 'false').lower() == 'true':
        raise ValueError('Enabled telemetry conflicts with OTEL_SDK_DISABLED=true')
    if config.get('OTEL_EXPORTER_OTLP_PROTOCOL', 'http/protobuf') != 'http/protobuf':
        raise ValueError('Enterprise telemetry requires OTLP over HTTP: http/protobuf')
    for signal in ('TRACES', 'METRICS', 'LOGS'):
        value = config.get('OTEL_EXPORTER_OTLP_' + signal + '_ENDPOINT') or config.get('OTEL_EXPORTER_OTLP_ENDPOINT', '')
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme in {'https', 'http'} and parsed.hostname and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment)
            if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
                valid = valid and config.get('OTEL_ALLOW_INSECURE_HTTP') == 'true'
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('Configure a valid authenticated HTTPS OTLP endpoint or approved private HTTP endpoint for ' + signal)


def validate_scheduled_config(config):
    """Validate declared inputs locally; no running application is required."""
    problems = []
    for name in ('LLM_MODEL', 'FACEBOOK_PAGE_ACCESS_TOKEN'):
        if not config.get(name, '').strip():
            problems.append('missing ' + name)
    for name in ('MARKETING_AUTOMATION_ENABLED', 'PUBLISHING_ENABLED'):
        if config.get(name, '') != 'true':
            problems.append(name + ' must be "true"')
    if config.get('WORKER_ENABLED', 'true').lower() != 'true':
        problems.append('WORKER_ENABLED must be "true"')
    if not re.fullmatch(r'v\d+\.\d+', config.get('FACEBOOK_GRAPH_VERSION', '')):
        problems.append('FACEBOOK_GRAPH_VERSION must have format v<number>.<number>')
    if not re.fullmatch(r'\d+', config.get('FACEBOOK_PAGE_ID', '')):
        problems.append('FACEBOOK_PAGE_ID must be a numeric Page ID')
    try:
        base = urlsplit(config.get('PUBLIC_API_BASE_URL', ''))
    except ValueError:
        base = urlsplit('')
    if base.scheme != 'https' or not base.hostname or base.username or base.password:
        problems.append('PUBLIC_API_BASE_URL must be HTTPS without credentials')
    if config.get('TELEMETRY_ENABLED', 'false').lower() != 'true' and config.get('DD_LOGS_ENABLED', 'false').lower() == 'true' and not config.get('DD_API_KEY', '').strip():
        problems.append('missing DD_API_KEY for enabled runtime logs')
    if problems:
        raise ValueError('Incomplete MARKETING_RUNTIME_CONFIG for scheduled deploy: ' + '; '.join(problems)
                         + '. Configure the JSON secret in the selected GitHub environment. '
                         'See docs/deployment.md, runtime JSON secrets. No Railway API was contacted.')


def prepare(env):
    try:
        config = json.loads(env.get('MARKETING_RUNTIME_CONFIG') or '{}')
    except ValueError:
        raise ValueError('MARKETING_RUNTIME_CONFIG must contain valid JSON') from None
    if not isinstance(config, dict) or any(not isinstance(v, str) for v in config.values()):
        raise ValueError('MARKETING_RUNTIME_CONFIG must be a JSON object of strings')
    key = env.get('MARKETING_API_KEY', '')
    if env.get('DEPLOY_OPERATION', 'deploy') == 'deploy' and not key.strip():
        raise ValueError('MARKETING_API_KEY is required for deployment')
    if key:
        config['MARKETING_API_KEY'] = key
    if env.get('GITHUB_SHA'):
        config.setdefault('SERVICE_VERSION', env['GITHUB_SHA'])
    if env.get('DEPLOY_OPERATION', 'deploy') == 'deploy':
        validate_telemetry_config(config)
        validate_scheduled_config(config)
    return json.dumps(config, ensure_ascii=True)


if __name__ == '__main__':
    try:
        config = prepare(os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc))
    with open(os.environ['GITHUB_ENV'], 'a') as output:
        output.write('TF_VAR_marketing_runtime_config=' + config + '\n')
