"""Persistent run artifacts for a single service instance using a mounted volume."""
import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS operational_state (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS alert_deliveries (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS schedule_slots (slot TEXT PRIMARY KEY, run_id TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS social_posts (id TEXT PRIMARY KEY, run_id TEXT UNIQUE, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT, data TEXT NOT NULL)")
            event_columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
            if 'exported' not in event_columns:
                db.execute('ALTER TABLE events ADD COLUMN exported INTEGER NOT NULL DEFAULT 0')
            db.execute('CREATE INDEX IF NOT EXISTS events_exported_id ON events(exported, id)')
            db.execute('CREATE TABLE IF NOT EXISTS telemetry_dead_letters (event_id INTEGER PRIMARY KEY, reason TEXT, at TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS telemetry_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO telemetry_metadata VALUES (?, ?)', ('journal_id', str(uuid4())))
            db.execute('INSERT OR IGNORE INTO telemetry_metadata VALUES (?, ?)', ('created_at', now()))
            db.execute("CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY, run_id TEXT, data TEXT NOT NULL, campaign_key TEXT)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(publications)")}
            if "campaign_key" not in columns:
                db.execute("ALTER TABLE publications ADD COLUMN campaign_key TEXT")
                db.execute("UPDATE publications SET campaign_key = run_id")

    @contextmanager
    def connect(self):
        from . import otel
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with (otel.span('db.sqlite.transaction', {'db.system.name': 'sqlite'}) if otel.RUN.get() else nullcontext()), db:
                yield db
        finally:
            db.close()

    def create(self, brief):
        from .otel import carrier
        run_id = str(uuid4())
        run = dict(id=run_id, campaign_key=brief.get("campaign_key") or run_id, status="queued", created_at=now(),
                   brief=brief, tasks=[], artifact=None, approval=None, error=None, trace_context=carrier())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT data FROM runs"):
                previous = json.loads(row[0])
                if previous.get("campaign_key") == run["campaign_key"] and previous["status"] in {"queued", "running"}:
                    raise ValueError("This campaign already has an active run")
            db.execute("INSERT INTO runs VALUES (?, ?)", (run["id"], json.dumps(run)))
        return run

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def update(self, run_id, expected=None, task=None, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = json.loads(row[0])
            if expected is not None and run["status"] not in expected:
                raise ValueError("Run status is " + run["status"])
            if task:
                run["tasks"].append(task)
            run.update(changes, updated_at=now())
            db.execute("UPDATE runs SET data = ? WHERE id = ?", (json.dumps(run), run_id))
        return run

    def recent(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
        return [{k: run[k] for k in ("id", "status", "created_at")}
                for run in (json.loads(row[0]) for row in rows)]

    def event(self, run_id, kind, **details):
        from .observability import redact, trace_context
        from . import langsmith_trace
        data = redact(dict(kind=kind, at=now(), **{**trace_context(), **langsmith_trace.correlation(), **details}))
        with self.connect() as db:
            db.execute("INSERT INTO events (run_id, data) VALUES (?, ?)", (run_id, json.dumps(data)))
        langsmith_trace.event(kind, data)
        from .otel import measure
        measure('app.event.count', attributes={'operation': kind, 'outcome': details.get('status', details.get('outcome', 'recorded'))})

    def events(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def enqueue(self, run_id, role, kind, index, content):
        import hashlib
        from .observability import redact
        run = self.get(run_id)
        campaign_key = run.get("campaign_key", run_id)
        if run.get("scheduled"):
            campaign_key += ":" + run_id
        key = hashlib.sha256(f"{campaign_key}:{kind}:{index}".encode()).hexdigest()[:32]
        content = redact(content)
        data = dict(id=key, run_id=run_id, campaign_key=campaign_key, agent=role, kind=kind,
                    status="pending", content=content, created_at=now(), request=None, remote=None, error=None)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM publications WHERE id = ?", (key,)).fetchone()
            if row:
                previous = json.loads(row[0])
                if previous["content"] == content:
                    return key
                if previous["status"] in {"sending", "unknown"}:
                    raise ValueError("Reconcile the previous publication before revising this campaign")
                data["created_at"] = previous["created_at"]
                data["remote"] = previous["remote"]
                data["destination"] = previous.get("destination")
                data["published_body"] = previous.get("published_body")
                db.execute("UPDATE publications SET run_id = ?, data = ? WHERE id = ?",
                           (run_id, json.dumps(data), key))
            else:
                if kind == "epic":
                    import os
                    limit = min(max(int(os.getenv("ATLASSIAN_MAX_NEW_CAMPAIGNS_PER_DAY", "3")), 1), 20)
                    today = now()[:10]
                    existing = [json.loads(r[0]) for r in db.execute("SELECT data FROM publications")]
                    if sum(p["kind"] == "epic" and p["created_at"].startswith(today) for p in existing) >= limit:
                        raise ValueError("Daily new-campaign publication limit reached")
                db.execute("INSERT INTO publications VALUES (?, ?, ?, ?)",
                           (key, run_id, json.dumps(data), campaign_key))
        return key

    def publications(self, run_id):
        run = self.get(run_id)
        campaign_key = run.get("campaign_key", run_id)
        if run.get("scheduled"):
            campaign_key += ":" + run_id
        with self.connect() as db:
            rows = db.execute("SELECT data FROM publications WHERE campaign_key = ? ORDER BY rowid", (campaign_key,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def publication(self, key):
        with self.connect() as db:
            row = db.execute("SELECT data FROM publications WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def update_publication(self, key, expected, **changes):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM publications WHERE id = ?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            data = json.loads(row[0])
            if data["status"] not in expected:
                raise ValueError("Publication status is " + data["status"])
            data.update(changes, updated_at=now())
            db.execute("UPDATE publications SET data = ? WHERE id = ?", (json.dumps(data), key))
        return data


    def schedule(self, slot, brief, **window):
        from .otel import carrier
        run_id = str(uuid4())
        run = dict(id=run_id, campaign_key=brief['campaign_key'], status='queued', created_at=now(),
                   brief=brief, tasks=[], artifact=None, approval=None, error=None, scheduled=True, attempts=0,
                   trace_context=carrier(), **window)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT run_id FROM schedule_slots WHERE slot = ?', (slot,)).fetchone()
            if previous:
                return self.get(previous[0]), False
            db.execute('INSERT INTO runs VALUES (?, ?)', (run_id, json.dumps(run)))
            db.execute('INSERT INTO schedule_slots VALUES (?, ?)', (slot, run_id))
        return run, True

    def queued(self):
        with self.connect() as db:
            runs = [json.loads(row[0]) for row in db.execute('SELECT data FROM runs ORDER BY rowid')]
        return [run for run in runs if run['status'] == 'queued' and run.get('scheduled')]

    def retry_generation(self, run_id, reviewer, automatic=False):
        """Explicit, atomic recovery of generation only; never retries a social send."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM runs WHERE id = ?', (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = json.loads(row[0])
            if run['status'] != 'failed' or not run.get('scheduled'):
                raise ValueError('Only failed scheduled generation can be retried')
            if automatic:
                from .recovery import classify
                policy = classify(run.get('error_details') or {})
                legacy = not run.get('generation_settings') and policy['retryable']
                if policy['pause_generation'] or not (run.get('retryable') or legacy) or run.get('attempts', 0) >= 3:
                    raise ValueError('Automatic generation recovery is not eligible or its attempt limit was reached')
                if run.get('retry_after') and datetime.fromisoformat(run['retry_after']) > datetime.now(timezone.utc):
                    raise ValueError('Generation retry backoff has not elapsed')
            if db.execute('SELECT 1 FROM social_posts WHERE run_id = ?', (run_id,)).fetchone():
                raise ValueError('A publication attempt exists; reconcile it instead of regenerating')
            deadline = run.get('publish_before')
            if not deadline or datetime.fromisoformat(deadline) <= datetime.now(timezone.utc):
                raise ValueError('Publication window has expired; wait for the next daily campaign')
            run.update(status='queued', tasks=[], artifact=None, approval=None, error=None,
                       error_details=None, publication_blocker=None, retryable=False, retry_after=None, updated_at=now())
            db.execute('UPDATE runs SET data = ? WHERE id = ?', (json.dumps(run), run_id))
            from .observability import redact
            event = redact(dict(kind='generation_retry_requested', at=now(), reviewer=reviewer,
                                status='queued', attempt=run.get('attempts', 0) + 1,
                                campaign_key=run['campaign_key']))
            db.execute('INSERT INTO events (run_id, data) VALUES (?, ?)', (run_id, json.dumps(event)))
        return run

    def recover_generation(self):
        # Called only after obtaining the exclusive worker lock for this mounted store.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id, data FROM runs').fetchall():
                run = json.loads(row[1])
                if run['status'] == 'running' and run.get('scheduled'):
                    run.update(status='queued' if run.get('attempts', 0) < 2 else 'failed',
                               error='Generation interrupted by process restart', updated_at=now())
                    db.execute('UPDATE runs SET data = ? WHERE id = ?', (json.dumps(run), row[0]))

    def claim_social(self, run_id, page_id, day, daily_limit):
        publication_id = 'fb-' + run_id
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM social_posts WHERE run_id = ?', (run_id,)).fetchone()
            if row:
                return dict(json.loads(row[0]), acquired=False)
            row = db.execute('SELECT data FROM runs WHERE id = ?', (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            run = json.loads(row[0])
            if run['status'] != 'approved':
                raise ValueError('Run is not available for publication')
            previous = [json.loads(row[0]) for row in db.execute('SELECT data FROM social_posts')]
            if sum(p['page_id'] == page_id and p['day'] == day for p in previous) >= daily_limit:
                raise ValueError('Daily Facebook publication limit reached')
            record = dict(id=publication_id, run_id=run_id, page_id=page_id, day=day,
                          status='sending', created_at=now(), remote_id=None, metrics={})
            db.execute('INSERT INTO social_posts VALUES (?, ?, ?)', (publication_id, run_id, json.dumps(record)))
            run.update(status='publishing', updated_at=now())
            db.execute('UPDATE runs SET data = ? WHERE id = ?', (json.dumps(run), run_id))
        return dict(record, acquired=True)

    def finish_social(self, publication_id, status, expected=('sending',), **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM social_posts WHERE id = ?', (publication_id,)).fetchone()
            if not row:
                raise KeyError(publication_id)
            record = json.loads(row[0])
            if record['status'] not in expected:
                raise ValueError('Publication already completed; reconcile manually')
            record.update(status=status, updated_at=now(), **changes)
            db.execute('UPDATE social_posts SET data = ? WHERE id = ?', (json.dumps(record), publication_id))
            run = json.loads(db.execute('SELECT data FROM runs WHERE id = ?', (record['run_id'],)).fetchone()[0])
            run.update(status='published' if status == 'published' else 'publication_' + status, updated_at=now())
            db.execute('UPDATE runs SET data = ? WHERE id = ?', (json.dumps(run), run['id']))
        return record

    def social(self, publication_id):
        with self.connect() as db:
            row = db.execute('SELECT data FROM social_posts WHERE id = ?', (publication_id,)).fetchone()
        if not row:
            raise KeyError(publication_id)
        return json.loads(row[0])

    def social_recent(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM social_posts ORDER BY rowid DESC LIMIT 20')]

    def social_metrics(self, publication_id, metrics, unavailable=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = json.loads(db.execute('SELECT data FROM social_posts WHERE id = ?', (publication_id,)).fetchone()[0])
            record.update(metrics=metrics, metrics_at=now(), missing_metrics=unavailable or {})
            db.execute('UPDATE social_posts SET data = ? WHERE id = ?', (json.dumps(record), publication_id))

    def published_between(self, start, end):
        """Uncapped publication history; engagement refreshes do not change its age."""
        with self.connect() as db:
            records = [json.loads(row[0]) for row in db.execute('SELECT data FROM social_posts')]
        return [record for record in records if record['status'] == 'published'
                and start <= datetime.fromisoformat(record['created_at']) <= end]

    def feedback_context(self):
        context = []
        for record in self.social_recent():
            run = self.get(record['run_id'])
            artifact = run.get('artifact') or {}
            context.append(dict(record, previous_posts=artifact.get('posts', []),
                                previous_article_titles=[a['title'] for a in artifact.get('articles', [])],
                                previous_hypothesis=artifact.get('measurement_plan')))
        return context


    def log_batch(self):
        with self.connect() as db:
            journal_id = db.execute("SELECT value FROM telemetry_metadata WHERE key = 'journal_id'").fetchone()[0]
            return [dict(id=row[0], journal_id=journal_id, run_id=row[1], event=json.loads(row[2])) for row in
                    db.execute('SELECT id, run_id, data FROM events WHERE exported = 0 ORDER BY id LIMIT 50')]

    def telemetry_created_at(self):
        with self.connect() as db:
            return db.execute("SELECT value FROM telemetry_metadata WHERE key = 'created_at'").fetchone()[0]

    def logs_sent(self, ids):
        with self.connect() as db:
            db.executemany('UPDATE events SET exported = 1 WHERE id = ?', [(key,) for key in ids])

    def quarantine_log(self, event_id, reason):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO telemetry_dead_letters VALUES (?, ?, ?)', (event_id, reason, now()))
            db.execute('UPDATE events SET exported = -1 WHERE id = ?', (event_id,))

    def requeue_log(self, event_id):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM telemetry_dead_letters WHERE event_id = ?', (event_id,)).fetchone():
                raise KeyError(event_id)
            db.execute('DELETE FROM telemetry_dead_letters WHERE event_id = ?', (event_id,))
            db.execute('UPDATE events SET exported = 0 WHERE id = ?', (event_id,))

    def telemetry_backlog(self):
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM events WHERE exported = 0').fetchone()[0]
            oldest = db.execute('SELECT data FROM events WHERE exported = 0 ORDER BY id LIMIT 1').fetchone()
            quarantined = db.execute('SELECT COUNT(*) FROM telemetry_dead_letters').fetchone()[0]
        age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(json.loads(oldest[0])['at'])).total_seconds()) if oldest else 0
        return {'pending_count': count, 'oldest_pending_seconds': age, 'quarantined_count': quarantined}
