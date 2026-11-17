"""Bounded, retryable Datadog operational log export from the durable event journal."""
import logging
import json
import random
import time
import fcntl
from email.utils import parsedate_to_datetime
import os
from datetime import datetime, timezone

import httpx
from .observability import redact
from . import otel

SITES = {'datadoghq.com', 'us3.datadoghq.com', 'us5.datadoghq.com', 'datadoghq.eu',
         'ap1.datadoghq.com', 'ap2.datadoghq.com', 'ddog-gov.com'}

LAST_EXPORT = {'status': 'not_attempted'}


def metadata_only(value):
    """Drop free-form diagnostics/content from the enterprise export boundary."""
    if isinstance(value, dict):
        excluded = {'message', 'provider_message', 'reason', 'reviewer', 'prompt', 'response', 'output', 'tool_input'}
        return {key: metadata_only(item) for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [metadata_only(item) for item in value]
    return value


def log_entry(item):
    event = item['event']
    outcome = event.get('outcome', event.get('status'))
    kind = event['kind']
    severity = 'error' if event.get('status') == 'failed' or outcome in {'failed', 'unknown', 'publication_failed', 'publication_unknown'} or kind.endswith('_failed') else (
        'warning' if outcome in {'blocked', 'awaiting_review', 'expired', 'partial'} or kind.endswith('_blocked') else 'info')
    # An allowlist keeps prompts, artifacts, tool inputs and response bodies out.
    fields = ('kind', 'at', 'agent', 'error_type', 'error', 'remote_id', 'metrics', 'workflow_name',
              'operation', 'model', 'campaign_key', 'attempt', 'duration_ms', 'reason', 'task_id',
              'publication_id', 'page_id', 'publish_after', 'publish_before', 'slot', 'reviewer',
              'execution_id', 'execution_url', 'node', 'run_ids', 'outcomes', 'http_status',
              'retryable', 'retry_after', 'generation_settings', 'reasoning_effort',
              'request_timeout_seconds', 'agent_timeout_seconds', 'max_output_tokens',
              'missing_metrics',
              'recent_item_count', 'feed_failures',
              'image_model', 'image_size', 'image_quality', 'artwork_url',
              'dd.trace_id', 'dd.span_id', 'trace_id', 'span_id', 'usage', 'cost', 'pricing_version',
              'quality', 'evaluator', 'measurement_status', 'input_tokens', 'output_tokens',
              'cached_tokens', 'finish_reason', 'prompt_version', 'policy_version', 'service_version',
              'retrieval_count', 'source_age_seconds', 'coverage', 'tool')
    metadata = {key: event[key] for key in fields if key in event}
    diagnostic = event.get('error')
    detail = diagnostic.get('message') if isinstance(diagnostic, dict) else None
    detail = detail or event.get('reason')
    if otel.enabled():
        metadata = metadata_only(metadata)
        detail = None
    context = ' '.join(f'{key}={event[key]}' for key in ('operation', 'agent', 'model', 'attempt') if event.get(key) is not None)
    message = f"{kind} run={item['run_id']} {context}".strip()
    if detail:
        message += ': ' + str(detail)
    return redact({'ddsource': 'crewai', 'service': os.getenv('DD_SERVICE', 'bun2too-marketing-api'),
                   'ddtags': 'env:' + os.getenv('DD_ENV', 'production'),
                   'timestamp': event['at'], 'status': severity, 'outcome': outcome,
                   'message': message, 'run_id': item['run_id'], 'event_id': item['id'],
                   'journal_id': item.get('journal_id', 'legacy'), **metadata})


def status(db):
    return {'logs_enabled': otel.enabled() or os.getenv('DD_LOGS_ENABLED', 'false').lower() == 'true',
            'transport': 'otlp/http-json' if otel.enabled() else 'datadog/https',
            'signals': dict(otel.HEALTH), **db.telemetry_backlog(),
            'api_key_configured': bool(os.getenv('DD_API_KEY', '').strip()),
            'site_supported': os.getenv('DD_SITE', 'us5.datadoghq.com') in SITES,
            'site': os.getenv('DD_SITE', 'us5.datadoghq.com') if os.getenv('DD_SITE', 'us5.datadoghq.com') in SITES else 'unsupported',
            'service': otel.resource_attributes()['service.name'] if otel.enabled() else os.getenv('DD_SERVICE', 'bun2too-marketing-api'),
            'pending_batch_count': len(db.log_batch()), 'last_export': dict(LAST_EXPORT)}


def _value(value):
    if isinstance(value, bool):
        return {'boolValue': value}
    if isinstance(value, int):
        return {'intValue': str(value)}
    if isinstance(value, float):
        return {'doubleValue': value}
    return {'stringValue': value if isinstance(value, str) else json.dumps(value, separators=(',', ':'))}


def otlp_payload(entries):
    records = []
    for entry in entries:
        record = {'timeUnixNano': str(int(datetime.fromisoformat(entry['timestamp']).timestamp() * 1_000_000_000)),
                  'severityNumber': {'info': 9, 'warning': 13, 'error': 17}[entry['status']],
                  'severityText': entry['status'].upper(), 'body': {'stringValue': entry['message']},
                  'attributes': [{'key': k, 'value': _value(v)} for k, v in entry.items()
                                 if v is not None and k not in {'trace_id', 'span_id', 'message', 'timestamp'}]}
        if entry.get('trace_id') and entry.get('span_id'):
            record.update(traceId=entry['trace_id'], spanId=entry['span_id'])
        records.append(record)
    return {'resourceLogs': [{'resource': {'attributes': [{'key': k, 'value': _value(v)}
                              for k, v in otel.resource_attributes().items()]},
                             'scopeLogs': [{'scope': {'name': 'crew-team.events', 'version': '1.0'},
                                            'logRecords': records}]}]}


def _retry_after(response):
    value = response.headers.get('Retry-After', '')
    try:
        return min(3600, max(0, float(value)))
    except ValueError:
        try:
            return min(3600, max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError):
            return 0


def flush(db):
    """One bounded batch. Return success; the independent pump controls backoff.

    Only one destination is selected: OTLP takes precedence over legacy Datadog.
    HTTP acceptance is at-least-once delivery, not proof of backend indexing.
    """
    if not otel.enabled() and os.getenv('DD_LOGS_ENABLED', 'false').lower() != 'true':
        return True
    if otel.enabled():
        url, request_headers = otel.endpoint('logs'), otel.headers()
    else:
        key = os.getenv('DD_API_KEY', '')
        site = os.getenv('DD_SITE', 'us5.datadoghq.com')
        if not key or site not in SITES:
            LAST_EXPORT.update(status='configuration_error', http_status=None)
            return False
        url, request_headers = f'https://http-intake.logs.{site}/api/v2/logs', {'DD-API-KEY': key}
    batch = db.log_batch()
    if not batch:
        return True
    LAST_EXPORT.clear()
    LAST_EXPORT.update(status='sending', attempted_at=datetime.now(timezone.utc).isoformat())
    deadline, requests = time.monotonic() + 10, 0

    def send(items):
        nonlocal requests
        if time.monotonic() >= deadline or requests >= 8:
            LAST_EXPORT.update(status='batch_budget_exhausted')
            return False
        entries = [log_entry(item) for item in items]
        payload = otlp_payload(entries) if otel.enabled() else entries
        # Split large batches before transport; keep rejected records for inspection.
        if len(json.dumps(payload).encode()) > 512_000:
            if len(items) == 1:
                db.quarantine_log(items[0]['id'], 'record_exceeds_512KB')
                LAST_EXPORT.update(status='quarantined', count=1)
                return True
            midpoint = len(items) // 2
            return send(items[:midpoint]) and send(items[midpoint:])
        from opentelemetry.instrumentation.utils import suppress_instrumentation
        with suppress_instrumentation():
            requests += 1
            response = httpx.post(url, headers=request_headers, json=payload, timeout=5)
        if response.status_code in {400, 413, 422}:
            if len(items) > 1:
                midpoint = len(items) // 2
                return send(items[:midpoint]) and send(items[midpoint:])
            db.quarantine_log(items[0]['id'], 'http_' + str(response.status_code))
            LAST_EXPORT.update(status='quarantined', http_status=response.status_code, count=1)
            return True
        if response.is_error:
            LAST_EXPORT['retry_after_seconds'] = _retry_after(response)
        response.raise_for_status()
        # OTLP partial success must not be retried: accepted records would duplicate.
        # Rejected IDs are unspecified, so quarantine the batch for operator review.
        if otel.enabled() and response.content:
            partial = response.json().get('partialSuccess', {})
            if int(partial.get('rejectedLogRecords', 0)):
                for item in items:
                    db.quarantine_log(item['id'], 'otlp_partial_success_review_required')
                LAST_EXPORT.update(status='partial_success', http_status=response.status_code, count=len(items))
                return True
        db.logs_sent([item['id'] for item in items])
        LAST_EXPORT.update(status='accepted', http_status=response.status_code, count=len(items),
                           accepted_at=datetime.now(timezone.utc).isoformat())
        return True
    try:
        return send(batch)
    except Exception as exc:
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        LAST_EXPORT.update(status='failed', http_status=code, error_type=type(exc).__name__)
        logging.getLogger(__name__).warning('Telemetry export failed type=%s http_status=%s; batch retained', type(exc).__name__, code)
        return False


def export_loop(stop, db):
    """Separate process-locked export pump: model calls cannot delay log delivery."""
    with open(db.path.with_suffix('.telemetry.lock'), 'a') as lock:
        failures = 0
        while not stop.is_set():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                stop.wait(2)
                continue
            try:
                success = flush(db)
                failures = 0 if success else min(failures + 1, 8)
                delay = 2 if success else max(random.uniform(1, min(300, 2 ** failures)), LAST_EXPORT.get('retry_after_seconds', 0))
            except Exception as exc:
                LAST_EXPORT.update(status='pump_failed', error_type=type(exc).__name__)
                delay = 10
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            stop.wait(delay)
        # Durable records remain for the next start; bounded final export attempt.
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            flush(db)
        except Exception as exc:
            logging.getLogger(__name__).warning('Final telemetry flush incomplete: %s', type(exc).__name__)
