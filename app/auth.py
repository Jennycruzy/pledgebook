"""Accounts, sessions, organisation roles and request limits."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import time
import uuid

from fastapi import HTTPException, Request, WebSocket

from .db import Database, now


SESSION_COOKIE = "pb_session"
SESSION_DAYS = 30
ROLES = ("owner", "admin", "usher")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# What each role may do. Ushers review and resolve lines during the event but
# never see guest contact details, exports, payments or organisation settings.
PERMISSIONS = {
    "owner": {"view", "review", "run", "guests", "contacts", "follow_up", "export", "settings", "staff"},
    "admin": {"view", "review", "run", "guests", "contacts", "follow_up", "export"},
    "usher": {"view", "review"},
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest.hex(), digest_hex)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_PATTERN.match(email) or len(email) > 200:
        raise HTTPException(400, "Enter a valid email address.")
    return email


def validate_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(400, "Use a password of at least 10 characters.")


class RateLimiter:
    """A small in-process sliding-window limiter keyed by client and action."""

    def __init__(self):
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def check(self, key: str, bucket: str, limit: int, window_seconds: int) -> None:
        stamp = time.monotonic()
        hits = self.hits[(key, bucket)]
        while hits and stamp - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
        hits.append(stamp)


limiter = RateLimiter()


def client_ip(request: Request | WebSocket) -> str:
    forwarded = request.headers.get("x-real-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0]
    return forwarded.strip() or (request.client.host if request.client else "unknown")


class Auth:
    def __init__(self, database: Database):
        self.db = database

    def create_user(self, email: str, name: str, password: str) -> dict:
        email = validate_email(email)
        validate_password(password)
        if not name.strip():
            raise HTTPException(400, "Enter your name.")
        if self.db.one("SELECT id FROM users WHERE email = ?", (email,)):
            raise HTTPException(409, "An account already uses this email. Sign in instead.")
        user_id = self.db.execute(
            "INSERT INTO users(email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (email, name.strip()[:120], hash_password(password), now()),
        )
        return self.db.one("SELECT id, email, name FROM users WHERE id = ?", (user_id,))

    def create_organisation(self, name: str, owner_id: int) -> str:
        org_id = uuid.uuid4().hex
        self.db.execute("INSERT INTO organisations(id, name, created_at) VALUES (?, ?, ?)", (org_id, name.strip()[:160], now()))
        self.db.execute("INSERT INTO memberships(org_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)", (org_id, owner_id, now()))
        return org_id

    def authenticate(self, email: str, password: str) -> dict:
        user = self.db.one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
        if not user or not verify_password(password, user["password_hash"]):
            raise HTTPException(401, "The email or password is not correct.")
        return user

    def start_session(self, user_id: int, org_id: str | None) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        self.db.execute(
            "INSERT INTO sessions(token_hash, user_id, org_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash(token), user_id, org_id, now(), expires.isoformat()),
        )
        return token, expires

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def set_session_org(self, token: str, org_id: str) -> None:
        self.db.execute("UPDATE sessions SET org_id = ? WHERE token_hash = ?", (org_id, token_hash(token)))

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.one(
            "SELECT s.org_id AS session_org, s.expires_at, u.id, u.email, u.name FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (token_hash(token),),
        )
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            self.end_session(token)
            return None
        memberships = self.db.all(
            "SELECT m.org_id, m.role, o.name FROM memberships m JOIN organisations o ON o.id = m.org_id "
            "WHERE m.user_id = ? ORDER BY m.created_at",
            (row["id"],),
        )
        active = next((m for m in memberships if m["org_id"] == row["session_org"]), memberships[0] if memberships else None)
        return {
            "id": row["id"], "email": row["email"], "name": row["name"], "label": row["name"],
            "memberships": memberships,
            "org_id": active["org_id"] if active else None,
            "role": active["role"] if active else None,
            "org_name": active["name"] if active else None,
            "token": token,
        }

    def user_from_request(self, request: Request | WebSocket) -> dict | None:
        return self.session_user(request.cookies.get(SESSION_COOKIE))

    def require_user(self, request: Request) -> dict:
        user = self.user_from_request(request)
        if not user:
            raise HTTPException(401, "Sign in to continue.")
        return user

    def require_org(self, request: Request, permission: str = "view") -> dict:
        user = self.require_user(request)
        if not user["org_id"]:
            raise HTTPException(403, "You are not a member of an organisation.")
        if permission not in PERMISSIONS.get(user["role"], set()):
            raise HTTPException(403, "Your role does not allow this action.")
        return user

    def require_event(self, request: Request | WebSocket, event_id: str, permission: str = "view") -> tuple[dict, dict]:
        """Return the event and the signed-in member allowed to use it.

        An event outside the member's organisations answers 404 so its
        existence is not revealed.
        """

        user = self.user_from_request(request)
        if not user:
            raise HTTPException(401, "Sign in to continue.")
        event = self.db.one("SELECT * FROM events WHERE id = ?", (event_id,))
        membership = None
        if event and event.get("org_id"):
            membership = next((m for m in user["memberships"] if m["org_id"] == event["org_id"]), None)
            if membership and membership["role"] == "usher":
                grant = self.db.one(
                    "SELECT role FROM event_grants WHERE event_id = ? AND org_id = ? AND user_id = ?",
                    (event_id, event["org_id"], user["id"]),
                )
                membership = {**membership, "role": grant["role"]} if grant else None
        if not event or not membership:
            raise HTTPException(404, "Event was not found")
        if permission not in PERMISSIONS.get(membership["role"], set()):
            raise HTTPException(403, "Your role does not allow this action.")
        member = {**user, "org_id": membership["org_id"], "role": membership["role"], "org_name": membership["name"]}
        return event, member

    def create_invite(self, org_id: str, role: str, email: str, created_by: int, event_id: str | None, days: int = 7) -> str:
        if role not in ("admin", "usher"):
            raise HTTPException(400, "Invite an admin or an usher.")
        if role == "usher" and not event_id:
            raise HTTPException(400, "Choose the event this usher may access.")
        token = secrets.token_urlsafe(24)
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        self.db.execute(
            "INSERT INTO invites(org_id, email, role, token_hash, event_id, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (org_id, email.strip().lower(), role, token_hash(token), event_id, created_by, now(), expires),
        )
        return token

    def open_invite(self, token: str) -> dict:
        invite = self.db.one(
            "SELECT i.*, o.name AS org_name FROM invites i JOIN organisations o ON o.id = i.org_id WHERE token_hash = ?",
            (token_hash(token),),
        )
        if not invite or invite["revoked_at"]:
            raise HTTPException(404, "This invitation is not valid. Ask the organiser for a new one.")
        if invite["accepted_at"]:
            raise HTTPException(410, "This invitation has already been used.")
        if datetime.fromisoformat(invite["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(410, "This invitation has expired. Ask the organiser for a new one.")
        return invite

    def accept_invite(self, token: str, user: dict) -> dict:
        invite = self.open_invite(token)
        if invite["email"] and invite["email"] != user["email"]:
            raise HTTPException(403, f"This invitation was sent to {invite['email']}. Sign in with that email.")
        existing = self.db.one("SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (invite["org_id"], user["id"]))
        if not existing:
            self.db.execute(
                "INSERT INTO memberships(org_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                (invite["org_id"], user["id"], invite["role"], now()),
            )
        elif existing["role"] != invite["role"] and invite["role"] != "usher":
            raise HTTPException(409, "This account already has a different role in the organisation.")
        if invite["role"] == "usher" and invite["event_id"]:
            self.db.execute(
                "INSERT OR REPLACE INTO event_grants(event_id, org_id, user_id, role, created_at) VALUES (?, ?, ?, 'usher', ?)",
                (invite["event_id"], invite["org_id"], user["id"], now()),
            )
        changed = self.db.update(
            "UPDATE invites SET accepted_at = ?, accepted_by = ? WHERE id = ? AND accepted_at IS NULL",
            (now(), user["id"], invite["id"]),
        )
        if not changed:
            raise HTTPException(410, "This invitation has already been used.")
        return invite
