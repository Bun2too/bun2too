import subprocess
import unittest
from unittest.mock import Mock

from scripts.apply_terraform import apply, missing_crewai_source, ROOT

FAILURE = '''Error: Client Error
  with railway_variable_collection.marketing_runtime[0],
Unable to redeploy service after variable collection updated, got error:
input:3: serviceInstanceRedeploy This deployment's source is no longer
available to rebuild. Push a new commit or run `railway up` to deploy.
'''


class ApplyTests(unittest.TestCase):
    def result(self, code=0, output=''):
        return subprocess.CompletedProcess([], code, stdout=output)

    def test_success_does_not_upload(self):
        run = Mock(return_value=self.result())
        self.assertEqual(apply('/tmp/test.tfplan', {'DEPLOY_OPERATION': 'deploy'}, run), 0)
        self.assertEqual(run.call_count, 1)

    def test_recovery_uploads_then_replans_and_inspects_before_apply(self):
        run = Mock(side_effect=[self.result(1, FAILURE)] + [self.result()] * 4)
        self.assertEqual(apply('/tmp/test.tfplan', {'DEPLOY_OPERATION': 'deploy'}, run), 0)
        commands = [call.args[0][2:] for call in run.call_args_list]
        self.assertEqual(commands[1][-2:], ['-m', 'scripts.deploy_crewai'])
        self.assertEqual(run.call_args_list[1].kwargs['cwd'], ROOT)
        self.assertEqual(commands[2][:2], ['terraform', 'plan'])
        self.assertTrue(commands[3][1].endswith('check_n8n_storage_plan.py'))
        self.assertEqual(commands[4], commands[0])

    def test_unrelated_or_mixed_errors_never_upload(self):
        for output in [FAILURE.replace('marketing_runtime', 'n8n_runtime'),
                       FAILURE + '\nError: another failure', 'Error: Unauthorized']:
            self.assertFalse(missing_crewai_source(output))
            run = Mock(return_value=self.result(1, output))
            self.assertEqual(apply('/tmp/test.tfplan', {'DEPLOY_OPERATION': 'deploy'}, run), 1)
            self.assertEqual(run.call_count, 1)

    def test_infrastructure_only_never_uploads(self):
        run = Mock(return_value=self.result(1, FAILURE))
        self.assertEqual(apply('/tmp/test.tfplan', {'DEPLOY_OPERATION': 'infrastructure-only'}, run), 1)
        self.assertEqual(run.call_count, 1)

    def test_each_recovery_failure_stops_without_looping(self):
        for index in range(4):
            run = Mock(side_effect=[self.result(1, FAILURE)] + [self.result()] * index + [self.result(7, FAILURE)])
            self.assertEqual(apply('/tmp/test.tfplan', {'DEPLOY_OPERATION': 'deploy'}, run), 7)
            self.assertEqual(run.call_count, index + 2)
