"""Application-owned OpenTelemetry providers; no payload or credential capture.

Providers are deliberately not installed globally: CrewAI owns its own optional
telemetry provider. All application instrumentation uses these providers explicitly.
"""
import functools
import inspect
import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Link, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

RUN = ContextVar('telemetry_run', default=None)
PROPAGATOR = TraceContextTextMapPropagator()
_runtime = None
_lock = threading.Lock()
_instance_id = str(uuid4())
HEALTH = {'enabled': False, 'trace_export_failures': 0, 'metric_export_failures': 0}


def sanitized_span(item):
    """Defend against automatic HTTP exception events containing URLs or bodies."""
    from opentelemetry.sdk.trace import ReadableSpan, Event
    from .observability import redact
    attrs = dict(item.attributes or {})
    for key in list(attrs):
        if key in {'http.url', 'url.full'}:
            parsed = urlsplit(str(attrs[key]))
            attrs[key] = parsed.scheme + '://' + (parsed.hostname or 'unknown') + '/'
        elif key.startswith(('http.request.header.', 'http.response.header.')) or key in {'url.query', 'url.path'}:
            attrs.pop(key)
    events = [Event(event.name, {key: value for key, value in (event.attributes or {}).items()
                                if key == 'exception.type'}, event.timestamp)
              for event in item.events if event.name == 'exception']
    return ReadableSpan(item.name, context=item.context, parent=item.parent, resource=item.resource,
                        attributes=redact(attrs), events=events, links=item.links, kind=item.kind,
                        status=Status(item.status.status_code), start_time=item.start_time, end_time=item.end_time,
                        instrumentation_scope=item.instrumentation_scope)


def enabled():
    return os.getenv('TELEMETRY_ENABLED', 'false').lower() == 'true'


def endpoint(signal):
    value = os.getenv('OTEL_EXPORTER_OTLP_' + signal.upper() + '_ENDPOINT')
    if not value:
        base = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', '').rstrip('/')
        value = base + '/v1/' + signal if base else ''
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Configure an OTLP HTTP endpoint without URL credentials/query/fragment')
    if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'} and os.getenv('OTEL_ALLOW_INSECURE_HTTP', 'false') != 'true':
        raise ValueError('Remote OTLP HTTP requires HTTPS or explicit private-network OTEL_ALLOW_INSECURE_HTTP=true')
    return value


def headers():
    result = {}
    for pair in os.getenv('OTEL_EXPORTER_OTLP_HEADERS', '').split(','):
        if pair.strip():
            key, separator, value = pair.partition('=')
            if not separator:
                raise ValueError('Invalid OTEL_EXPORTER_OTLP_HEADERS')
            result[key.strip()] = unquote(value.strip())
    return result


def resource_attributes():
    return {'service.name': os.getenv('OTEL_SERVICE_NAME', 'bun2too-marketing-api'),
            'service.instance.id': os.getenv('SERVICE_INSTANCE_ID', _instance_id),
            'service.version': os.getenv('SERVICE_VERSION', 'unknown'),
            'deployment.environment.name': os.getenv('DEPLOYMENT_ENVIRONMENT', os.getenv('DD_ENV', 'development')),
            'service.namespace': 'marketing',
            'organization.department': os.getenv('TELEMETRY_DEPARTMENT', 'marketing')}


