"""Bounded, retryable Datadog operational log export from the durable event journal."""
import logging
import os
from datetime import datetime, timezone

import httpx

SITES = {'datadoghq.com', 'us3.datadoghq.com', 'us5.datadoghq.com', 'datadoghq.eu',
         'ap1.datadoghq.com', 'ap2.datadoghq.com', 'ddog-gov.com'}

LAST_EXPORT = {'status': 'not_attempted'}


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
    entries = []
    for item in batch:
        event = item['event']
        # Export operational metadata, not prompts, source content or credentials.
        metadata = {key: event[key] for key in ('kind', 'at', 'agent', 'status', 'error_type', 'remote_id', 'metrics', 'workflow_name') if key in event}
        entries.append({'ddsource': 'crewai', 'service': os.getenv('DD_SERVICE', 'bun2too-marketing-api'),
                        'ddtags': 'env:' + os.getenv('DD_ENV', 'production'), 'message': event['kind'],
                        'run_id': item['run_id'], 'event_id': item['id'], **metadata})
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
