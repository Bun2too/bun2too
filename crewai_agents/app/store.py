"""Persistent run artifacts for a single service instance using a mounted volume."""
import json
import sqlite3
from contextlib import contextmanager
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
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY, run_id TEXT, data TEXT NOT NULL, campaign_key TEXT)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(publications)")}
            if "campaign_key" not in columns:
                db.execute("ALTER TABLE publications ADD COLUMN campaign_key TEXT")
                db.execute("UPDATE publications SET campaign_key = run_id")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, brief):
        run_id = str(uuid4())
        run = dict(id=run_id, campaign_key=brief.get("campaign_key") or run_id, status="queued", created_at=now(),
                   brief=brief, tasks=[], artifact=None, approval=None, error=None)
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
        from .observability import redact
        data = redact(dict(kind=kind, at=now(), **details))
        with self.connect() as db:
            db.execute("INSERT INTO events (run_id, data) VALUES (?, ?)", (run_id, json.dumps(data)))

    def events(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM events WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def enqueue(self, run_id, role, kind, index, content):
        import hashlib
        from .observability import redact
        campaign_key = self.get(run_id).get("campaign_key", run_id)
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
        campaign_key = self.get(run_id).get("campaign_key", run_id)
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