def initialize():
    global _runtime
    if not enabled():
        return
    with _lock:
        if _runtime is not None:
            return
        if os.getenv('OTEL_SDK_DISABLED', 'false').lower() == 'true':
            raise ValueError('TELEMETRY_ENABLED=true conflicts with OTEL_SDK_DISABLED=true')
        if os.getenv('DD_LLMOBS_ENABLED', '0').lower() in {'1', 'true'}:
            raise ValueError('Use start.py or disable DD_LLMOBS_ENABLED when selecting enterprise OTLP instrumentation')
        if os.getenv('OTEL_EXPORTER_OTLP_PROTOCOL', 'http/protobuf') != 'http/protobuf':
            raise ValueError('This service uses OTLP over HTTP; set OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf')
        for signal in ('traces', 'metrics', 'logs'):
            endpoint(signal)
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, MetricExportResult
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        class TraceExporter(OTLPSpanExporter):
            def export(self, spans):
                result = super().export([sanitized_span(item) for item in spans])
                if result != SpanExportResult.SUCCESS:
                    HEALTH['trace_export_failures'] += 1
                else:
                    HEALTH['trace_last_success'] = time.time()
                return result

        class MetricExporter(OTLPMetricExporter):
            def export(self, data, timeout_millis=10000, **kwargs):
                result = super().export(data, timeout_millis=timeout_millis, **kwargs)
                if result != MetricExportResult.SUCCESS:
                    HEALTH['metric_export_failures'] += 1
                else:
                    HEALTH['metric_last_success'] = time.time()
                return result

        ratio = float(os.getenv('TELEMETRY_TRACE_SAMPLE_RATIO', '1'))
        if not 0 <= ratio <= 1:
            raise ValueError('TELEMETRY_TRACE_SAMPLE_RATIO must be between zero and one')
        resource = Resource.create(resource_attributes())
        provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(ratio)))
        provider.add_span_processor(BatchSpanProcessor(TraceExporter(endpoint=endpoint('traces'), headers=headers(), timeout=5)))
        reader = PeriodicExportingMetricReader(MetricExporter(endpoint=endpoint('metrics'), headers=headers(), timeout=5),
                                              export_interval_millis=15000, export_timeout_millis=6000)
        views = [View(instrument_name='http.server.request.duration', aggregation=ExplicitBucketHistogramAggregation(
                    [.005, .01, .025, .05, .1, .25, .5, 1, 2, 5, 10, 30, 60])),
                 View(instrument_name='gen_ai.client.operation.duration', aggregation=ExplicitBucketHistogramAggregation(
                    [.1, .5, 1, 2, 5, 10, 30, 60, 120, 240, 600, 900]))]
        meters = MeterProvider(resource=resource, metric_readers=[reader], views=views)
        _runtime = {'traces': provider, 'meters': meters, 'tracer': provider.get_tracer('crew-team', '1.0'),
                    'meter': meters.get_meter('crew-team', '1.0'), 'instruments': {}}
        HEALTH.update(enabled=True, started_at=time.time())
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        def request_hook(span, request):
            # Paths, queries and headers may contain credentials, IDs or user data.
            parsed = urlsplit(str(request.url))
            span.set_attribute('http.url', parsed.scheme + '://' + (parsed.hostname or 'unknown') + '/')
            span.set_attribute('url.full', parsed.scheme + '://' + (parsed.hostname or 'unknown') + '/')
        async def async_request_hook(span, request):
            request_hook(span, request)
        HTTPXClientInstrumentor().instrument(tracer_provider=provider, meter_provider=meters,
                                            request_hook=request_hook, async_request_hook=async_request_hook)


def shutdown():
    global _runtime
    runtime, _runtime = _runtime, None
    if runtime:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().uninstrument()
        runtime['traces'].force_flush(timeout_millis=5000)
        runtime['meters'].shutdown(timeout_millis=6000)
        runtime['traces'].shutdown()
    HEALTH['enabled'] = False


def runtime_metrics(db, data_dir, worker_ready):
    if not _runtime:
        return
    import psutil
    from opentelemetry.metrics import Observation
    process = psutil.Process()
    from datetime import datetime
    created_at = datetime.fromisoformat(db.telemetry_created_at()).timestamp()
    def gauge(name, callback, unit='1'):
        def read(options):
            try:
                return [Observation(callback())]
            except (OSError, ValueError):
                return []  # Missing observations are not invented zeroes.
        _runtime['meter'].create_observable_gauge(name, callbacks=[read], unit=unit)
    gauge('process.memory.usage', lambda: process.memory_info().rss, 'By')
    gauge('process.cpu.time', lambda: sum(process.cpu_times()[:2]), 's')
    gauge('process.thread.count', process.num_threads)
    gauge('app.storage.free', lambda: psutil.disk_usage(str(data_dir)).free, 'By')
    gauge('app.storage.used_ratio', lambda: psutil.disk_usage(str(data_dir)).percent / 100)
    gauge('app.worker.ready', lambda: int(worker_ready.is_set()))
    gauge('app.runtime.heartbeat', time.time, 's')
    gauge('app.queue.depth', lambda: len(db.queued()))
    for field in ('pending_count', 'oldest_pending_seconds', 'quarantined_count'):
        gauge('telemetry.logs.' + field, lambda field=field: db.telemetry_backlog()[field])
    for signal in ('trace', 'metric'):
        gauge('telemetry.' + signal + '.export_failures', lambda signal=signal: HEALTH[signal + '_export_failures'])
    def latest_event(kinds):
        with db.connect() as connection:
            row = connection.execute('SELECT MAX(json_extract(data, \'$.at\')) FROM events WHERE json_extract(data, \'$.kind\') IN (' +
                                     ','.join('?' for _ in kinds) + ')', kinds).fetchone()
        if not row[0]:
            return max(0, time.time() - created_at)
        from datetime import datetime
        return max(0, time.time() - datetime.fromisoformat(row[0]).timestamp())
    gauge('app.workflow.heartbeat_age', lambda: latest_event(('n8n_execution_started', 'n8n_execution_completed', 'n8n_execution_failed')), 's')
    gauge('app.engagement.observation_age', lambda: latest_event(('facebook_metrics_collected', 'facebook_metrics_partial')), 's')
    def publication_age():
        records = [item for item in db.social_recent() if item.get('status') == 'published']
        from datetime import datetime
        return max(0, time.time() - max((datetime.fromisoformat(item.get('updated_at', item['created_at'])).timestamp()
                                       for item in records), default=created_at))
    gauge('app.publication.age', publication_age, 's')


def carrier():
    result = {}
    PROPAGATOR.inject(result)
    return result


