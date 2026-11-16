import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from crewai_agents.app import otel, telemetry, main, ai_telemetry, evaluation
from crewai_agents.app.observability import redact
from crewai_agents.app.store import Store


class EnterpriseTelemetryTests(unittest.TestCase):
    def setUp(self):
        sdk = patch.dict(os.environ, OTEL_SDK_DISABLED='false')
        sdk.start()
        self.addCleanup(sdk.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Store(Path(self.temp.name) / 'runs.sqlite3')
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider(resource=Resource.create({'service.name': 'test'}))
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.reader = InMemoryMetricReader()
        self.meters = MeterProvider(metric_readers=[self.reader])
        runtime = {'traces': self.provider, 'tracer': self.provider.get_tracer('test'),
                   'meters': self.meters, 'meter': self.meters.get_meter('test'), 'instruments': {}}
        self.addCleanup(self.provider.shutdown)
        self.addCleanup(self.meters.shutdown)
        for item in [patch.object(otel, '_runtime', runtime), patch.object(main, 'DATA_DIR', Path(self.temp.name)),
                     patch.dict(os.environ, TELEMETRY_ENABLED='true', OTEL_EXPORTER_OTLP_ENDPOINT='http://127.0.0.1:4318',
                                OTEL_EXPORTER_OTLP_HEADERS='', DD_LLMOBS_ENABLED='0', DD_TRACE_ENABLED='false',
                                WORKER_ENABLED='false', MARKETING_API_KEY='test-key', RUN_COST_BUDGET_USD='0',
                                MODEL_PRICING_PATH='', REPLAY_EXPORT_ENABLED='false')]:
            item.start()
            self.addCleanup(item.stop)
        telemetry.LAST_EXPORT.clear()
        storage = patch.dict(os.environ, CREWAI_STORAGE_DIR=self.temp.name)
        storage.start()
        self.addCleanup(storage.stop)

    def response(self, status=200, body=None, headers=None):
        return httpx.Response(status, json={} if body is None else body,
                              headers=headers, request=httpx.Request('POST', 'https://collector.example/v1/logs'))

    def test_http_context_headers_and_route_cardinality(self):
        client = TestClient(main.app)
        parent = '00-' + '1' * 32 + '-' + '2' * 16 + '-01'
        response = client.get('/health', headers={'traceparent': parent})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['x-trace-id'], '1' * 32)
        server = next(s for s in self.exporter.get_finished_spans() if s.name == 'GET /health')
        self.assertEqual(server.parent.span_id, int('2' * 16, 16))
        self.assertEqual(server.attributes['http.route'], '/health')
        unknown = client.get('/missing-private-path')
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(self.exporter.get_finished_spans()[-1].name, 'GET unmatched')

    def test_queued_context_is_durable_and_execution_is_linked(self):
        with otel.span('request'):
            run = self.db.create({'channels': ['facebook']})
            request_trace = otel.correlation()['trace_id']
        reopened = Store(self.db.path).get(run['id'])
        self.assertIn(request_trace, reopened['trace_context']['traceparent'])
        def execute(run_id, social_only):
            self.db.event(run_id, 'run_started')
            self.db.update(run_id, status='awaiting_review')
        with patch.object(main, '_execute_run', side_effect=execute):
            main.execute_run(run['id'])
        span = next(s for s in self.exporter.get_finished_spans() if s.name == 'campaign.run')
        self.assertIsNone(span.parent)
        self.assertEqual(span.links[0].context.trace_id, int(request_trace, 16))
        self.assertEqual(self.db.events(run['id'])[0]['trace_id'], format(span.context.trace_id, '032x'))

    def test_sanitized_exception_does_not_export_payload_or_query(self):
        with self.provider.get_tracer('unsafe-library').start_as_current_span('http.client') as current:
            current.set_attribute('http.url', 'https://example.com/private?token=sensitive-value')
            current.record_exception(ValueError('secret prompt and response body'))
        safe = otel.sanitized_span(self.exporter.get_finished_spans()[-1])
        self.assertEqual(safe.attributes['http.url'], 'https://example.com/')
        self.assertEqual(dict(safe.events[0].attributes), {'exception.type': 'ValueError'})
        self.assertNotIn('secret prompt', str(safe.events))

    def test_numeric_usage_is_preserved_but_token_credentials_are_redacted(self):
        value = redact({'input_tokens': 100, 'output_tokens': 20, 'access_token': 'private',
                        'input_tokens_details': {'cached_tokens': 3}, 'input_tokens_string': 'private'})
        self.assertEqual(value['input_tokens'], 100)
        self.assertEqual(value['output_tokens'], 20)
        self.assertEqual(value['access_token'], '[REDACTED]')
        self.assertEqual(value['input_tokens_string'], '[REDACTED]')

    def test_otlp_json_has_correlation_and_no_prompt(self):
        with otel.span('work'):
            self.db.event('test-run', 'task_completed', prompt='private article', input_tokens=100)
        with patch.object(telemetry.httpx, 'post', return_value=self.response()) as post:
            self.assertTrue(telemetry.flush(self.db))
        self.assertEqual(post.call_args.args[0], 'http://127.0.0.1:4318/v1/logs')
        payload = post.call_args.kwargs['json']
        record = payload['resourceLogs'][0]['scopeLogs'][0]['logRecords'][0]
        self.assertEqual(len(record['traceId']), 32)
        self.assertEqual(len(record['spanId']), 16)
        self.assertNotIn('private article', json.dumps(payload))
        self.assertEqual(self.db.telemetry_backlog()['pending_count'], 0)

    def test_backlog_counts_more_than_one_batch(self):
        for _ in range(65):
            self.db.event('test-run', 'task_completed')
        self.assertEqual(telemetry.status(self.db)['pending_count'], 65)
        self.assertEqual(telemetry.status(self.db)['pending_batch_count'], 50)

    def test_retry_after_preserves_events_and_recovers(self):
        self.db.event('test-run', 'run_failed')
        with patch.object(telemetry.httpx, 'post', return_value=self.response(429, headers={'Retry-After': '30'})):
            self.assertFalse(telemetry.flush(self.db))
        self.assertEqual(telemetry.LAST_EXPORT['retry_after_seconds'], 30)
        self.assertEqual(Store(self.db.path).telemetry_backlog()['pending_count'], 1)
        with patch.object(telemetry.httpx, 'post', return_value=self.response()):
            self.assertTrue(telemetry.flush(self.db))
        self.assertEqual(self.db.telemetry_backlog()['pending_count'], 0)

    def test_poison_record_does_not_block_next_event(self):
        self.db.event('run', 'bad_event')
        self.db.event('run', 'good_event')
        with patch.object(telemetry.httpx, 'post', side_effect=[self.response(400), self.response(400), self.response()]):
            telemetry.flush(self.db)
        self.assertEqual(self.db.telemetry_backlog()['pending_count'], 0)
        self.assertEqual(self.db.telemetry_backlog()['quarantined_count'], 1)
        self.db.requeue_log(1)
        self.assertEqual(self.db.telemetry_backlog()['pending_count'], 1)

    def test_partial_success_is_not_blindly_retried(self):
        self.db.event('run', 'event')
        with patch.object(telemetry.httpx, 'post', return_value=self.response(body={'partialSuccess': {'rejectedLogRecords': '1'}})):
            telemetry.flush(self.db)
        self.assertEqual(self.db.telemetry_backlog()['quarantined_count'], 1)
        self.assertEqual(telemetry.LAST_EXPORT['status'], 'partial_success')

    def test_oversized_event_is_quarantined_locally(self):
        self.db.event('run', 'event', metrics={'oversized': 'x' * 600_000})
        with patch.object(telemetry.httpx, 'post') as post:
            telemetry.flush(self.db)
        post.assert_not_called()
        self.assertEqual(self.db.telemetry_backlog()['quarantined_count'], 1)

    def test_export_pump_runs_while_campaign_is_blocked(self):
        stop = threading.Event()
        accepted = threading.Event()
        self.db.event('run', 'run_started')
        def send(*args, **kwargs):
            accepted.set()
            return self.response()
        with patch.object(telemetry.httpx, 'post', side_effect=send):
            thread = threading.Thread(target=telemetry.export_loop, args=(stop, self.db))
            thread.start()
            try:
                self.assertTrue(accepted.wait(2))
            finally:
                stop.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_native_llm_actual_usage_and_finish_reason(self):
        with patch('crewai_core.token_manager.TokenManager._get_secure_storage_path', return_value=Path(self.temp.name)):
            from crewai import LLM
        from openai import OpenAI
        llm = LLM(model='gpt-4o', api_key='fake-provider-key')
        def respond(request):
            return httpx.Response(200, json={'id': 'chatcmpl-test', 'object': 'chat.completion', 'created': 1,
                'model': 'test-model', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'private response'},
                                                  'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}})
        llm._client = OpenAI(api_key='fake-provider-key', http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        events = []
        ai_telemetry.instrument_llm(llm, lambda kind, **data: events.append(dict(kind=kind, **data)))
        output = llm.call('private prompt')
        self.assertEqual(output, 'private response')
        self.assertEqual(events[-1]['usage']['input_tokens'], 100)
        self.assertEqual(events[-1]['usage']['output_tokens'], 20)
        self.assertEqual(events[-1]['finish_reason'], 'stop')
        self.assertEqual(events[-1]['cost']['status'], 'unavailable')
        self.assertNotIn('private prompt', str(self.exporter.get_finished_spans()[-1].attributes))
        self.assertNotIn('private response', json.dumps(events))

    def test_provider_failure_records_failed_span_without_raw_exception(self):
        class FakeLLM:
            model = 'test'
            provider = 'test'
            def call(self, *args, **kwargs):
                raise ValueError('private prompt in error')
            def _emit_call_completed_event(self, response, call_type, usage=None, finish_reason=None):
                pass
            def _emit_stream_chunk_event(self, chunk):
                pass
        events = []
        llm = ai_telemetry.instrument_llm(FakeLLM(), lambda kind, **data: events.append(data))
        with self.assertRaises(ValueError):
            llm.call('test')
        self.assertEqual(events[-1]['status'], 'failed')
        self.assertEqual(self.exporter.get_finished_spans()[-1].status.status_code, trace.StatusCode.ERROR)
        self.assertNotIn('private prompt', json.dumps(events))

    def test_versioned_price_accounts_for_cached_input(self):
        path = Path(self.temp.name) / 'rates.json'
        path.write_text(json.dumps({'version': 'test-v1', 'models': {'test': {'input_per_million': 2,
            'cached_input_per_million': 1, 'output_per_million': 4}}}))
        with patch.dict(os.environ, MODEL_PRICING_PATH=str(path)):
            value = ai_telemetry.price('test', {'input_tokens': 100, 'cached_tokens': 20, 'output_tokens': 10})
            self.assertAlmostEqual(value['usd'], 0.00022)
            self.assertEqual(value['pricing_version'], 'test-v1')
            self.assertEqual(ai_telemetry.price('unknown', {})['status'], 'unavailable')

    def test_evaluation_deduplication_and_real_cosine_drift(self):
        run = self.db.create({'channels': ['facebook']})
        common = dict(evaluator='embedding', evaluator_version='1', dataset_version='fixed-benchmark-1', embedding_model='test-embed')
        first = evaluation.record(self.db, run['id'], evaluation.Evaluation(evaluation_id='a', embedding=[1, 0], **common))
        self.assertEqual(first['drift_status'], 'baseline_created')
        second = evaluation.record(self.db, run['id'], evaluation.Evaluation(evaluation_id='b', embedding=[0, 1], **common))
        self.assertEqual(second['scores']['cosine_distance'], 1)
        self.assertEqual(second['drift_sample_count'], 1)
        evaluation.record(self.db, run['id'], evaluation.Evaluation(evaluation_id='b', embedding=[0, 1], **common))
        self.assertEqual(len(self.db.events(run['id'])), 2)
        self.assertNotIn('embedding', self.db.events(run['id'])[-1]['quality'])

    def test_replay_is_authenticated_disabled_by_default_and_never_executes(self):
        run = self.db.create({'brief': 'original input'})
        client = TestClient(main.app)
        url = '/runs/' + run['id'] + '/replay-bundle'
        self.assertEqual(client.get(url).status_code, 401)
        headers = {'Authorization': 'Bearer test-key'}
        self.assertEqual(client.get(url, headers=headers).status_code, 403)
        with patch.dict(os.environ, REPLAY_EXPORT_ENABLED='true'):
            response = client.get(url, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertFalse(response.json()['constraints']['publish'])

    def test_endpoints_reject_insecure_remote_and_preserve_header_encoding(self):
        with patch.dict(os.environ, OTEL_EXPORTER_OTLP_ENDPOINT='http://public.example:4318', OTEL_ALLOW_INSECURE_HTTP='false'):
            with self.assertRaises(ValueError):
                otel.endpoint('traces')
        with patch.dict(os.environ, OTEL_EXPORTER_OTLP_HEADERS='Authorization=Bearer%20test-value'):
            self.assertEqual(otel.headers()['Authorization'], 'Bearer test-value')

    def test_sdk_exports_real_otlp_protobuf_for_both_signals(self):
        import requests
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
        sent = []
        def post(session, url, **kwargs):
            sent.append((url, kwargs.get('data')))
            response = requests.Response()
            response.status_code = 200
            response._content = b''
            return response
        with patch.object(otel, '_runtime', None), patch('requests.Session.post', new=post), \
             patch.dict(os.environ, OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf', OTEL_SDK_DISABLED='false'):
            try:
                otel.initialize()
                with otel.span('integration.check', {'gen_ai.usage.input_tokens': 123}):
                    otel.measure('integration.count')
                otel._runtime['traces'].force_flush()
                otel._runtime['meters'].force_flush()
            finally:
                otel.shutdown()
        traces = [ExportTraceServiceRequest.FromString(body) for url, body in sent if url.endswith('/v1/traces')]
        metrics = [ExportMetricsServiceRequest.FromString(body) for url, body in sent if url.endswith('/v1/metrics')]
        self.assertTrue(traces)
        self.assertTrue(metrics)
        attributes = traces[0].resource_spans[0].scope_spans[0].spans[0].attributes
        self.assertEqual(next(a.value.int_value for a in attributes if a.key == 'gen_ai.usage.input_tokens'), 123)

    def test_budget_blocks_subsequent_call_when_usage_is_unknown(self):
        run = self.db.create({'brief': 'test'})
        self.db.event(run['id'], 'llm_call_finished', cost={'status': 'unavailable'})
        context = otel.RUN.set({'id': run['id'], 'db': self.db})
        try:
            with patch.dict(os.environ, RUN_COST_BUDGET_USD='1'), patch.object(ai_telemetry, 'price', return_value={'status': 'estimated'}):
                with self.assertRaisesRegex(ValueError, 'prior provider usage'):
                    ai_telemetry.check_budget()
        finally:
            otel.RUN.reset(context)

    def test_credential_guardrail_is_recorded_without_secret(self):
        with patch.dict(os.environ, SOME_API_KEY='private-test-credential'):
            with self.assertRaisesRegex(ValueError, 'credential material'):
                ai_telemetry.input_policy({'brief': 'include private-test-credential'})
        item = next(s for s in self.exporter.get_finished_spans() if s.name == 'guardrail.input')
        self.assertFalse(item.attributes['policy.passed'])
        self.assertNotIn('private-test-credential', str(item.attributes))

    def test_handled_publication_failure_is_an_error_span(self):
        @otel.observed('publication.test')
        def publish(run_id):
            return {'status': 'unknown'}
        self.assertEqual(publish('test-run')['status'], 'unknown')
        item = self.exporter.get_finished_spans()[-1]
        self.assertEqual(item.status.status_code, trace.StatusCode.ERROR)
        self.assertEqual(item.attributes['run.id'], 'test-run')

    def test_event_deduplication_identity_survives_reopen(self):
        self.db.event('run', 'event')
        first = self.db.log_batch()[0]
        reopened = Store(self.db.path).log_batch()[0]
        self.assertEqual((first['journal_id'], first['id']), (reopened['journal_id'], reopened['id']))


if __name__ == '__main__':
    unittest.main()
