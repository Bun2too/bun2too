"""Read-only, authenticated runtime checks; never generates or publishes content."""
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler


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
            request = Request(base + '/ready', headers={'Authorization': 'Bearer ' + token})
            with build_opener(NoRedirect).open(request, timeout=15) as response:
                result = json.load(response)
            if (result.get('missing_configuration') or not result.get('model_configured') or
                    not result.get('worker_ready') or result.get('automation_enabled') != 'true'):
                print(json.dumps(result, sort_keys=True), flush=True)
                raise ValueError('Runtime is not ready')
            print(json.dumps(result, sort_keys=True), flush=True)
            return
        except Exception as exc:
            # URLs, tokens and HTTP bodies are deliberately excluded.
            status = f' http_status={exc.code}' if isinstance(exc, HTTPError) else ''
            print(f'Runtime check GET /ready attempt={attempt}/12 error_type={type(exc).__name__}{status}', flush=True)
            if attempt == 12:
                raise RuntimeError('Runtime readiness failed; inspect Railway logs and /ready') from None
            time.sleep(5)


if __name__ == '__main__':
    try:
        check()
    except Exception as exc:
        print('Runtime check failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
