import json
import unittest
from unittest.mock import Mock
from scripts import prepare_runtime_config, check_provider_config


class ProviderConfigTests(unittest.TestCase):
    def test_rotated_standalone_keys_override_old_json(self):
        env = {'DEPLOY_OPERATION': 'infrastructure-only',
               'MARKETING_RUNTIME_CONFIG': json.dumps({k: 'old' for k in check_provider_config.KEYS})}
        env.update({k: 'rotated-' + k for k in check_provider_config.KEYS})
        result = json.loads(prepare_runtime_config.prepare(env))
        for name in check_provider_config.KEYS:
            self.assertEqual(result[name], env[name])

    def test_absent_or_empty_standalone_retains_json_key(self):
        for value in ('', ' '):
            result = json.loads(prepare_runtime_config.prepare({
                'DEPLOY_OPERATION': 'infrastructure-only', 'OPENAI_API_KEY': value,
                'MARKETING_RUNTIME_CONFIG': '{"OPENAI_API_KEY":"existing"}'}))
            self.assertEqual(result['OPENAI_API_KEY'], 'existing')

    def test_readback_checks_correct_target_and_rejects_stale_key(self):
        env = dict(TF_VAR_marketing_runtime_config='{"OPENAI_API_KEY":"rotated-private"}',
                   RAILWAY_API_TOKEN='token', RAILWAY_PROJECT_ID='project',
                   RAILWAY_ENVIRONMENT_ID='qa', CREWAI_SERVICE_ID='crew')
        for actual in ({'OPENAI_API_KEY': 'old-private'}, {}, None):
            request = Mock(return_value={'data': {'variablesForServiceDeployment': actual}})
            with self.assertRaises(ValueError) as caught:
                check_provider_config.verify(env, request)
            self.assertNotIn('private', str(caught.exception))
        request = Mock(return_value={'data': {'variablesForServiceDeployment': {'OPENAI_API_KEY': 'rotated-private'}}})
        check_provider_config.verify(env, request)
        self.assertEqual(request.call_args.args[2]['variables'],
                         {'projectId': 'project', 'environmentId': 'qa', 'serviceId': 'crew'})

    def test_graphql_error_cannot_pass_even_with_matching_values(self):
        env = dict(TF_VAR_marketing_runtime_config='{"OPENAI_API_KEY":"private"}',
                   RAILWAY_API_TOKEN='token', RAILWAY_PROJECT_ID='project',
                   RAILWAY_ENVIRONMENT_ID='prod', CREWAI_SERVICE_ID='crew')
        with self.assertRaises(ValueError):
            check_provider_config.verify(env, Mock(return_value={
                'errors': [{'message': 'private'}],
                'data': {'variablesForServiceDeployment': {'OPENAI_API_KEY': 'private'}}}))
