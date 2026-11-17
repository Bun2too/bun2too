import unittest
from unittest.mock import Mock
from scripts.ensure_n8n_volume import ensure
from scripts.check_n8n_storage_plan import validate


class N8nVolumeTests(unittest.TestCase):
    def setUp(self):
        self.env = dict(RAILWAY_PROJECT_ID='project', RAILWAY_ENVIRONMENT_ID='production',
                        N8N_SERVICE_ID='n8n', RAILWAY_API_TOKEN='test-token', N8N_VOLUME_READY='true')

    def response(self, instances=None, name='n8n-data'):
        volumes = [] if instances is None else [{'node': {'id': 'volume', 'name': name,
                   'volumeInstances': {'edges': [{'node': i} for i in instances]}}}]
        return {'data': {'project': {'services': {'edges': [{'node': {'id': 'n8n'}}]},
                'environments': {'edges': [{'node': {'id': 'production'}}]},
                'volumes': {'edges': volumes}}}}

    def attached(self, **overrides):
        return self.response([dict(environmentId='production', serviceId='n8n',
                                   mountPath='/home/node/.n8n', **overrides)])

    def test_existing_attachment_is_reused_without_mutation(self):
        request = Mock(return_value=self.attached())
        self.assertEqual(ensure(self.env, request), 'volume')
        request.assert_called_once()

    def test_creation_targets_explicit_environment_and_waits_for_readback(self):
        request = Mock(side_effect=[self.response(), {'data': {'volumeCreate': {'volume': {'id': 'volume'}}}},
                                   self.response([]), self.attached()])
        sleep = Mock()
        self.assertEqual(ensure(self.env, request, sleep), 'volume')
        mutation = request.call_args_list[1].args[2]
        self.assertEqual(mutation['variables']['input'], dict(projectId='project', environmentId='production',
                          serviceId='n8n', mountPath='/home/node/.n8n'))
        sleep.assert_called_once_with(5)

    def test_orphaned_volume_from_previous_apply_is_not_replaced(self):
        request = Mock(return_value=self.response([]))
        with self.assertRaisesRegex(ValueError, 'unattached'):
            ensure(self.env, request)
        request.assert_called_once()

    def test_migration_requires_acknowledgement_and_verify_never_creates(self):
        for env, verify in [(dict(self.env, N8N_VOLUME_READY='false'), False), (self.env, True)]:
            request = Mock(return_value=self.response())
            with self.assertRaises(ValueError):
                ensure(env, request, verify_only=verify)
            request.assert_called_once()

    def test_wrong_mount_is_not_replaced(self):
        request = Mock(return_value=self.response([dict(environmentId='production', serviceId='n8n', mountPath='/old')]))
        with self.assertRaisesRegex(ValueError, 'another mount'):
            ensure(self.env, request)
        request.assert_called_once()

    def test_creation_timeout_is_not_blindly_retried(self):
        request = Mock(side_effect=[self.response(), TimeoutError()])
        with self.assertRaises(TimeoutError):
            ensure(self.env, request)
        self.assertEqual(request.call_count, 2)

    def test_provider_null_is_allowed_only_with_scoped_attachment_verification(self):
        plan = {'resource_changes': [dict(type='railway_service', name='n8n_engine',
                 change=dict(before={'volume': None}, after={'volume': None}, actions=['no-op']))]}
        with self.assertRaises(ValueError):
            validate(plan, self.env)
        validate(plan, self.env, volume_verified=True)

    def test_api_verification_does_not_allow_terraform_detachment(self):
        plan = {'resource_changes': [dict(type='railway_service', name='n8n_engine',
                 change=dict(before={'volume': {'name': 'n8n-data', 'mount_path': '/home/node/.n8n'}},
                             after={'volume': None}, actions=['update']))]}
        with self.assertRaises(ValueError):
            validate(plan, self.env, volume_verified=True)
