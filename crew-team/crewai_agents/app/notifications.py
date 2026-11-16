"""Durable, deduplicated incidents with independent Slack and SMTP delivery."""
import hashlib
import json
import os
import random
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import NAMESPACE_URL, uuid5

import httpx

from .observability import redact
from .store import now


def enabled():
    return os.getenv('ALERTS_ENABLED', 'false').lower() == 'true'


def configuration():
    return {'slack': bool(os.getenv('ALERT_SLACK_BOT_TOKEN') and os.getenv('ALERT_SLACK_CHANNEL')),
            'email': bool(os.getenv('SMTP_HOST') and os.getenv('ALERT_EMAIL_FROM') and os.getenv('ALERT_EMAIL_TO')
                          and (not os.getenv('SMTP_USER') or os.getenv('SMTP_PASSWORD')))}


def _enqueue(connection, incident, notice, instant):
    for channel in ('slack', 'email'):
        identity = hashlib.sha256(f"{incident['key']}:{incident['episode']}:{notice}:{channel}".encode()).hexdigest()[:32]
        record = dict(id=identity, channel=channel, incident_key=incident['key'], notice=notice,
                      incident=incident, status='pending', attempts=0, next_attempt=instant, created_at=instant)
        connection.execute('INSERT OR IGNORE INTO alert_deliveries VALUES (?, ?)', (identity, json.dumps(record)))


def incident(db, key, title, reason, run_id=None, severity='error'):
    if not enabled():
        return
    instant = now()
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT data FROM incidents WHERE id = ?', (key,)).fetchone()
        previous = json.loads(row[0]) if row else None
        fresh = previous is None or previous['status'] == 'resolved'
        rank = {'warning': 0, 'error': 1, 'critical': 2}
        escalated = not fresh and rank.get(severity, 1) > rank.get(previous['severity'], 1)
        if not fresh and not escalated:
            severity = previous['severity']
        data = redact(dict(key=key, title=title[:200], reason=reason[:2000], run_id=run_id, severity=severity,
                           status='open', episode=(previous.get('episode', 0) if previous else 0) + int(fresh),
                           opened_at=instant if fresh else previous['opened_at'], last_seen=instant,
                           last_notified=instant if fresh else previous['last_notified']))
        reminder_seconds = max(900, int(os.getenv('ALERT_REMINDER_SECONDS', '21600')))
        remind = not fresh and (datetime.fromisoformat(instant) - datetime.fromisoformat(data['last_notified'])).total_seconds() >= reminder_seconds
        if fresh or remind or escalated:
            notice = 'opened' if fresh else ('escalated-' + severity if escalated else 'reminder-' + instant)
            data['last_notified'] = instant
            _enqueue(connection, data, notice, instant)
        connection.execute('INSERT OR REPLACE INTO incidents VALUES (?, ?)', (key, json.dumps(data)))


def resolve(db, key, reason):
    if not enabled():
        return
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT data FROM incidents WHERE id = ?', (key,)).fetchone()
        if not row:
            return
        data = json.loads(row[0])
        if data['status'] != 'open':
            return
        data.update(status='resolved', resolved_at=now(), reason=redact(reason)[:2000])
        connection.execute('UPDATE incidents SET data = ? WHERE id = ?', (json.dumps(data), key))
        _enqueue(connection, data, 'resolved', data['resolved_at'])


def message(record):
    info = record['incident']
    text = f"[{info['status'].upper()}] {info['title']}\n{info['reason']}\nIncident: {info['key']} (episode {info['episode']})"
    base = os.getenv('PUBLIC_API_BASE_URL', '').rstrip('/')
    if info.get('run_id'):
        text += '\nRun: ' + info['run_id'] + '\nDiagnostics (authenticated): ' + base + '/runs/' + info['run_id'] + '/work'
    text += '\nEnvironment: ' + os.getenv('DEPLOYMENT_ENVIRONMENT', os.getenv('DD_ENV', 'unknown'))
    return redact(text)


