"""Bounded, retryable Datadog operational log export from the durable event journal."""
import logging
import os
from datetime import datetime, timezone

import httpx
from .observability import redact

SITES = {'datadoghq.com', 'us3.datadoghq.com', 'us5.datadoghq.com', 'datadoghq.eu',
         'ap1.datadoghq.com', 'ap2.datadoghq.com', 'ddog-gov.com'}

LAST_EXPORT = {'status': 'not_attempted'}


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
              'dd.trace_id', 'dd.span_id')
    metadata = {key: event[key] for key in fields if key in event}
    diagnostic = event.get('error')
    detail = diagnostic.get('message') if isinstance(diagnostic, dict) else None
    detail = detail or event.get('reason')
    context = ' '.join(f'{key}={event[key]}' for key in ('operation', 'agent', 'model', 'attempt') if event.get(key) is not None)
    message = f"{kind} run={item['run_id']} {context}".strip()
    if detail:
        message += ': ' + str(detail)
    return redact({'ddsource': 'crewai', 'service': os.getenv('DD_SERVICE', 'bun2too-marketing-api'),
                   'ddtags': 'env:' + os.getenv('DD_ENV', 'production'),
                   'timestamp': event['at'], 'status': severity, 'outcome': outcome,
                   'message': message, 'run_id': item['run_id'], 'event_id': item['id'], **metadata})


def status(db):
    return {'logs_enabled': os.getenv('DD_LOGS_ENABLED', 'false').lower() == 'true',
            'api_key_configured': bool(os.getenv('DD_API_KEY', '').strip()),
            'site_supported': os.getenv('DD_SITE', 'us5.datadoghq.com') in SITES,
            'site': os.getenv('DD_SITE', 'us5.datadoghq.com') if os.getenv('DD_SITE', 'us5.datadoghq.com') in SITES else 'unsupported',
            'service': os.getenv('DD_SERVICE', 'bun2too-marketing-api'),
            'pending_batch_count': len(db.log_batch()), 'last_export': dict(LAST_EXPORT)}


def flush(db):
    if os.getenv('DD_LOGS_ENABLED', 'false').lower() != 'true':
        return
    key = os.getenv('DD_API_KEY', '')
    site = os.getenv('DD_SITE', 'us5.datadoghq.com')
    if not key or site not in SITES:
        LAST_EXPORT.update(status='configuration_error', http_status=None)
        logging.getLogger(__name__).error('Datadog logs require DD_API_KEY and a supported DD_SITE')
        return
    batch = db.log_batch()
    if not batch:
        return
    LAST_EXPORT.clear()
    LAST_EXPORT.update(status='sending', attempted_at=datetime.now(timezone.utc).isoformat())
    entries = [log_entry(item) for item in batch]
    try:
        response = httpx.post(f'https://http-intake.logs.{site}/api/v2/logs',
                              headers={'DD-API-KEY': key}, json=entries, timeout=10)
        response.raise_for_status()
        db.logs_sent([item['id'] for item in batch])
        LAST_EXPORT.update(status='accepted', http_status=response.status_code, count=len(batch))
        logging.getLogger(__name__).info('Datadog logs accepted status=%s count=%s', response.status_code, len(batch))
    except Exception as exc:
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        LAST_EXPORT.update(status='failed', http_status=code, error_type=type(exc).__name__)
        logging.getLogger(__name__).warning('Datadog log export failed type=%s http_status=%s; batch retained', type(exc).__name__, code)
