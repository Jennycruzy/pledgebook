from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organisations (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'NGN',
  retention_days INTEGER NOT NULL DEFAULT 90, link_expiry_days INTEGER NOT NULL DEFAULT 14,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  org_id TEXT NOT NULL REFERENCES organisations(id), user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (org_id, user_id)
);
CREATE TABLE IF NOT EXISTS event_grants (
  event_id TEXT NOT NULL REFERENCES events(id),
  org_id TEXT NOT NULL REFERENCES organisations(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (event_id, user_id)
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  org_id TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL REFERENCES organisations(id),
  email TEXT NOT NULL DEFAULT '', role TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
  event_id TEXT, created_by INTEGER, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  accepted_at TEXT, accepted_by INTEGER, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS usage (
  org_id TEXT NOT NULL, day TEXT NOT NULL, audio_seconds INTEGER NOT NULL DEFAULT 0,
  assistant_sessions INTEGER NOT NULL DEFAULT 0, events_created INTEGER NOT NULL DEFAULT 0,
  emails_sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (org_id, day)
);
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
CREATE TABLE IF NOT EXISTS pledge_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL REFERENCES events(id),
  pledge_id INTEGER NOT NULL REFERENCES pledges(id), token TEXT NOT NULL UNIQUE,
  created_by INTEGER, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  opened_at TEXT, revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS pledge_links_pledge ON pledge_links(pledge_id);
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, pledge_id INTEGER NOT NULL,
  link_id INTEGER, channel TEXT NOT NULL, recipient TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_by INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS deliveries_event ON deliveries(event_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            self._ensure_columns(conn)

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        """Apply additive schema changes without deleting existing event data."""

        required = {
            "events": {
                "expires_at": "TEXT",
                "demo_audio_seconds": "INTEGER NOT NULL DEFAULT 0",
                "org_id": "TEXT",
                "created_by": "INTEGER",
                "sample": "INTEGER NOT NULL DEFAULT 0",
                "started_at": "TEXT",
                "paused_at": "TEXT",
                "ended_at": "TEXT",
                "archived_at": "TEXT",
                "audio_purged_at": "TEXT",
            },
            "guests": {
                "learned_from_pledge_id": "INTEGER",
                "learned_at": "TEXT",
                "updated_at": "TEXT",
                "removed_at": "TEXT",
            },
            "pledges": {
                "safe_audio_path": "TEXT",
                "safe_audio_reason": "TEXT NOT NULL DEFAULT ''",
                "recognised_from_pledge_id": "INTEGER",
                "recognised_at": "TEXT",
                "capture_id": "TEXT",
                "received_minor": "INTEGER NOT NULL DEFAULT 0",
                "follow_up_stopped": "INTEGER NOT NULL DEFAULT 0",
                # What each pass heard, kept for measuring the two passes.
                "live_amount_minor": "INTEGER",
                "live_guest_id": "INTEGER",
                "spoken_end_at": "TEXT",
                "recheck_amount_minor": "INTEGER",
                "recheck_guest_id": "INTEGER",
                "recheck_ms": "REAL",
                "rechecked_at": "TEXT",
            },
            "payments": {
                "public_token": "TEXT",
                "expires_at": "TEXT",
                "link_id": "INTEGER",
            },
            "audit_log": {
                "actor_user_id": "INTEGER",
                "actor_label": "TEXT NOT NULL DEFAULT ''",
                "guest_id": "INTEGER",
            },
            "calls": {
                "kind": "TEXT NOT NULL DEFAULT 'assistant'",
                "link_id": "INTEGER",
                "created_by": "INTEGER",
            },
        }
        for table, columns in required.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute("UPDATE events SET sample = 1 WHERE demo = 1 AND sample = 0")
        conn.execute("CREATE INDEX IF NOT EXISTS events_org ON events(org_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS event_grants_user ON event_grants(user_id, org_id)")
        # Preserve access for ushers who accepted event invitations before
        # event-scoped grants were introduced.
        conn.execute(
            "INSERT OR IGNORE INTO event_grants(event_id, org_id, user_id, role, created_at) "
            "SELECT event_id, org_id, accepted_by, 'usher', accepted_at FROM invites "
            "WHERE role = 'usher' AND event_id IS NOT NULL AND accepted_by IS NOT NULL AND accepted_at IS NOT NULL"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS audit_event ON audit_log(event_id, id)")
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

    def update(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run a write and return how many rows it changed."""

        with self.connect() as conn:
            return int(conn.execute(sql, params).rowcount)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def audit(self, event_id: str, action: str, details: dict, pledge_id: int | None = None,
              actor: dict | None = None, guest_id: int | None = None) -> None:
        if guest_id is None and isinstance(details.get("guest_id"), int):
            guest_id = details["guest_id"]
        actor = actor or {}
        self.execute(
            "INSERT INTO audit_log(event_id, pledge_id, action, details_json, created_at, actor_user_id, actor_label, guest_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, pledge_id, action, json.dumps(details, ensure_ascii=False), now(),
             actor.get("id"), actor.get("label") or actor.get("name") or "", guest_id),
        )
