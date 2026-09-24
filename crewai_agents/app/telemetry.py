"""Bounded, retryable Datadog operational log export from the durable event journal."""
import logging
import os

import httpx

SITES = {'datadoghq.com', 'us3.datadoghq.com', 'us5.datadoghq.com', 'datadoghq.eu',
         'ap1.datadoghq.com', 'ap2.datadoghq.com', 'ddog-gov.com'}


def flush(db):
    if os.getenv('DD_LOGS_ENABLED', 'false').lower() != 'true':
        return
    key = os.getenv('DD_API_KEY', '')
    site = os.getenv('DD_SITE', 'us5.datadoghq.com')
    if not key or site not in SITES:
        logging.getLogger(__name__).error('Datadog logs require DD_API_KEY and a supported DD_SITE')
        return
    batch = db.log_batch()
    if not batch:
        return
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
    except Exception as exc:
        logging.getLogger(__name__).warning('Datadog log export failed type=%s', type(exc).__name__)
