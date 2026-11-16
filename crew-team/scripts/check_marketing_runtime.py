"""Read-only, authenticated runtime checks; never generates or publishes content."""
import json
import os
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler


API_USER_AGENT = 'crew-team-deployment-preflight/1.0'


class ConfigurationError(RuntimeError):
    pass


def configuration_problems(result):
    problems = []
    if not result.get('model_configured'):
        problems.append('LLM_MODEL is not configured in the deployed service')
    if result.get('automation_enabled') != 'true':
        problems.append('MARKETING_AUTOMATION_ENABLED must be "true" in the deployed service')
    missing = result.get('missing_configuration') or []
    if 'marketing_profile' in missing:
        problems.append('Marketing profile is incomplete or invalid. Edit crewai_agents/config/marketing.json '
                        '(audience and business_facts ship as placeholders), or fix the file selected by '
                        'MARKETING_PROFILE_PATH. This is a profile file error, not a missing API secret')
    if any(item != 'marketing_profile' for item in missing):
        problems.append('/ready reports missing runtime configuration; check MARKETING_RUNTIME_CONFIG')
    return problems


def error_metadata(error, token):
    """Report selected diagnostic headers and a recognized edge code, never raw bodies."""
    metadata = {}
    for name in ('Content-Type', 'Server', 'CF-Ray', 'CF-Mitigated',
                 'X-Railway-Request-ID', 'X-Request-ID'):
        value = error.headers.get(name) if error.headers else None
        if isinstance(value, str):
            metadata[name.lower()] = (value.replace(token, '[REDACTED]') if token else value)[:200]
    try:
        body = error.read(4096).decode('utf-8', errors='replace')
        try:
            problem = json.loads(body)
        except ValueError:
            problem = None
        json_1010 = isinstance(problem, dict) and problem.get('type') == (
            'https://developers.cloudflare.com/support/troubleshooting/'
            'http-status-codes/cloudflare-1xxx-errors/error-1010/')
        if (metadata.get('server', '').lower() == 'cloudflare'
                and (re.fullmatch(r'\s*error code:\s*1010\s*', body) or json_1010)):
            metadata['edge_error'] = 'Cloudflare 1010: request/browser signature denied'
    except Exception:
        pass  # Diagnostics must not obscure the original HTTP failure.
    return metadata


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check():
    from urllib.parse import urlsplit
    base = os.environ['CREWAI_BASE_URL'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('CREWAI_BASE_URL must be HTTPS without credentials')
    token = os.environ['MARKETING_API_KEY']
    for attempt in range(1, 13):
        try:
            results = {}
            for path in ('/ready',):
                request = Request(base + path, headers={
                    'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json',
                    'User-Agent': API_USER_AGENT,
                })
                with build_opener(NoRedirect).open(request, timeout=30) as response:
                    results[path] = json.load(response)
                print(json.dumps({'check': path, 'result': results[path]}, sort_keys=True), flush=True)
            result = results['/ready']
            problems = configuration_problems(result)
            if problems:
                raise ConfigurationError('; '.join(problems) +
                                         '. Correct the indicated configuration and redeploy.')
            if not result.get('worker_ready'):
                raise ValueError('Worker is not ready')
            for path in ('/automation/delivery-check', '/automation/research-check'):
                request = Request(base + path, headers={
                    'Authorization': 'Bearer ' + token,
                    'Accept': 'application/json',
                    'User-Agent': API_USER_AGENT,
                })
                with build_opener(NoRedirect).open(request, timeout=30) as response:
                    results[path] = json.load(response)
                print(json.dumps({'check': path, 'result': results[path]}, sort_keys=True), flush=True)
            if results['/automation/delivery-check'].get('status') != 'ready':
                raise ValueError('Facebook Page delivery check is not ready')
            research = results['/automation/research-check']
            if research.get('status') != 'ready' or not research.get('recent_item_count'):
                raise ValueError('Current-topic research check is not ready')
            return
        except ConfigurationError:
            raise  # Static settings will not change by retrying the same deployment.
        except Exception as exc:
            # URLs, tokens and HTTP bodies are deliberately excluded.
            status = f' http_status={exc.code}' if isinstance(exc, HTTPError) else ''
            print(f'Runtime integration checks attempt={attempt}/12 error_type={type(exc).__name__}{status}', flush=True)
            if isinstance(exc, HTTPError):
                print('Runtime HTTP diagnostics: ' + json.dumps(error_metadata(exc, token), sort_keys=True), flush=True)
            if attempt == 12:
                raise RuntimeError('Runtime integration checks failed; inspect Railway logs and authenticated preflight endpoints') from None
            time.sleep(5)


if __name__ == '__main__':
    try:
        check()
    except ConfigurationError as exc:
        print('::error::' + str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print('Runtime check failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
