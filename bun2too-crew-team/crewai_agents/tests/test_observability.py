import os
import unittest
from unittest.mock import patch

from crewai_agents.app.observability import action_span, workflow_span


class ObservabilityTests(unittest.TestCase):
    def test_run_spans_and_redaction_without_export(self):
        with patch.dict(os.environ, {
            'DD_INSTRUMENTATION_TELEMETRY_ENABLED': 'false',
            'DD_REMOTE_CONFIGURATION_ENABLED': 'false', 'DD_TRACE_ENABLED': 'false',
            'DD_LLMOBS_ENABLED': '1', 'DD_API_KEY': 'test-secret-value',
        }):
            from ddtrace.llmobs import LLMObs
            with patch('ddtrace.llmobs._writer.LLMObsSpanWriter.enqueue') as enqueue:
                LLMObs.enable(ml_app='bun2too-test', integrations_enabled=False,
                              agentless_enabled=True, site='us5.datadoghq.com', api_key='test-secret-value')
                try:
                    with workflow_span('test-run'):
                        with action_span('test-run', 'test.action', {'input': 'test-secret-value'}):
                            pass
                finally:
                    LLMObs.disable()
                self.assertEqual(enqueue.call_count, 2)
                self.assertIn('test-run', str(enqueue.call_args_list))
                self.assertNotIn('test-secret-value', str(enqueue.call_args_list))


if __name__ == '__main__':
    unittest.main()