def send(record):
    text = message(record)
    if record['channel'] == 'slack':
        response = httpx.post('https://slack.com/api/chat.postMessage',
            headers={'Authorization': 'Bearer ' + os.environ['ALERT_SLACK_BOT_TOKEN']},
            json={'channel': os.environ['ALERT_SLACK_CHANNEL'], 'text': text, 'mrkdwn': False,
                  'unfurl_links': False, 'unfurl_media': False,
                  'client_msg_id': str(uuid5(NAMESPACE_URL, record['id']))}, timeout=15, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not data.get('ok'):
            raise ValueError('Slack delivery rejected')
        return {'remote_id': data.get('ts')}
    mail = EmailMessage()
    mail['From'] = os.environ['ALERT_EMAIL_FROM']
    mail['To'] = os.environ['ALERT_EMAIL_TO']
    mail['Subject'] = f"[FB workflow {record['incident']['status']}] {record['incident']['title']}"
    mail['Message-ID'] = '<' + record['id'] + '@crew-team-alerts>'
    mail.set_content(text)
    port = int(os.getenv('SMTP_PORT', '587'))
    factory = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    kwargs = {'context': ssl.create_default_context()} if port == 465 else {}
    with factory(os.environ['SMTP_HOST'], port, timeout=15, **kwargs) as smtp:
        if port != 465:
            smtp.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USER'):
            smtp.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
        refused = smtp.send_message(mail)
        if refused:
            raise RuntimeError('SMTP recipient refused')
    return {'remote_id': mail['Message-ID']}


def deliver(db, limit=10):
    if not enabled():
        return
    for _ in range(limit):
        instant = now()
        configured = configuration()
        claimed = None
        with db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute('SELECT data FROM alert_deliveries ORDER BY rowid').fetchall()
            for row in rows:
                item = json.loads(row[0])
                if item['status'] in {'sent', 'exhausted'} or item['next_attempt'] > instant:
                    continue
                if item['status'] == 'sending' and item.get('lease_until', instant) > instant:
                    continue
                if not configured[item['channel']]:
                    item.update(status='blocked', last_error='Missing notification configuration')
                    connection.execute('UPDATE alert_deliveries SET data = ? WHERE id = ?', (json.dumps(item), item['id']))
                    continue
                if item['attempts'] >= 5:
                    item.update(status='exhausted')
                    connection.execute('UPDATE alert_deliveries SET data = ? WHERE id = ?', (json.dumps(item), item['id']))
                    continue
                item.update(status='sending', attempts=item['attempts'] + 1,
                            lease_until=(datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat())
                connection.execute('UPDATE alert_deliveries SET data = ? WHERE id = ?', (json.dumps(item), item['id']))
                claimed = item
                break
        if not claimed:
            return
        try:
            remote = send(claimed)
            claimed.update(status='sent', sent_at=now(), last_error=None, **remote)
        except Exception as exc:
            delay = min(900, 30 * 2 ** (claimed['attempts'] - 1)) + random.randint(0, 30)
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    delay = max(delay, min(3600, int(exc.response.headers.get('Retry-After', '0'))))
                except ValueError:
                    pass
            claimed.update(status='exhausted' if claimed['attempts'] >= 5 else 'pending', last_error=type(exc).__name__,
                           next_attempt=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat())
        with db.connect() as connection:
            connection.execute('UPDATE alert_deliveries SET data = ? WHERE id = ?', (json.dumps(claimed), claimed['id']))
        db.event('operations', 'notification_delivery', channel=claimed['channel'], status=claimed['status'],
                 incident_key=claimed['incident_key'], error_type=claimed.get('last_error'))


def status(db):
    with db.connect() as connection:
        incidents = [json.loads(row[0]) for row in connection.execute('SELECT data FROM incidents ORDER BY rowid DESC LIMIT 30')]
        counts = {}
        recent = []
        for row in connection.execute('SELECT data FROM alert_deliveries ORDER BY rowid DESC'):
            item = json.loads(row[0]); key = item['channel'] + ':' + item['status']
            counts[key] = counts.get(key, 0) + 1
            if len(recent) < 30:
                recent.append({k: item.get(k) for k in ('id', 'channel', 'incident_key', 'status', 'attempts', 'last_error', 'remote_id', 'next_attempt')})
    return {'enabled': enabled(), 'configured': configuration(), 'deliveries': counts, 'recent_deliveries': recent, 'incidents': incidents}


def retry(db, identity, reviewer):
    with db.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT data FROM alert_deliveries WHERE id = ?', (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        item = json.loads(row[0])
        if item['status'] not in {'exhausted', 'blocked'}:
            raise ValueError('Only blocked or exhausted alert deliveries can be retried')
        item.update(status='pending', attempts=0, next_attempt=now(), last_error=None)
        connection.execute('UPDATE alert_deliveries SET data = ? WHERE id = ?', (json.dumps(item), identity))
    db.event('operations', 'notification_retry_requested', publication_id=identity, reviewer=reviewer)
    return {'id': identity, 'status': 'pending'}
