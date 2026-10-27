import json
import subprocess
import unittest
from unittest.mock import Mock

from scripts import deploy_crewai, prepare_runtime_config


class BootstrapTests(unittest.TestCase):
    def test_enterprise_telemetry_preflight_rejects_bad_endpoints_without_echoing_them(self):
        for endpoint in ('', 'grpc://collector:4317', 'https://user:private-secret@collector.example', 'http://public.example:4318'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError) as caught:
                prepare_runtime_config.validate_telemetry_config({'TELEMETRY_ENABLED': 'true', 'OTEL_EXPORTER_OTLP_ENDPOINT': endpoint})
            self.assertNotIn('private-secret', str(caught.exception))
        prepare_runtime_config.validate_telemetry_config({'TELEMETRY_ENABLED': 'true', 'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://collector.example'})

    def test_release_identity_uses_ci_commit_when_unspecified(self):
        config = json.loads(prepare_runtime_config.prepare({'DEPLOY_OPERATION': 'infrastructure-only', 'GITHUB_SHA': 'test-release'}))
        self.assertEqual(config['SERVICE_VERSION'], 'test-release')

    def setUp(self):
        self.env = dict(RAILWAY_PROJECT_ID='project', CREWAI_SERVICE_ID='service',
                        RAILWAY_ENVIRONMENT_ID='environment', RAILWAY_API_TOKEN='secret')
        self.run = Mock(return_value=Mock(stdout='{"deploymentId":"new-deployment"}'))
        self.sleep = Mock()

    def response(self, status, deployment_id='new-deployment'):
        return {'data': {'deployment': {'id': deployment_id, 'status': status}}}

    def test_first_deploy_waits_through_build_and_startup(self):
        request = Mock(side_effect=[self.response(s) for s in
                                   ('QUEUED', 'BUILDING', 'DEPLOYING', 'SUCCESS')])
        deploy_crewai.deploy(self.env, self.run, request, self.sleep)
        self.assertEqual(self.sleep.call_count, 3)
        for call in request.call_args_list:
            self.assertEqual(call.args[2]['variables'], {'id': 'new-deployment'})
            self.assertEqual(call.args[0], 'https://backboard.railway.com/graphql/v2')
        self.assertIn('--detach', self.run.call_args.args[0])

    def test_failed_or_wrong_deployment_cannot_pass(self):
        for response in [self.response('FAILED'), self.response('CRASHED'),
                         self.response('SUCCESS', 'previous-deployment'),
                         {'errors': [{'message': 'denied'}]}]:
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                deploy_crewai.deploy(self.env, self.run, Mock(return_value=response), self.sleep)

    def test_deployment_wait_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, 'Timed out'):
            deploy_crewai.deploy(self.env, self.run, Mock(return_value=self.response('BUILDING')),
                                 self.sleep, Mock(side_effect=[0, 0, 901]))

    def test_recovery_does_not_pass_terraform_token_to_cli(self):
        env = dict(self.env, RAILWAY_TOKEN='account-token-in-provider-alias', PATH='/bin')
        deploy_crewai.deploy(env, self.run, Mock(return_value=self.response('SUCCESS')), self.sleep)
        child_env = self.run.call_args.kwargs['env']
        self.assertNotIn('RAILWAY_TOKEN', child_env)
        self.assertEqual(child_env['RAILWAY_API_TOKEN'], self.env['RAILWAY_API_TOKEN'])
        self.assertEqual(child_env['PATH'], '/bin')
        self.assertIn('RAILWAY_TOKEN', env)

    def test_cli_failure_is_actionable_and_does_not_echo_secrets(self):
        for stderr, expected in [('Unauthorized token=private-key', 'authentication rejected'),
                                 ('unexpected argument --project private-key', 'upload arguments'),
                                 ('unknown private-key', 'safe diagnostic category')]:
            request = Mock()
            run = Mock(side_effect=subprocess.CalledProcessError(1, ['railway'], stderr=stderr))
            with self.assertRaises(RuntimeError) as caught:
                deploy_crewai.deploy(self.env, run, request, self.sleep)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('private-key', str(caught.exception))
            request.assert_not_called()

    def test_upload_failure_does_not_query_status(self):
        request = Mock()
        with self.assertRaises(ValueError):
            deploy_crewai.deploy(self.env, Mock(side_effect=ValueError()), request, self.sleep)
        request.assert_not_called()

    def test_standalone_key_is_deployed_and_other_config_preserved(self):
        config = json.loads(prepare_runtime_config.prepare({
            'MARKETING_API_KEY': 'current-key',
            'DEPLOY_OPERATION': 'infrastructure-only',
            'MARKETING_RUNTIME_CONFIG': '{"MARKETING_API_KEY":"old-key","LLM_MODEL":"model"}',
        }))
        self.assertEqual(config, {'MARKETING_API_KEY': 'current-key', 'LLM_MODEL': 'model'})
        self.assertEqual(json.loads(prepare_runtime_config.prepare({'MARKETING_API_KEY': 'first-key', 'DEPLOY_OPERATION': 'infrastructure-only'})),
                         {'MARKETING_API_KEY': 'first-key'})

    def test_infrastructure_operation_preserves_map_without_standalone_key(self):
        self.assertEqual(json.loads(prepare_runtime_config.prepare({
            'DEPLOY_OPERATION': 'infrastructure-only',
            'MARKETING_RUNTIME_CONFIG': '{"MARKETING_API_KEY":"existing"}',
        })), {'MARKETING_API_KEY': 'existing'})

    def test_invalid_config_and_missing_key_fail_locally(self):
        for env in [{}, {'MARKETING_API_KEY': 'key', 'MARKETING_RUNTIME_CONFIG': '[]'},
                    {'MARKETING_API_KEY': 'key', 'MARKETING_RUNTIME_CONFIG': '{"X":true}'}]:
            with self.subTest(env=env), self.assertRaises(ValueError):
                prepare_runtime_config.prepare(env)

    def test_key_only_full_deploy_reports_all_required_settings_without_secret(self):
        with self.assertRaises(ValueError) as caught:
            prepare_runtime_config.prepare({'MARKETING_API_KEY': 'private-key'})
        message = str(caught.exception)
        for name in ('LLM_MODEL', 'MARKETING_AUTOMATION_ENABLED', 'PUBLISHING_ENABLED',
                     'FACEBOOK_PAGE_ID', 'FACEBOOK_GRAPH_VERSION', 'FACEBOOK_PAGE_ACCESS_TOKEN',
                     'PUBLIC_API_BASE_URL'):
            self.assertIn(name, message)
        self.assertNotIn('private-key', message)

    def test_complete_declared_settings_can_bootstrap_without_live_api(self):
        config = dict(LLM_MODEL='provider/model', MARKETING_AUTOMATION_ENABLED='true',
                      PUBLISHING_ENABLED='true', FACEBOOK_PAGE_ID='123', FACEBOOK_GRAPH_VERSION='v1.0',
                      FACEBOOK_PAGE_ACCESS_TOKEN='page-key', PUBLIC_API_BASE_URL='https://crew.example')
        prepared = json.loads(prepare_runtime_config.prepare({
            'MARKETING_API_KEY': 'api-key', 'MARKETING_RUNTIME_CONFIG': json.dumps(config)}))
        self.assertEqual(prepared, dict(config, MARKETING_API_KEY='api-key'))
