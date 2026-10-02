import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient
from openai import BadRequestError

from crewai_agents.app import main, marketing, telemetry
from crewai_agents.app.crews import build_crew, generation_settings
from crewai_agents.app.observability import error_details
from crewai_agents.tests.test_marketing import config


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for p in [patch.object(main, 'DATA_DIR', Path(directory.name)),
                  patch.object(marketing, 'profile', return_value=config()),
                  patch.object(marketing, 'facebook_destination', return_value=('v99.0', '123', 'test-page-secret', 'Bun2too')),
                  patch.dict(os.environ, MARKETING_API_KEY='test-key', LLM_MODEL='gpt-6.1-sol',
                             CREWAI_STORAGE_DIR=directory.name, OTEL_SDK_DISABLED='true',
                             OPENAI_API_KEY='test-provider-secret', MARKETING_AUTOMATION_ENABLED='true',
                             PUBLISHING_ENABLED='true', FACEBOOK_GRAPH_VERSION='v99.0', FACEBOOK_PAGE_ID='123',
                             FACEBOOK_PAGE_ACCESS_TOKEN='test-page-secret', PUBLIC_API_BASE_URL='https://crew.example',
                             DD_LLMOBS_ENABLED='0', DD_TRACE_ENABLED='false', CREWAI_TRACING_ENABLED='false')]:
            p.start(); self.addCleanup(p.stop)
        self.db = main.store()
        self.client = TestClient(main.app)
        self.client.headers['Authorization'] = 'Bearer test-key'

    def run_record(self, status='failed'):
        instant = datetime.now(timezone.utc)
        run, _ = self.db.schedule('slot', {'campaign_key': 'bun2too-daily', 'channels': ['facebook']},
                                  publish_after=(instant - timedelta(hours=1)).isoformat(),
                                  publish_before=(instant + timedelta(hours=1)).isoformat())
        return self.db.update(run['id'], status=status, attempts=1)

    def test_actual_provider_request_uses_default_temperature(self):
        with patch('crewai_core.token_manager.TokenManager._get_secure_storage_path', return_value=main.DATA_DIR):
            crew = build_crew({'channels': ['facebook']}, lambda *args: None)
        llm = crew.agents[0].llm
        messages = [{'role': 'user', 'content': 'Test'}]
        # Exercise the pinned provider's serialization, without sending a model request.
        for params in (llm._prepare_completion_params(messages), llm._prepare_responses_params(messages)):
            self.assertNotIn('temperature', params)
            self.assertEqual(params['model'], 'gpt-6.1-sol')
        self.assertEqual(llm._prepare_completion_params(messages)['reasoning_effort'], 'low')
        self.assertEqual(llm.max_retries, 0)
        self.assertGreaterEqual(crew.agents[0].max_execution_time, 2 * llm.timeout)
        self.assertEqual(crew.agents[0].max_retry_limit, 0)

    def test_generation_budgets_are_validated_and_other_models_keep_defaults(self):
        with patch.dict(os.environ, LLM_MODEL='gpt-4.1', LLM_REASONING_EFFORT=''):
            self.assertIsNone(generation_settings()['reasoning_effort'])
        with patch.dict(os.environ, LLM_REQUEST_TIMEOUT_SECONDS='600', AGENT_MAX_EXECUTION_SECONDS='180'):
            with self.assertRaisesRegex(ValueError, 'two model requests'):
                generation_settings()

    def test_remote_delivery_failure_does_not_reserve_slot_or_call_model(self):
        response = httpx.Response(400, json={'error':{'message':'Page permission denied','code':10}},
                                  request=httpx.Request('GET','https://graph.facebook.com'))
        failure = httpx.HTTPStatusError('Permission denied', request=response.request, response=response)
        with patch.object(marketing, 'schedule_slot', return_value='today'), \
                patch.object(marketing, 'verify_delivery', side_effect=failure), patch.object(main, 'build_crew') as build:
            result = self.client.post('/automation/tick')
        self.assertEqual(result.status_code, 409)
        self.assertIn('Page permission denied', result.text)
        self.assertEqual(self.db.recent(), [])
        build.assert_not_called()

    def test_automatic_recovery_obeys_backoff_cap_and_reuses_slot(self):
        run = self.run_record()
        self.db.update(run['id'], retryable=True, generation_settings={'model':'test'},
                       retry_after=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        with self.assertRaisesRegex(ValueError, 'backoff'):
            self.db.retry_generation(run['id'], 'automatic', automatic=True)
        self.db.update(run['id'], retry_after=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())
        recovered = self.db.retry_generation(run['id'], 'automatic', automatic=True)
        self.assertEqual(recovered['status'], 'queued')
        self.assertEqual(recovered['attempts'], 1)
        self.assertFalse(self.db.schedule('slot', {'campaign_key':'bun2too-daily'})[1])
        self.db.update(run['id'], status='failed', retryable=True, attempts=3)
        with self.assertRaisesRegex(ValueError, 'attempt limit'):
            self.db.retry_generation(run['id'], 'automatic', automatic=True)

    def test_tick_recovers_legacy_timeout_once_without_changing_publication_window(self):
        run = self.run_record()
        self.db.update(run['id'], error_details={'kind':'TimeoutError'})
        with patch.object(marketing, 'schedule_slot', return_value='slot'), \
                patch.object(main.Store, 'schedule', return_value=(self.db.get(run['id']), False)):
            result = self.client.post('/automation/tick').json()
        self.assertTrue(result['retried'])
        self.assertFalse(result['created'])
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(result['publish_after'], run['publish_after'])

    def test_provider_root_cause_survives_wrapper_and_export(self):
        run = self.run_record('queued')
        def kickoff():
            try:
                raise BadRequestError('raw request Private prompt test-provider-secret',
                    response=httpx.Response(400, headers={'x-request-id': 'req-123'},
                        request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions')),
                    body={'message': "Unsupported value: temperature 0.3; only default supported test-provider-secret",
                          'param': 'temperature', 'code': 'unsupported_value', 'type': 'invalid_request_error',
                          'request': 'Private prompt'})
            except BadRequestError as exc:
                raise RuntimeError('wrapper Private prompt') from exc
        recent = [dict(url='https://news.example/item', feed_url='https://news.example/feed', title='Current topic',
                       published_at=datetime.now(timezone.utc).isoformat(),
                       retrieved_at=datetime.now(timezone.utc).isoformat(), text='Current evidence')]
        with patch.object(marketing, 'source_context', return_value=(recent, [])), \
                patch.object(main, 'build_crew', return_value=SimpleNamespace(kickoff=kickoff)):
            main.execute_run(run['id'])
        item = next(item for item in self.db.log_batch() if item['event']['kind'] == 'run_failed')
        entry = telemetry.log_entry(item)
        self.assertEqual(entry['status'], 'error')
        self.assertEqual(entry['outcome'], 'failed')
        self.assertEqual(entry['agent'], 'product_owner')
        self.assertEqual(entry['operation'], 'Crew.kickoff')
        self.assertEqual(entry['model'], 'gpt-6.1-sol')
        self.assertEqual(entry['error']['kind'], 'BadRequestError')
        self.assertIn('temperature 0.3', entry['message'])
        self.assertIn('kickoff', entry['error']['stack'])
        self.assertIn('req-123', json.dumps(entry))
        self.assertIn('unsupported_value', json.dumps(entry))
        self.assertNotIn('Private prompt', json.dumps(entry))
        self.assertNotIn('test-provider-secret', json.dumps(entry))

    def test_retry_is_atomic_keeps_slot_and_rejects_expired_or_published_work(self):
        run = self.run_record()
        self.db.update(run['id'], tasks=[{'agent': 'writer'}], error='old error', artifact={'draft': 'old'})
        def retry(_):
            try:
                return self.db.retry_generation(run['id'], 'operator')['status']
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(retry, range(8)))
        self.assertEqual(outcomes.count('queued'), 1)
        saved = self.db.get(run['id'])
        self.assertEqual(saved['tasks'], [])
        self.assertIsNone(saved['artifact'])
        self.assertEqual(saved['attempts'], 1)
        self.assertEqual(saved['publish_after'], run['publish_after'])
        self.assertFalse(self.db.schedule('slot', {'campaign_key': 'bun2too-daily'})[1])
        self.assertEqual(len(self.db.events(run['id'])), 1)
        self.db.update(run['id'], status='failed', publish_before=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
        response = self.client.post('/runs/'+run['id']+'/retry-generation', json={'reviewer': 'operator'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('expired', response.text)
        self.db.update(run['id'], status='approved', publish_before=run['publish_before'])
        self.db.claim_social(run['id'], '123', 'today', 1)
        # Even an inconsistent failed run must not bypass a previous send claim.
        self.db.update(run['id'], status='failed')
        self.assertEqual(self.client.post('/runs/'+run['id']+'/retry-generation', json={'reviewer': 'operator'}).status_code, 409)

    def test_retry_endpoint_requires_auth_and_queues_only_generation(self):
        run = self.run_record()
        path = '/runs/'+run['id']+'/retry-generation'
        self.assertEqual(TestClient(main.app).post(path, json={'reviewer':'operator'}).status_code, 401)
        with patch.object(main, 'build_crew') as generate, patch.object(marketing.httpx, 'post') as send:
            response = self.client.post(path, json={'reviewer':'operator'})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['status'], 'queued')
            self.assertEqual(self.client.post(path, json={'reviewer':'operator'}).status_code, 409)
            generate.assert_not_called(); send.assert_not_called()

    def test_failed_campaign_reaches_n8n_even_with_no_publications(self):
        run = self.run_record()
        end = datetime.now(ZoneInfo('America/Chicago')).replace(hour=22, minute=30)
        self.db.update(run['id'], publish_before=end.isoformat())
        response = self.client.post('/automation/publish')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'blocked')
        self.assertEqual(response.json()['publications'], [])
        observed = self.client.post('/automation/events', json={
            'execution_id':'516', 'workflow_name':'Marketing', 'operation':'Publish approved content',
            'status':'completed', 'result':response.json()})
        self.assertTrue(observed.json()['failed'])
        self.assertEqual(observed.json()['run_ids'], [run['id']])
        self.assertEqual(self.db.events('n8n:516')[-1]['status'], 'failed')
        event = self.db.events(run['id'])[-1]
        self.assertEqual(event['execution_id'], '516')
        self.assertEqual(event['status'], 'failed')
        self.assertEqual(event['publish_after'], run['publish_after'])

    def test_not_due_and_success_have_info_severity_and_keep_business_outcome(self):
        for status in ['not_due', 'queued', 'running', 'published', 'idle']:
            response = self.client.post('/automation/events', json={
                'execution_id':status, 'workflow_name':'Marketing', 'status':'completed',
                'operation':'Generate daily campaign', 'result':{'status':status, 'prompt':'Private prompt'}})
            self.assertFalse(response.json()['failed'])
        for item in self.db.log_batch():
            entry = telemetry.log_entry(item)
            self.assertEqual(entry['status'], 'info')
            self.assertEqual(entry['outcome'], item['run_id'].split(':')[1])
            self.assertNotIn('Private prompt', json.dumps(entry))
            self.assertEqual(entry['timestamp'], item['event']['at'])

    def test_workflow_error_retains_node_message_and_execution_link(self):
        response = self.client.post('/automation/events', json={
            'execution_id':'517', 'workflow_name':'Marketing', 'status':'failed',
            'node':'Generate daily campaign', 'execution_url':'https://n8n.example/execution/517',
            'error_message':'HTTP 401 Bearer test-provider-secret'})
        self.assertTrue(response.json()['failed'])
        entry = telemetry.log_entry(self.db.log_batch()[0])
        self.assertEqual(entry['status'], 'error')
        self.assertIn('HTTP 401', entry['message'])
        self.assertEqual(entry['node'], 'Generate daily campaign')
        self.assertIn('/517', entry['execution_url'])
        self.assertNotIn('test-provider-secret', json.dumps(entry))

    def test_http_provider_diagnostics_exclude_request_body(self):
        response = httpx.Response(403, json={'error':{'message':'Page permission denied', 'code':200, 'fbtrace_id':'meta-trace'},
            'request_body':'Private prompt'}, request=httpx.Request('POST','https://graph.facebook.com', content='Private prompt'))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = error_details(exc)
        self.assertIn('Page permission denied', detail['message'])
        self.assertIn('meta-trace', json.dumps(detail))
        self.assertNotIn('Private prompt', json.dumps(detail))

    def test_metrics_failure_reaches_workflow_and_keeps_meta_diagnostic(self):
        run = self.run_record('approved')
        publication = self.db.claim_social(run['id'], '123', 'today', 1)
        self.db.finish_social(publication['id'], 'published', remote_id='123_456')
        response = httpx.Response(403, json={'error':{'message':'Page permission denied', 'code':200,
            'fbtrace_id':'meta-trace'}}, request=httpx.Request('GET','https://graph.facebook.com'))
        with patch.object(marketing.httpx, 'get', return_value=response):
            result = self.client.post('/automation/metrics').json()
        self.assertEqual(result['status'], 'failed')
        event = self.client.post('/automation/events', json={'execution_id':'518', 'workflow_name':'Marketing',
            'status':'completed', 'operation':'Collect Facebook results', 'result':result}).json()
        self.assertTrue(event['failed'])
        self.assertEqual(event['run_ids'], [run['id']])
        item = next(item for item in self.db.log_batch() if item['event']['kind'] == 'facebook_metrics_failed')
        entry = telemetry.log_entry(item)
        self.assertEqual(entry['status'], 'error')
        self.assertIn('Page permission denied', entry['message'])
        self.assertIn('meta-trace', json.dumps(entry))

    def test_missing_metric_permission_preserves_available_counts_without_zeroes(self):
        run = self.run_record('approved')
        publication = self.db.claim_social(run['id'], '123', 'today', 1)
        self.db.finish_social(publication['id'], 'published', remote_id='123_456')
        def response(*args, **kwargs):
            if kwargs['params']['fields'] == 'id,shares':
                return httpx.Response(200, json={'shares':{'count':2}}, request=httpx.Request('GET',args[0]))
            return httpx.Response(400, json={'error':{'message':'pages_read_user_content required', 'code':10}},
                                  request=httpx.Request('GET',args[0]))
        with patch.object(marketing.httpx, 'get', side_effect=response):
            result = self.client.post('/automation/metrics').json()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['results'][0]['metrics'], {'shares':2})
        saved = self.db.social(publication['id'])
        self.assertEqual(saved['metrics'], {'shares':2})
        self.assertEqual(set(saved['missing_metrics']), {'comments','reactions'})
        item = next(item for item in self.db.log_batch() if item['event']['kind'] == 'facebook_metrics_partial')
        entry = telemetry.log_entry(item)
        self.assertEqual(entry['status'], 'warning')
        self.assertIn('pages_read_user_content', json.dumps(entry))


if __name__ == '__main__':
    unittest.main()