def correlation():
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {'trace_id': format(context.trace_id, '032x'), 'span_id': format(context.span_id, '016x')}


def measure(name, value=1, attributes=None, unit='1', histogram=False):
    runtime = _runtime
    if not runtime:
        return
    # IDs, URLs, prompts and user names must never become metric dimensions.
    allowed = {'operation', 'outcome', 'agent', 'model', 'provider', 'token_type', 'evaluator', 'metric',
               'http.request.method', 'http.route', 'http.response.status_code', 'pricing_version'}
    labels = {key: val for key, val in (attributes or {}).items() if key in allowed and isinstance(val, (str, int, bool))}
    key = (name, histogram)
    with _lock:
        if key not in runtime['instruments']:
            factory = runtime['meter'].create_histogram if histogram else runtime['meter'].create_counter
            runtime['instruments'][key] = factory(name, unit=unit)
        instrument = runtime['instruments'][key]
    (instrument.record if histogram else instrument.add)(value, labels)


@contextmanager
def span(name, attributes=None, parent=None, linked=None, kind=SpanKind.INTERNAL):
    runtime = _runtime
    tracer = runtime['tracer'] if runtime else trace.NoOpTracer()
    links = []
    if linked:
        source = trace.get_current_span(PROPAGATOR.extract(linked)).get_span_context()
        if source.is_valid:
            links = [Link(source)]
    context = PROPAGATOR.extract(parent) if parent else (Context() if linked else None)
    attrs = {k: v for k, v in (attributes or {}).items() if isinstance(v, (str, int, float, bool))}
    run = RUN.get()
    if run:
        attrs['run.id'] = run['id']
    started = time.monotonic()
    outcome = 'completed'
    with tracer.start_as_current_span(name, context=context, links=links, kind=kind, attributes=attrs,
                                      record_exception=False, set_status_on_exception=False) as current:
        try:
            yield current
        except BaseException as exc:
            outcome = 'failed'
            current.set_attribute('error.type', type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR))
            current.add_event('exception', {'exception.type': type(exc).__name__})
            raise
        finally:
            if current.is_recording() and current.status.status_code == StatusCode.ERROR:
                outcome = 'failed'
            measure('app.operation.duration', time.monotonic() - started,
                    {'operation': name, 'outcome': outcome}, unit='s', histogram=True)
            measure('app.operation.count', attributes={'operation': name, 'outcome': outcome})


def observed(name):
    def decorate(function):
        signature = inspect.signature(function)
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            run_id = signature.bind(*args, **kwargs).arguments.get('run_id')
            attributes = {'run.id': run_id} if isinstance(run_id, str) else {}
            with span(name, attributes) as current:
                result = function(*args, **kwargs)
                if isinstance(result, dict) and isinstance(result.get('status'), str):
                    outcome = result['status']
                    current.set_attribute('operation.outcome', outcome)
                    if outcome in {'failed', 'unknown', 'publication_failed', 'publication_unknown', 'conflict'}:
                        current.set_status(Status(StatusCode.ERROR))
                return result
        return wrapper
    return decorate


def policy(name, version='1'):
    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            passed = False
            with span('guardrail.' + name, {'policy.name': name, 'policy.version': version}) as current:
                try:
                    result = function(*args, **kwargs)
                    passed = True
                    return result
                finally:
                    current.set_attribute('policy.passed', passed)
                    measure('ai.guardrail.decisions', attributes={'operation': name, 'outcome': 'passed' if passed else 'blocked'})
        return wrapper
    return decorate


class RequestTracing:
    """ASGI middleware preserves streaming and never reads request/response bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not _runtime:
            return await self.app(scope, receive, send)
        incoming = {k.decode('latin1'): v.decode('latin1') for k, v in scope.get('headers', [])
                    if k in {b'traceparent', b'tracestate'}}
        method = scope['method'] if scope['method'] in {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'} else 'OTHER'
        started, code = time.monotonic(), 500
        with span('HTTP ' + method, parent=incoming, kind=SpanKind.SERVER) as current:
            async def traced_send(message):
                nonlocal code
                if message['type'] == 'http.response.start':
                    code = message['status']
                    extra = list(message.get('headers', []))
                    extra.extend((k.encode(), v.encode()) for k, v in carrier().items())
                    identity = correlation().get('trace_id')
                    if identity:
                        extra.append((b'x-trace-id', identity.encode()))
                    message = dict(message, headers=extra)
                await send(message)
            try:
                await self.app(scope, receive, traced_send)
            finally:
                route = getattr(scope.get('route'), 'path', 'unmatched')
                labels = {'http.request.method': method, 'http.route': route, 'http.response.status_code': code}
                current.update_name(method + ' ' + route)
                current.set_attributes(labels)
                if code >= 500:
                    current.set_status(Status(StatusCode.ERROR))
                measure('http.server.request.duration', time.monotonic() - started, labels, unit='s', histogram=True)
                measure('http.server.request.count', attributes=labels)
