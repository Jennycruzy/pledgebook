from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, organisation TEXT NOT NULL,
  event_date TEXT NOT NULL, target_minor INTEGER NOT NULL DEFAULT 0,
  min_minor INTEGER NOT NULL DEFAULT 0, max_minor INTEGER NOT NULL DEFAULT 0,
  demo INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'setup', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guests (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES events(id),
  title TEXT NOT NULL DEFAULT '', name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '', consent_to_contact INTEGER NOT NULL DEFAULT 0,
  group_name TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS guests_event ON guests(event_id);
CREATE TABLE IF NOT EXISTS pledges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES events(id),
  guest_id INTEGER REFERENCES guests(id), heard_name TEXT NOT NULL DEFAULT '',
  matched_name TEXT NOT NULL DEFAULT '', amount_minor INTEGER, currency TEXT,
  item TEXT, live_text TEXT NOT NULL DEFAULT '', recheck_text TEXT NOT NULL DEFAULT '',
  source_start_ms INTEGER, source_end_ms INTEGER, audio_path TEXT,
  state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS pledges_event ON pledges(event_id);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, pledge_id INTEGER,
  action TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, pledge_id INTEGER,
  outcome TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def audit(self, event_id: str, action: str, details: dict, pledge_id: int | None = None) -> None:
        self.execute("INSERT INTO audit_log(event_id, pledge_id, action, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
                     (event_id, pledge_id, action, json.dumps(details, ensure_ascii=False), now()))
