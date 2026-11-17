import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CommandTraceTests(unittest.TestCase):
    def test_output_exit_code_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / 'summary.md'
            result = subprocess.run(
                [sys.executable, 'scripts/run_deployment_step.py', sys.executable,
                 '-c', 'print("command-output"); raise SystemExit(7)'],
                env={**os.environ, 'GITHUB_STEP_SUMMARY': str(summary)},
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout, 'command-output\n')
            self.assertIn('START command=', result.stderr)
            self.assertIn('exit_code=7', result.stderr)
            self.assertIn('duration_seconds=', result.stderr)
            self.assertIn('exit **7**', summary.read_text())

    def test_command_arguments_redact_known_secret(self):
        result = subprocess.run(
            [sys.executable, 'scripts/run_deployment_step.py', sys.executable,
             '-c', 'pass', 'secret-sentinel'],
            env={**os.environ, 'TF_API_TOKEN': 'secret-sentinel'},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('secret-sentinel', result.stderr)
        self.assertIn('[REDACTED]', result.stderr)

    def test_missing_command_preserves_failure(self):
        result = subprocess.run(
            [sys.executable, 'scripts/run_deployment_step.py', '/no-such-deploy-command'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 127)
        self.assertIn('exit_code=127', result.stderr)
