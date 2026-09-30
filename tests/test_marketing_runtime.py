import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts import check_marketing_runtime as runtime


class RuntimeChecks(unittest.TestCase):
    def test_readiness_identifies_client_and_keeps_authentication(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO(json.dumps({
            'missing_configuration': [], 'model_configured': True,
            'worker_ready': True, 'automation_enabled': 'true',
        })))
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.dict(runtime.os.environ, CREWAI_BASE_URL='https://crew.example', MARKETING_API_KEY='secret'), \
                patch.object(runtime, 'build_opener', return_value=opener):
            runtime.check()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('User-agent'), runtime.API_USER_AGENT)
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret')
        self.assertEqual(request.get_header('Accept'), 'application/json')

    def test_cloudflare_diagnostics_are_bounded_and_redacted(self):
        error = HTTPError('https://crew.example/ready', 403, 'Forbidden', {
            'Server': 'cloudflare', 'CF-Ray': 'ray-secret',
            'Set-Cookie': 'private-cookie', 'Authorization': 'Bearer secret',
        }, io.BytesIO(b'error code: 1010\n'))
        metadata = runtime.error_metadata(error, 'secret')
        self.assertIn('1010', metadata['edge_error'])
        self.assertEqual(metadata['cf-ray'], 'ray-[REDACTED]')
        self.assertNotIn('private-cookie', json.dumps(metadata))
        self.assertNotIn('authorization', metadata)

    def test_failure_logs_diagnostics_without_response_body_or_token(self):
        def denied(*args, **kwargs):
            raise HTTPError('https://crew.example/ready', 403, 'secret',
                            {'Server': 'cloudflare'}, io.BytesIO(b'private body secret'))
        opener = Mock()
        opener.open.side_effect = denied
        output = io.StringIO()
        with patch.dict(runtime.os.environ, CREWAI_BASE_URL='https://crew.example', MARKETING_API_KEY='secret'), \
                patch.object(runtime, 'build_opener', return_value=opener), \
                patch.object(runtime.time, 'sleep'), redirect_stdout(output), \
                self.assertRaises(RuntimeError):
            runtime.check()
        self.assertIn('http_status=403', output.getvalue())
        self.assertIn('cloudflare', output.getvalue())
        self.assertNotIn('private body', output.getvalue())
        self.assertNotIn('secret', output.getvalue())

    def test_redirects_do_not_forward_credentials(self):
        self.assertIsNone(runtime.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_cloudflare_json_problem_is_classified_without_logging_detail(self):
        body = json.dumps({
            'type': 'https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/',
            'detail': 'private detail',
        }).encode()
        error = HTTPError('https://crew.example/ready', 403, '',
                          {'Server': 'cloudflare'}, io.BytesIO(body))
        metadata = runtime.error_metadata(error, 'secret')
        self.assertIn('1010', metadata['edge_error'])
        self.assertNotIn('private detail', json.dumps(metadata))
