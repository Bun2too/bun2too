import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from crewai_agents.app import model_routing as routing, ai_telemetry
from crewai_agents.app.batch_jobs import BatchJobs


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LLM_MODEL': 'gpt-4.1-mini', 'OPENAI_API_KEY': 'test',
            'ANTHROPIC_API_KEY': 'test', 'GEMINI_API_KEY': 'test', 'MODEL_ROUTING_ENABLED': 'true'}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.settings = dict(model='gpt-4.1-mini', max_output_tokens=6000, request_timeout_seconds=240, reasoning_effort='low')

    def test_tiers_and_provider_specific_caps(self):
        with patch.dict(os.environ, LLM_ROUTINE_MODEL='gemini/gemini-2.5-flash-lite', LLM_COMPLEX_MODEL='anthropic/claude-sonnet-4-6'):
            routine = routing.route('creative', self.settings)
            deep = routing.route('editor', self.settings)
            self.assertEqual(routine['max_output_tokens'], 2500)
            self.assertEqual(deep['max_output_tokens'], 6000)
            self.assertEqual(routing.llm_options(routine, self.settings)['max_output_tokens'], 2500)
            self.assertEqual(routing.llm_options(deep, self.settings)['max_tokens'], 6000)
            self.assertNotIn('reasoning_effort', routing.llm_options(deep, self.settings))
            self.assertNotIn('reasoning_effort', routing.llm_options(routing.route('writer', self.settings), self.settings))

    def test_missing_provider_key_fails_closed_and_overrides_are_explicit(self):
        with patch.dict(os.environ, LLM_COMPLEX_MODEL='anthropic/claude-sonnet-4-6', ANTHROPIC_API_KEY=''):
            with self.assertRaisesRegex(ValueError, 'ANTHROPIC_API_KEY'):
                routing.route('writer', self.settings)
            with patch.dict(os.environ, LLM_MODEL_WRITER='openai/gpt-4.1-mini'):
                self.assertEqual(routing.route('writer', self.settings)['provider'], 'openai')
        with patch.dict(os.environ, LLM_MAX_TOKENS_CREATIVE='999999'):
            with self.assertRaises(ValueError): routing.route('creative', self.settings)

    def test_cache_marks_only_system_and_does_not_mutate(self):
        llm = SimpleNamespace(call=lambda messages: messages)
        routing.enable_prompt_cache(llm, 'anthropic')
        messages = [{'role': 'system', 'content': 'stable'}, {'role': 'user', 'content': 'changing'}]
        result = llm.call(messages)
        self.assertTrue(result[0]['cache_breakpoint'])
        self.assertNotIn('cache_breakpoint', messages[0])
        self.assertNotIn('cache_breakpoint', result[1])

    def test_cache_write_usage_preserved(self):
        self.assertEqual(ai_telemetry.normalized_usage({'cache_creation_tokens': 100})['cache_creation_tokens'], 100)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.jobs = BatchJobs(self.temp.name + '/batch.db')
        self.env = patch.dict(os.environ, OPENAI_API_KEY='test', ANTHROPIC_API_KEY='test')
        self.env.start(); self.addCleanup(self.env.stop)

    def test_no_automatic_resubmission_after_ambiguous_transport(self):
        self.jobs.prepare('daily-tags', 'openai', 'gpt-4.1-mini', 'tagging', ['article'])
        with patch.object(self.jobs, 'request', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError): self.jobs.submit('daily-tags')
        self.assertEqual(self.jobs.get('daily-tags')['status'], 'submission_unknown')
        with self.assertRaises(ValueError): self.jobs.submit('daily-tags')

    def test_anthropic_batch_output_caps_and_collect(self):
        self.jobs.prepare('tags', 'anthropic', 'claude-sonnet-4-6', 'tagging', ['a', 'b'], 500)
        with patch.object(self.jobs, 'request', return_value=SimpleNamespace(json=lambda: {'id':'batch_1'})) as request:
            self.jobs.submit('tags')
            payload = request.call_args.kwargs['json']['requests']
            self.assertEqual([r['params']['max_tokens'] for r in payload], [500, 500])
        with patch.object(self.jobs, 'request', side_effect=[SimpleNamespace(json=lambda: {'processing_status':'ended'}),
                SimpleNamespace(text='{"custom_id":"0","result":{"type":"succeeded"}}\n{"custom_id":"1","result":{"type":"errored"}}')]):
            result = self.jobs.collect('tags')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]['result']['type'], 'errored')

    def test_reject_publication_task_and_oversized_outputs(self):
        for task, cap in [('publish', 500), ('tagging', 50000)]:
            with self.assertRaises(ValueError):
                self.jobs.prepare('test', 'openai', 'gpt-4.1-mini', task, ['a'], cap)

class ProviderSerializationTests(unittest.TestCase):
    def test_native_provider_caps_and_anthropic_cache_serialization(self):
        from crewai import LLM
        with patch.dict(os.environ, ANTHROPIC_API_KEY='test', GEMINI_API_KEY='test'):
            claude = LLM(model='anthropic/claude-sonnet-4-6', max_tokens=2345, max_retries=0)
            messages, system = claude._format_messages_for_anthropic([
                {'role': 'system', 'content': 'Stable context', 'cache_breakpoint': True},
                {'role': 'user', 'content': 'Task'}])
            params = claude._prepare_completion_params(messages, system)
            self.assertEqual(params['max_tokens'], 2345)
            self.assertEqual(params['system'][0]['cache_control'], {'type':'ephemeral'})
            options = routing.llm_options(dict(model='gemini/gemini-2.5-flash-lite',
                provider='gemini', max_output_tokens=1234), dict(request_timeout_seconds=240))
            gemini = LLM(**options)
            client = gemini._client
            self.assertEqual(client._api_client._http_options.timeout, 240000)
            self.assertEqual(client._api_client._http_options.retry_options.attempts, 1)
            self.assertEqual(gemini._prepare_generation_config().max_output_tokens, 1234)

class BudgetTests(unittest.TestCase):
    def test_call_limit_blocks_even_without_rate_card(self):
        db = SimpleNamespace(events=lambda run_id: [{'kind':'llm_call_finished'}] * 2)
        token = ai_telemetry.otel.RUN.set({'id':'test', 'db':db})
        try:
            with patch.dict(os.environ, RUN_MAX_LLM_CALLS='2', RUN_COST_BUDGET_USD='0'):
                with self.assertRaisesRegex(ValueError, 'call limit'):
                    ai_telemetry.check_budget()
        finally:
            ai_telemetry.otel.RUN.reset(token)

    def test_anthropic_cache_creation_is_priced_separately(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + '/prices.json'
            from pathlib import Path
            rates = {'input_per_million':3,'cached_input_per_million':0.3,'output_per_million':15,
                     'cache_creation_per_million':3.75}
            Path(path).write_text(json.dumps({'version':'test', 'models':{'claude':rates}}))
            with patch.dict(os.environ, MODEL_PRICING_PATH=path):
                cost = ai_telemetry.price('claude', {'input_tokens':1000,'output_tokens':100,
                                                    'cached_tokens':400,'cache_creation_tokens':100})
            self.assertAlmostEqual(cost['usd'], (500*3 + 400*0.3 + 100*3.75 + 100*15)/1e6)
