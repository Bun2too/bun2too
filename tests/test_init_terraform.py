import subprocess
import unittest
from unittest.mock import Mock
from scripts.init_terraform import initialize, transient_provider_failure, COMMAND

FAILURE = '''Initializing HCP Terraform...
Error: Failed to install provider
Error while installing terraform-community-providers/railway v0.6.2: could
not query provider registry: failed to retrieve cryptographic signature for
provider: the request failed after 2 attempts: 504 Gateway Timeout returned
from github.com
'''


class InitTerraformTests(unittest.TestCase):
    def result(self, code, output=''):
        return subprocess.CompletedProcess(COMMAND, code, stdout=output)

    def test_reported_signature_download_failure_then_success(self):
        run=Mock(side_effect=[self.result(1,FAILURE),self.result(0,'Initialized\n')]);sleep=Mock()
        self.assertEqual(initialize(run,sleep),0)
        self.assertEqual(run.call_count,2);sleep.assert_called_once_with(5)
        self.assertIn('-lockfile=readonly',run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs['timeout'],120)

    def test_three_total_attempts_then_nonzero(self):
        run=Mock(return_value=self.result(1,FAILURE));sleep=Mock()
        self.assertEqual(initialize(run,sleep),1)
        self.assertEqual(run.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[5,15])

    def test_never_retry_authentication_integrity_backend_or_mixed_failure(self):
        for output in [FAILURE+'\nError: Backend configuration invalid',
                       FAILURE.replace('504 Gateway Timeout','403 Forbidden'),
                       FAILURE.replace('504 Gateway Timeout','checksum mismatch'),
                       FAILURE.replace('504 Gateway Timeout','signature verification failed'),
                       'Error: Backend unavailable: 504 Gateway Timeout',
                       'Error: Failed to install provider\ncertificate verification failed',
                       'Error: Failed to install provider\nno available releases']:
            with self.subTest(output=output):
                run=Mock(return_value=self.result(1,output));sleep=Mock()
                self.assertEqual(initialize(run,sleep),1)
                run.assert_called_once();sleep.assert_not_called()

    def test_hang_and_missing_executable_stop_without_retry(self):
        for error,code in [(subprocess.TimeoutExpired(COMMAND,120),124),(FileNotFoundError(),127)]:
            run=Mock(side_effect=error);sleep=Mock()
            self.assertEqual(initialize(run,sleep),code)
            run.assert_called_once();sleep.assert_not_called()

    def test_success_has_no_wait(self):
        run=Mock(return_value=self.result(0));sleep=Mock()
        self.assertEqual(initialize(run,sleep),0)
        run.assert_called_once();sleep.assert_not_called()

    def test_readonly_lock_warning_stops_even_when_init_returns_success(self):
        run = Mock(return_value=self.result(0, 'Warning: Provider lock file not updated\nHCP Terraform has been successfully initialized!'))
        sleep = Mock()
        self.assertEqual(initialize(run, sleep), 1)
        run.assert_called_once()
        sleep.assert_not_called()
