import io
import os
import shutil
import tempfile
from contextlib import redirect_stdout
import subprocess
import unittest
from unittest.mock import patch

from scripts.prepare_terraform_state import SHARED, prepare, state_addresses


class TerraformStateTests(unittest.TestCase):
    def env(self):
        return dict(GITHUB_REF_NAME='main', DEPLOY_ENVIRONMENT='production',
                    RAILWAY_API_TOKEN='secret', RAILWAY_PROJECT_ID='project',
                    RAILWAY_ENVIRONMENT_ID='prod', POSTGRES_SERVICE_ID='pg',
                    CREWAI_SERVICE_ID='crew')

    def request(self, url, token, payload):
        if 'id' in payload['variables']:
            return {'data': {'project': {
                'services': {'edges': [{'node': {'id': key, 'name': name}} for key, name in
                                      [('pg', 'postgres'), ('crew', 'crewai'), ('n8n', 'n8n-orchestrator')]]},
                'environments': {'edges': [{'node': {'id': 'prod', 'name': 'production'}}]}}}}
        return {'data': {'variablesForServiceDeployment': {'POSTGRES_PASSWORD': 'never-log-this',
                                                          'DATA_DIR': '/data'}}}

    def test_absent_state_has_actionable_error_without_apply(self):
        with self.assertRaisesRegex(ValueError, 'operation=import-state'):
            prepare(self.env(), read_state=lambda: set())

    def test_existing_legacy_state_passes(self):
        prepare(self.env(), read_state=lambda: set(SHARED))

    def test_missing_state_distinguished_from_access_failure(self):
        with patch('scripts.prepare_terraform_state.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 1, '', 'No state file was found!\nMore guidance')):
            self.assertEqual(state_addresses(), set())
        with patch('scripts.prepare_terraform_state.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 1, '', 'Unauthorized')):
            with self.assertRaisesRegex(ValueError, 'Cannot read'):
                state_addresses()

    def test_colored_missing_state_is_recognized(self):
        error = '\x1b[31mNo state file was found!\nGuidance\x1b[0m\n'
        with patch('scripts.prepare_terraform_state.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 1, '', error)) as command:
            self.assertEqual(state_addresses(), set())
            self.assertEqual(command.call_args.args[0], ['terraform', 'state', 'list', '-no-color'])

    def test_real_empty_directory_is_detected(self):
        if not shutil.which('terraform'):
            self.skipTest('Terraform is not installed')
        actual_run = subprocess.run
        with tempfile.TemporaryDirectory() as directory:
            def isolated_run(args, **kwargs):
                return actual_run(args, cwd=directory, **kwargs)
            with patch('scripts.prepare_terraform_state.subprocess.run', side_effect=isolated_run):
                self.assertEqual(state_addresses(), set())

    def test_backend_diagnostic_is_visible_and_redacted(self):
        output = io.StringIO()
        failure = 'Error: Unauthorized secret-sentinel Authorization: Bearer hidden-token'
        with patch.dict(os.environ, {'TF_API_TOKEN': 'secret-sentinel'}), redirect_stdout(output):
            with patch('scripts.prepare_terraform_state.subprocess.run', return_value=
                       subprocess.CompletedProcess([], 1, '', failure)):
                with self.assertRaisesRegex(ValueError, 'diagnostic above'):
                    state_addresses()
        self.assertIn('Unauthorized', output.getvalue())
        self.assertNotIn('secret-sentinel', output.getvalue())
        self.assertNotIn('hidden-token', output.getvalue())

    def test_import_uses_ids_and_skips_existing_state(self):
        states = iter([{'railway_project.fb_pipeline'}, {address + '[0]' for address in SHARED}])
        commands = []
        prepare(self.env(), True, lambda: next(states), self.request,
                lambda command: commands.append(command) or 0)
        self.assertEqual(len(commands), 5)  # three services and two existing variables
        self.assertTrue(all(command[:2] == ['terraform', 'import'] for command in commands))
        self.assertIn(['railway_service.n8n_engine[0]', 'n8n'], [c[-2:] for c in commands])
        self.assertIn(['railway_variable.postgres_password', 'pg:production:POSTGRES_PASSWORD'],
                      [c[-2:] for c in commands])
        self.assertNotIn('never-log-this', str(commands))

    def test_discovery_failure_prevents_all_imports(self):
        env = self.env()
        env['N8N_SERVICE_ID'] = 'foreign'
        commands = []
        with self.assertRaisesRegex(ValueError, 'distinct services'):
            prepare(env, True, lambda: set(), self.request, lambda c: commands.append(c) or 0)
        self.assertEqual(commands, [])

    def test_import_failure_stops_remaining_commands(self):
        commands = []
        with self.assertRaisesRegex(ValueError, 'Completed imports remain'):
            prepare(self.env(), True, lambda: set(), self.request,
                    lambda c: commands.append(c) or 1)
        self.assertEqual(len(commands), 1)

    def test_qa_cannot_import_production_resources(self):
        env = self.env()
        env['GITHUB_REF_NAME'] = 'qa'
        with self.assertRaisesRegex(ValueError, 'requires main'):
            prepare(env, True, lambda: self.fail('must not read state'))
