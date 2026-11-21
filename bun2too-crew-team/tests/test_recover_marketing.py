import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from scripts import recover_marketing as recovery


class RecoveryTests(unittest.TestCase):
    def env(self):
        return dict(CREWAI_BASE_URL='https://crew.example', MARKETING_API_KEY='private-marketing',
                    N8N_BASE_URL='https://n8n.example', N8N_API_KEY='private-n8n', GITHUB_ACTOR='operator')

    def request(self, circuit=None, after=None):
        operations = iter([{'generation_circuit': circuit}, {'generation_circuit': after}])
        def call(url, headers, method='GET', payload=None):
            if url.endswith('/automation/operations/status'):
                return next(operations)
            if url.endswith('/automation/status'):
                return {'runs': [], 'publications': []}
            if '/api/v1/workflows?' in url or '/api/v1/executions?' in url:
                return {'data': []}
            if url.endswith('/automation/recovery/resume'):
                return {'status': 'ready'}
            return {}
        return Mock(side_effect=call)

    def test_inspection_never_mutates_and_omits_secrets_and_private_outputs(self):
        request = self.request()
        original = request.side_effect
        def call(url, headers, method='GET', payload=None):
            if url.endswith('/automation/status'):
                return {'runs': [{'id': 'one', 'status': 'failed', 'artifact': 'private draft',
                                  'error': {'causes': [{'type': 'RateLimitError', 'status_code': 429,
                                                      'provider_code': 'private-marketing'}]}}],
                        'publications': []}
            return original(url, headers, method, payload)
        request.side_effect = call
        output = io.StringIO()
        with redirect_stdout(output):
            report = recovery.recover(self.env(), 'inspect', request)
        text = json.dumps(report) + output.getvalue()
        for private in ('private-marketing', 'private-n8n', 'private draft'):
            self.assertNotIn(private, text)
        self.assertTrue(all(len(c.args) < 3 or c.args[2] == 'GET' for c in request.call_args_list))

    def test_resume_closes_billing_pause_without_replaying_expired_run(self):
        circuit = {'category': 'provider_billing', 'run_id': 'expired-run', 'status': 'open'}
        request = self.request(circuit)
        report = recovery.recover(self.env(), 'resume', request)
        mutations = [c for c in request.call_args_list if len(c.args) > 2 and c.args[2] == 'POST']
        self.assertEqual(len(mutations), 1)
        self.assertTrue(mutations[0].args[0].endswith('/automation/recovery/resume'))
        self.assertNotIn('run_id', mutations[0].args[3])
        self.assertIsNone(report['after']['generation_circuit'])

    def test_resume_rejects_unrelated_pause_without_mutating(self):
        request = self.request({'category': 'unexpected', 'status': 'open'})
        with self.assertRaisesRegex(recovery.RecoveryError, 'billing'):
            recovery.recover(self.env(), 'resume', request)
        self.assertFalse(any(len(c.args) > 2 and c.args[2] == 'POST' for c in request.call_args_list))

    def test_resume_already_closed_is_read_only(self):
        request = self.request()
        recovery.recover(self.env(), 'resume', request)
        self.assertFalse(any(len(c.args) > 2 and c.args[2] == 'POST' for c in request.call_args_list))

    def test_reopened_pause_is_failure(self):
        circuit = {'category': 'provider_billing', 'status': 'open'}
        with self.assertRaisesRegex(recovery.RecoveryError, 'remains open'):
            recovery.recover(self.env(), 'resume', self.request(circuit, circuit))

    def test_invalid_origins_fail_before_network(self):
        for url in ('http://crew.example', 'https://user:password@crew.example',
                    'https://crew.example?token=value', 'https://crew.example/#token'):
            request = Mock()
            with self.subTest(url=url), self.assertRaises(recovery.RecoveryError):
                recovery.recover(dict(self.env(), CREWAI_BASE_URL=url), 'inspect', request)
            request.assert_not_called()

    def test_http_failure_does_not_print_body_or_retry_a_resume(self):
        from urllib.error import HTTPError
        request = self.request({'category': 'provider_billing', 'status': 'open'})
        original = request.side_effect
        def call(url, headers, method='GET', payload=None):
            if method == 'POST':
                raise HTTPError(url, 502, 'private-provider-body', {}, io.BytesIO(b'private-secret'))
            return original(url, headers, method, payload)
        request.side_effect = call
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery.recover(self.env(), 'resume', request)
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(sum(len(c.args) > 2 and c.args[2] == 'POST' for c in request.call_args_list), 1)


if __name__ == '__main__':
    unittest.main()
