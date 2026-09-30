import json
import unittest
from unittest.mock import Mock

from scripts import deploy_crewai, prepare_runtime_config


class BootstrapTests(unittest.TestCase):
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

    def test_upload_failure_does_not_query_status(self):
        request = Mock()
        with self.assertRaises(ValueError):
            deploy_crewai.deploy(self.env, Mock(side_effect=ValueError()), request, self.sleep)
        request.assert_not_called()

    def test_standalone_key_is_deployed_and_other_config_preserved(self):
        config = json.loads(prepare_runtime_config.prepare({
            'MARKETING_API_KEY': 'current-key',
            'MARKETING_RUNTIME_CONFIG': '{"MARKETING_API_KEY":"old-key","LLM_MODEL":"model"}',
        }))
        self.assertEqual(config, {'MARKETING_API_KEY': 'current-key', 'LLM_MODEL': 'model'})
        self.assertEqual(json.loads(prepare_runtime_config.prepare({'MARKETING_API_KEY': 'first-key'})),
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
