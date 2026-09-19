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

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, brief):
        run = dict(id=str(uuid4()), status="queued", created_at=now(),
                   brief=brief, tasks=[], artifact=None, approval=None, error=None)
        with self.connect() as db:
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
