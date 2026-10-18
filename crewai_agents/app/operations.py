"""Independent watchdog: bounded generation recovery, incidents and notification outbox."""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from . import notifications, recovery
from .observability import error_details
from .store import now

logger = logging.getLogger(__name__)


def state(db, key):
    with db.connect() as connection:
        row = connection.execute('SELECT data FROM operational_state WHERE id = ?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def save(db, key, data):
    with db.connect() as connection:
        connection.execute('INSERT OR REPLACE INTO operational_state VALUES (?, ?)', (key, json.dumps(data)))


def circuit(db):
    value = state(db, 'generation_circuit')
    return value if value and value.get('status') == 'open' else None


def pause(db, run_id, policy):
    if not policy['pause_generation']:
        return
    if not circuit(db):
        save(db, 'generation_circuit', dict(status='open', run_id=run_id, category=policy['category'],
                                           reason=policy['reason'], opened_at=now()))
        db.event(run_id, 'generation_circuit_opened', status='blocked', category=policy['category'], reason=policy['reason'])


def resume(db, reviewer, run_id=None):
    # Explicit operator action after billing/auth repair. Never touches social sends.
    if run_id:
        db.retry_generation(run_id, reviewer, automatic=False)
    save(db, 'generation_circuit', dict(status='closed', resumed_at=now(), reviewer=reviewer, run_id=run_id))
    db.event(run_id or 'operations', 'generation_circuit_resumed', reviewer=reviewer, status='queued' if run_id else 'ready')
    return {'status': 'queued' if run_id else 'ready', 'run_id': run_id}


def bootstrap(db):
    """Adopt a known billing/auth outage from existing durable runs on upgrade."""
    if state(db, 'generation_circuit') is not None:
        return
    for item in db.recent():
        run = db.get(item['id'])
        if not run.get('scheduled'):
            continue
        if run.get('status') in {'approved', 'published'}:
            break
        if run.get('error_details'):
            pause(db, run['id'], recovery.classify(run['error_details']))
            break


def inspect_runs(db):
    instant = datetime.now(timezone.utc)
    results = []
    blocked = circuit(db)
    for item in db.recent():
        run = db.get(item['id'])
        if not run.get('scheduled'):
            continue
        key = 'campaign:' + run['id']
        if run['status'] == 'published':
            notifications.resolve(db, key, 'Campaign recovered; observed state: ' + run['status'])
            continue
        # Avoid a storm of historical alerts on first deployment.
        if (instant - datetime.fromisoformat(run['created_at'])).total_seconds() > 86400:
            continue
        deadline = run.get('publish_before')
        expired = deadline and datetime.fromisoformat(deadline) <= instant
        if expired and run['status'] in {'queued', 'approved'}:
            try:
                run = db.update(run['id'], expected={run['status']}, status='expired',
                                publication_blocker='Publishing window expired; stale content was not sent.')
            except ValueError:
                continue
        if run['status'] == 'approved':
            notifications.resolve(db, key, 'Campaign generation recovered; content is approved and waiting for publication.')
            continue
        if run['status'] == 'failed':
            policy = recovery.classify(run.get('error_details') or {}, run.get('attempts', 1))
            # Never trust legacy retryable=True for billing/auth errors.
            if policy['pause_generation']:
                reason = policy['reason']
            else:
                reason = run.get('error') or policy['reason']
            notifications.incident(db, key, 'Daily campaign generation failed', reason, run['id'],
                                   severity='critical' if policy['pause_generation'] or run.get('attempts', 0) >= 3 else 'error')
            if not blocked and not expired and policy['retryable']:
                try:
                    db.retry_generation(run['id'], 'operational-watchdog', automatic=True)
                    results.append({'run_id': run['id'], 'action': 'generation_retry_queued'})
                except ValueError:
                    pass
        elif run['status'] in {'publication_failed', 'publication_unknown', 'expired', 'awaiting_review'}:
            reason = run.get('publication_blocker') or run.get('error') or 'Campaign requires review; inspect approved content and publishing evidence.'
            if run['status'] == 'publication_unknown':
                reason = 'Facebook send outcome is unknown. Reconcile the remote post before any further send; automatic replay is disabled.'
            notifications.incident(db, key, 'Daily campaign requires attention: ' + run['status'], reason, run['id'])
        elif run['status'] in {'running', 'queued'}:
            age = (instant - datetime.fromisoformat(run.get('updated_at') or run['created_at'])).total_seconds()
            threshold = max(300, int(os.getenv('STALLED_RUN_SECONDS', '7200')))
            if age > threshold:
                notifications.incident(db, key, 'Campaign execution may be stalled',
                    'No campaign progress within the configured threshold. Inspect worker/task traces. A live agent is not automatically restarted.', run['id'])
    return results


def heartbeat_check(db):
    if os.getenv('WORKFLOW_HEARTBEAT_ENABLED', 'false').lower() != 'true':
        return
    instant = datetime.now(timezone.utc)
    started = state(db, 'watchdog_started')
    threshold = max(300, int(os.getenv('WORKFLOW_HEARTBEAT_SECONDS', '1200')))
    if not started or (instant - datetime.fromisoformat(started['at'])).total_seconds() < threshold:
        return
    with db.connect() as connection:
        rows = connection.execute("SELECT data FROM events WHERE run_id LIKE 'n8n:%' ORDER BY id DESC LIMIT 2000").fetchall()
    events = [json.loads(row[0]) for row in rows]
    for operation in ('Generate daily campaign', 'Publish approved content'):
        latest = next((e for e in events if e.get('operation') == operation and e['kind'].startswith('n8n_execution_')), None)
        key = 'heartbeat:' + operation
        if not latest or (instant - datetime.fromisoformat(latest['at'])).total_seconds() > threshold:
            notifications.incident(db, key, 'Workflow heartbeat missing: ' + operation,
                'No recent workflow outcome was received. Check n8n uptime, schedule activation and the shared API credential.')
        else:
            notifications.resolve(db, key, 'Workflow outcomes are arriving again.')


def tick(db):
    bootstrap(db)
    results = inspect_runs(db)
    heartbeat_check(db)
    if notifications.enabled():
        for channel, configured in notifications.configuration().items():
            key = 'notification_configuration:' + channel
            if configured:
                notifications.resolve(db, key, channel + ' notification configuration is present.')
            else:
                notifications.incident(db, key, channel + ' notifications are not configured',
                    'Configure the missing sender credentials. Alerts for this channel are retained locally until configuration is repaired.')
        notifications.deliver(db)
    save(db, 'watchdog_heartbeat', {'at': now(), 'status': 'ok'})
    return results


def loop(stop, db):
    save(db, 'watchdog_started', {'at': now()})
    while not stop.is_set():
        try:
            tick(db)
        except Exception as exc:
            logger.error('Operational watchdog failure type=%s', type(exc).__name__)
            try:
                db.event('operations', 'watchdog_failed', status='failed', error=error_details(exc))
            except Exception:
                pass
        stop.wait(30)


def status(db):
    return {'enabled': os.getenv('OPERATIONS_ENABLED', 'false').lower() == 'true',
            'generation_circuit': circuit(db), 'watchdog': state(db, 'watchdog_heartbeat'),
            'notifications': notifications.status(db)}
