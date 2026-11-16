import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from unittest.mock import Mock, patch

from langsmith import Client
from crewai_agents.app import langsmith_trace as ls, otel
from crewai_agents.app.store import Store


class LangSmithTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, LANGSMITH_TRACING='true', LANGSMITH_API_KEY='test-secret-langsmith',
                         LANGSMITH_AGENT_ID='crew-ai-agents', LANGSMITH_AGENT_ENVIRONMENT='local',
                         LANGSMITH_PROJECT='', LANGCHAIN_PROJECT='', LANGCHAIN_SESSION='',
                         LANGSMITH_ENDPOINT='https://api.smith.langchain.com', TELEMETRY_CAPTURE_CONTENT='false')
        env.start()
        self.addCleanup(env.stop)
        self.api = Mock(spec=Client)
        mock = patch.object(ls, 'client', return_value=self.api)
        mock.start()
        self.addCleanup(mock.stop)
        self.addCleanup(ls.HEALTH.update, last_error_type=None, export_errors=0, runs_queued=0)

    def test_nested_real_sdk_runs_usage_and_handled_failure_without_otel(self):
        with patch.object(otel, '_runtime', None), otel.span('campaign.run', {'run.id': 'campaign-123'}):
            with otel.span('task.writer', {'gen_ai.agent.name': 'writer'}):
                with otel.span('gen_ai.chat') as span:
                    ls.event('llm_call_finished', {'model': 'test-model', 'agent': 'writer',
                        'usage': {'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14}})
                    span.set_status(otel.Status(otel.StatusCode.ERROR))
        creates = [call.kwargs for call in self.api.create_run.call_args_list]
        updates = [call.kwargs for call in self.api.update_run.call_args_list]
        self.assertEqual(len(creates), 3)
        self.assertEqual(creates[1]['parent_run_id'], creates[0]['id'])
        self.assertEqual(creates[2]['parent_run_id'], creates[1]['id'])
        self.assertEqual(creates[2]['run_type'], 'llm')
        self.assertEqual(creates[0]['address'].id, 'crew-ai-agents')
        self.assertEqual(updates[0]['outputs']['usage_metadata']['total_tokens'], 14)
        self.assertEqual(updates[0]['error'], 'OperationFailed')
        self.assertIsNone(ls.CURRENT.get())

    def test_exception_and_content_redaction(self):
        with self.assertRaisesRegex(ValueError, 'private prompt'):
            with otel.span('task.writer', {'api_key': 'test-secret-langsmith'}):
                ls.event('agent_deliverable', {'agent': 'writer', 'summary': 'private prompt'})
                raise ValueError('private prompt test-secret-langsmith')
        serialized = str(self.api.mock_calls)
        self.assertNotIn('private prompt', serialized)
        self.assertNotIn('test-secret-langsmith', serialized)
        self.assertEqual(self.api.update_run.call_args.kwargs['error'], 'ValueError')
        with patch.dict(os.environ, TELEMETRY_CAPTURE_CONTENT='true'), otel.span('task.editor'):
            ls.event('agent_deliverable', {'decisions': ['Use evidence', 'test-secret-langsmith', 'lsv2_pt_example_secret']})
        serialized = str(self.api.update_run.call_args)
        self.assertIn('Use evidence', serialized)
        self.assertNotIn('test-secret-langsmith', serialized)
        self.assertNotIn('lsv2_pt_example_secret', serialized)

    def test_disabled_and_sdk_failure_do_not_block_work(self):
        with patch.dict(os.environ, LANGSMITH_TRACING='false'), otel.span('campaign.run'):
            pass
        self.api.create_run.assert_not_called()
        self.api.create_run.side_effect = RuntimeError('export unavailable')
        with otel.span('campaign.run'):
            value = 42
        self.assertEqual(value, 42)
        self.assertIsNone(ls.CURRENT.get())
        self.assertEqual(ls.HEALTH['last_error_type'], 'RuntimeError')
        self.api.create_run.side_effect = None
        self.api.update_run.side_effect = RuntimeError('export unavailable')
        with otel.span('task.writer'):
            pass
        self.assertIsNone(ls.CURRENT.get())

    def test_thread_context_propagation_and_local_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Store(Path(directory) / 'test.db')
            with otel.span('campaign.run'):
                def step():
                    with otel.span('task.writer'):
                        db.event('test', 'agent_step', agent='writer', tool='lookup', tool_input='private question')
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(copy_context().run, step).result()
            self.assertEqual(self.api.create_run.call_args.kwargs['parent_run_id'],
                             self.api.create_run.call_args_list[0].kwargs['id'])
            self.assertIn('agent_step', str(self.api.update_run.call_args_list))
            self.assertNotIn('private question', str(self.api.update_run.call_args_list))
            self.assertEqual(db.events('test')[0]['tool_input'], 'private question')

    def test_configuration_and_status_are_serializable(self):
        self.assertEqual(ls.status()['configuration'], 'ready')
        json.dumps(ls.status())
        with patch.dict(os.environ, LANGSMITH_PROJECT='conflict'):
            self.assertEqual(ls.status()['configuration'], 'invalid')
        with patch.dict(os.environ, LANGSMITH_AGENT_ENVIRONMENT=''):
            self.assertEqual(ls.status()['configuration'], 'invalid')
        with patch.dict(os.environ, LANGSMITH_API_KEY=''):
            self.assertEqual(ls.status()['configuration'], 'invalid')
        with patch.dict(os.environ, LANGSMITH_AGENT_ID='', LANGSMITH_AGENT_ENVIRONMENT='', LANGSMITH_PROJECT='test'):
            self.assertEqual(ls.configuration()[1], {'project_name': 'test'})
