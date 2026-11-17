import unittest
from unittest.mock import Mock
from scripts.check_n8n_storage_plan import current_variables, validate


def resource(kind, name, before, after, actions=None):
    return dict(type=kind, name=name, change=dict(before=before, after=after,
                                                actions=actions or ['update']))


def variables(values):
    return {'variables': [dict(name=k, value=v) for k, v in values.items()]}


class N8nStoragePlanTests(unittest.TestCase):
    def setUp(self):
        self.volume = {'name': 'n8n-data', 'mount_path': '/home/node/.n8n'}
        self.service = {'volume': self.volume}
        self.key = {'N8N_ENCRYPTION_KEY': 'existing-test-key'}

    def check(self, *resources, **env):
        validate({'resource_changes': list(resources)}, env)

    def test_first_instance_has_storage_before_owner_setup(self):
        self.check(resource('railway_service', 'n8n_engine', None, self.service, ['create']))

    def test_existing_ephemeral_instance_requires_migration_acknowledgement(self):
        r = resource('railway_service', 'n8n_engine', {'volume': None}, self.service)
        with self.assertRaisesRegex(ValueError, 'Back up'):
            self.check(r)
        self.check(r, N8N_VOLUME_READY='true')

    def test_existing_volume_is_retained_without_flag(self):
        self.check(resource('railway_service', 'n8n_engine', self.service, self.service), N8N_VOLUME_READY='false')

    def test_volume_detachment_replacement_and_moves_are_rejected(self):
        for after, actions in [({'volume': None}, ['update']),
                               ({'volume': dict(self.volume, mount_path='/other')}, ['update']),
                               ({'volume': dict(self.volume, name='empty-volume')}, ['update']),
                               (self.service, ['delete', 'create'])]:
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.check(resource('railway_service', 'n8n_engine', self.service, after, actions))

    def test_normal_runtime_update_preserves_key(self):
        self.check(resource('railway_variable_collection', 'n8n_runtime', variables(self.key),
                            variables(dict(self.key, WEBHOOK_URL='https://n8n.example'))))

    def test_key_removal_rotation_and_collection_deletion_are_rejected(self):
        for after, actions in [(variables({'WEBHOOK_URL': 'https://n8n.example'}), ['update']),
                               (variables({'N8N_ENCRYPTION_KEY': 'new-key'}), ['update']),
                               (None, ['delete'])]:
            with self.subTest(after=after), self.assertRaises(ValueError) as caught:
                self.check(resource('railway_variable_collection', 'n8n_runtime', variables(self.key), after, actions))
            self.assertNotIn('existing-test-key', str(caught.exception))
            self.assertNotIn('new-key', str(caught.exception))

    def test_legacy_state_key_is_protected_during_collection_migration(self):
        old = resource('railway_variable', 'n8n_runtime', {'name': 'N8N_ENCRYPTION_KEY', 'value': 'old-key'}, None, ['forget'])
        with self.assertRaisesRegex(ValueError, 'N8N_ENCRYPTION_KEY'):
            self.check(old, resource('railway_variable_collection', 'n8n_runtime', None, variables(self.key), ['create']))

    def test_database_location_changes_require_separate_migration(self):
        for name, value in [('DB_TYPE', 'postgresdb'), ('N8N_USER_FOLDER', '/elsewhere'), ('DB_SQLITE_DATABASE', 'new.sqlite')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(resource('railway_variable_collection', 'n8n_runtime', variables(self.key), variables(dict(self.key, **{name: value}))))

    def test_qa_requires_separate_volume_confirmation(self):
        r = resource('railway_variable_collection', 'n8n_runtime', variables(self.key), variables(self.key))
        with self.assertRaisesRegex(ValueError, 'QA'):
            self.check(r, DEPLOY_ENVIRONMENT='qa')
        self.check(r, DEPLOY_ENVIRONMENT='qa', N8N_VOLUME_READY='true')

    def test_untracked_live_encryption_key_cannot_be_overwritten(self):
        plan = {'resource_changes': [resource('railway_variable_collection', 'n8n_runtime', None, variables(self.key), ['create'])]}
        with self.assertRaisesRegex(ValueError, 'live n8n N8N_ENCRYPTION_KEY'):
            validate(plan, {}, {'N8N_ENCRYPTION_KEY': 'untracked-live-key'})
        validate(plan, {}, self.key)

    def test_live_lookup_targets_selected_service_and_fails_closed(self):
        env = dict(RAILWAY_API_TOKEN='test-token', RAILWAY_PROJECT_ID='project',
                   RAILWAY_ENVIRONMENT_ID='qa-env', N8N_SERVICE_ID='n8n-service')
        request = Mock(return_value={'data': {'variablesForServiceDeployment': self.key}})
        self.assertEqual(current_variables(env, request), self.key)
        self.assertEqual(request.call_args.args[2]['variables'],
                         dict(projectId='project', environmentId='qa-env', serviceId='n8n-service'))
        request.return_value = {'errors': [{'message': 'test-secret'}]}
        with self.assertRaises(ValueError) as caught:
            current_variables(env, request)
        self.assertNotIn('test-secret', str(caught.exception))
