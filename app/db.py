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
  demo INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'setup', created_at TEXT NOT NULL,
  expires_at TEXT, demo_audio_seconds INTEGER NOT NULL DEFAULT 0
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
  safe_audio_path TEXT, safe_audio_reason TEXT NOT NULL DEFAULT '',
  recognised_from_pledge_id INTEGER, recognised_at TEXT,
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
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL REFERENCES events(id),
  pledge_id INTEGER NOT NULL REFERENCES pledges(id),
  reference TEXT NOT NULL UNIQUE,
  amount_kobo INTEGER NOT NULL,
  email TEXT NOT NULL,
  authorization_url TEXT NOT NULL,
  public_token TEXT UNIQUE,
  expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'initialized',
  paystack_status TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS payments_event ON payments(event_id);
CREATE INDEX IF NOT EXISTS payments_pledge ON payments(pledge_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        """Apply additive schema changes without deleting existing event data."""

        required = {
            "events": {
                "expires_at": "TEXT",
                "demo_audio_seconds": "INTEGER NOT NULL DEFAULT 0",
            },
            "guests": {
                "learned_from_pledge_id": "INTEGER",
                "learned_at": "TEXT",
            },
            "pledges": {
                "safe_audio_path": "TEXT",
                "safe_audio_reason": "TEXT NOT NULL DEFAULT ''",
                "recognised_from_pledge_id": "INTEGER",
                "recognised_at": "TEXT",
            },
            "payments": {
                "public_token": "TEXT",
                "expires_at": "TEXT",
            },
        }
        for table, columns in required.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS payments_public_token ON payments(public_token)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS payments_public_token_unique ON payments(public_token) WHERE public_token IS NOT NULL")

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
