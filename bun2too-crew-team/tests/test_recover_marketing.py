import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock

from scripts import recover_marketing as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def env(self):
        return dict(CREWAI_BASE_URL='https://crew.example', MARKETING_API_KEY='private-marketing',
                    N8N_BASE_URL='https://n8n.example', N8N_API_KEY='private-n8n', GITHUB_ACTOR='operator')

    def test_resume_branch_guard_runs_before_the_protected_job(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/deploy.yml').read_text()
        validation, recovery_job = workflow.split('  publishing_recovery:', 1)
        self.assertIn('validate_publishing_recovery:', validation)
        self.assertIn("inputs.operation == 'resume-publishing' && github.ref_name != 'main'", validation)
        self.assertNotIn('\n    environment:', validation)
        self.assertIn('needs: validate_publishing_recovery', recovery_job)

    def request(self, circuit=None, after=None, before_resume=None,
                resume_contract='compare-and-resume/v1'):
        operations = iter([{'generation_circuit': circuit},
                           {'generation_circuit': before_resume if before_resume is not None else circuit},
                           {'generation_circuit': after}])
        def call(url, headers, method='GET', payload=None):
            if url.endswith('/automation/operations/status'):
                return {'watchdog': {'at': '2026-11-21T00:00:00Z', 'status': 'ok',
                                     'provider_message': 'private-watchdog-detail'},
                        'resume_contract': resume_contract, **next(operations)}
            if url.endswith('/automation/status'):
                return {'runs': [], 'publications': []}
            if '/api/v1/workflows?' in url or '/api/v1/executions?' in url:
                return {'data': []}
            if url.endswith('/automation/recovery/resume'):
                return {'status': 'ready', 'resumed_circuit': payload['expected_circuit']}
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
        for private in ('private-marketing', 'private-n8n', 'private draft', 'private-watchdog-detail'):
            self.assertNotIn(private, text)
        self.assertEqual(report['before']['watchdog'], {'at': '2026-11-21T00:00:00Z', 'status': 'ok'})
        self.assertTrue(all(len(c.args) < 3 or c.args[2] == 'GET' for c in request.call_args_list))

    def test_resume_closes_billing_pause_without_replaying_expired_run(self):
        circuit = {'category': 'provider_billing', 'run_id': 'expired-run',
                   'opened_at': '2026-11-15T14:06:40Z', 'status': 'open'}
        request = self.request(circuit)
        report = recovery.recover(self.env(), 'resume', request)
        mutations = [c for c in request.call_args_list if len(c.args) > 2 and c.args[2] == 'POST']
        self.assertEqual(len(mutations), 1)
        self.assertTrue(mutations[0].args[0].endswith('/automation/recovery/resume'))
        self.assertIsNone(mutations[0].args[3]['run_id'])
        self.assertEqual(mutations[0].args[3]['expected_circuit'], {
            'run_id': 'expired-run', 'opened_at': '2026-11-15T14:06:40Z', 'category': 'provider_billing'})
        self.assertIsNone(report['after']['generation_circuit'])

    def test_resume_rejects_unrelated_pause_without_mutating(self):
        request = self.request({'category': 'unexpected', 'status': 'open'})
        with self.assertRaisesRegex(recovery.RecoveryError, 'billing'):
            recovery.recover(self.env(), 'resume', request)
        self.assertFalse(any(len(c.args) > 2 and c.args[2] == 'POST' for c in request.call_args_list))

    def test_resume_already_closed_is_read_only(self):
        request = self.request()
        output = io.StringIO()
        with redirect_stdout(output):
            recovery.recover(self.env(), 'resume', request)
        self.assertIn('already_closed_no_change', output.getvalue())
        self.assertFalse(any(len(c.args) > 2 and c.args[2] == 'POST' for c in request.call_args_list))

    def test_resume_does_not_clear_a_different_pause_opened_after_inspection(self):
        first = {'category': 'provider_billing', 'run_id': 'run-a',
                 'opened_at': '2026-11-15T14:06:40Z', 'status': 'open'}
        second = {'category': 'provider_billing', 'run_id': 'run-b',
                  'opened_at': '2026-11-21T08:05:00Z', 'status': 'open'}
        request = self.request(first, before_resume=second)
        with self.assertRaisesRegex(recovery.RecoveryError, 'changed after inspection'):
            recovery.recover(self.env(), 'resume', request)
        self.assertFalse(any(len(call.args) > 2 and call.args[2] == 'POST' for call in request.call_args_list))

    def test_resume_refuses_old_server_without_compare_contract(self):
        circuit = {'category': 'provider_billing', 'run_id': 'run-a',
                   'opened_at': '2026-11-15T14:06:40Z', 'status': 'open'}
        request = self.request(circuit, resume_contract=None)
        with self.assertRaisesRegex(recovery.RecoveryError, 'lacks compare-and-resume/v1'):
            recovery.recover(self.env(), 'resume', request)
        self.assertFalse(any(len(call.args) > 2 and call.args[2] == 'POST' for call in request.call_args_list))

    def test_reopened_pause_is_failure(self):
        circuit = {'category': 'provider_billing', 'run_id': 'run-a',
                   'opened_at': '2026-11-15T14:06:40Z', 'status': 'open'}
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
        request = self.request({'category': 'provider_billing', 'run_id': 'run-a',
                                'opened_at': '2026-11-15T14:06:40Z', 'status': 'open'})
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
