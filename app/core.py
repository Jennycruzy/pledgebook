"""Shared services and the event view every screen is built from."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil

from fastapi import HTTPException

from .auth import PERMISSIONS, Auth
from .config import Settings
from .db import Database, now


settings = Settings.load()
database = Database(settings.data_dir / "pledgebook.sqlite3")
auth = Auth(database)

SAMPLE_RETENTION_HOURS = 24
ACCEPTED_STATES = ("confirmed", "corrected", "redeemed")
ACTIVE_LINK_STATES = ACCEPTED_STATES


class Hub:
    """Fan-out of live changes to every open screen for an event.

    Messages carry no event data. Each subscriber rebuilds the view for its
    own role, so an usher's screen never receives guest contact details.
    """

    def __init__(self):
        self.listeners: dict[str, set[asyncio.Queue]] = {}

    async def subscribe(self, event_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self.listeners.setdefault(event_id, set()).add(queue)
        return queue

    def unsubscribe(self, event_id: str, queue: asyncio.Queue) -> None:
        self.listeners.get(event_id, set()).discard(queue)

    async def publish(self, event_id: str, event: dict) -> None:
        for queue in list(self.listeners.get(event_id, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except asyncio.QueueEmpty:
                    pass


hub = Hub()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# Daily usage per organisation keeps one account from spending the service
# allowance of the whole deployment.
USAGE_FIELDS = {"audio_seconds", "assistant_sessions", "events_created", "emails_sent"}


def usage_today(org_id: str) -> dict:
    row = database.one("SELECT * FROM usage WHERE org_id = ? AND day = ?", (org_id, today()))
    return row or {"audio_seconds": 0, "assistant_sessions": 0, "events_created": 0, "emails_sent": 0}


def usage_limits() -> dict:
    return {
        "audio_seconds": settings.daily_audio_minutes * 60,
        "assistant_sessions": settings.daily_assistant_sessions,
        "events_created": settings.daily_events,
        "emails_sent": settings.daily_emails,
    }


def add_usage(org_id: str, field: str, amount: int) -> None:
    if field not in USAGE_FIELDS or amount <= 0:
        return
    database.execute("INSERT OR IGNORE INTO usage(org_id, day) VALUES (?, ?)", (org_id, today()))
    database.execute(f"UPDATE usage SET {field} = {field} + ? WHERE org_id = ? AND day = ?", (amount, org_id, today()))


def remaining_usage(org_id: str, field: str) -> int:
    return usage_limits()[field] - int(usage_today(org_id).get(field) or 0)


def require_usage(org_id: str, field: str, needed: int = 1) -> None:
    if remaining_usage(org_id, field) < needed:
        labels = {
            "audio_seconds": "listening time",
            "assistant_sessions": "assistant conversations",
            "events_created": "new events",
            "emails_sent": "emails",
        }
        raise HTTPException(429, f"Your organisation has used today's allowance of {labels[field]}. It resets at midnight UTC.")


def organisation(org_id: str) -> dict:
    return database.one("SELECT * FROM organisations WHERE id = ?", (org_id,)) or {}


def guests_for(event_id: str, include_removed: bool = False) -> list[dict]:
    removed = "" if include_removed else " AND removed_at IS NULL"
    return database.all(f"SELECT * FROM guests WHERE event_id = ?{removed} ORDER BY id", (event_id,))


def guest_label(guest: dict) -> str:
    return " ".join(part for part in (guest.get("title"), guest.get("name")) if part).strip()


def keyterm_preview(event_id: str) -> dict:
    terms = [term for term in (guest_label(guest) for guest in guests_for(event_id)) if term]
    included, overflow, characters = [], [], 0
    for term in terms:
        if len(included) >= 100 or characters + len(term) > 8000:
            overflow.append(term)
            continue
        included.append(term)
        characters += len(term)
    return {"terms": included, "overflow": overflow, "included_count": len(included), "overflow_count": len(overflow),
            "characters": characters, "term_limit": 100, "character_limit": 8000}


def event_keyterms(event_id: str) -> list[str]:
    return keyterm_preview(event_id)["terms"]


def serialise_pledge(row: dict) -> dict:
    result = dict(row)
    result["amount"] = result.pop("amount_minor")
    result["received"] = int(result.pop("received_minor") or 0)
    for private in ("audio_path", "safe_audio_path"):
        result[f"has_{private.replace('_path', '')}"] = bool(result.pop(private, None))
    return result


def payment_page_url(token: str) -> str:
    relative = f"/pay/{token}"
    return f"{settings.public_url}{relative}" if settings.public_url else relative


def currency_totals(pledges: list[dict]) -> dict:
    totals: dict[str, dict] = {}
    for pledge in pledges:
        if pledge["state"] == "rejected" or pledge.get("item") or pledge.get("amount") is None:
            continue
        bucket = totals.setdefault(pledge.get("currency") or "NGN", {"pledged": 0, "confirmed": 0, "received": 0})
        bucket["pledged"] += pledge["amount"]
        if pledge["state"] in ACCEPTED_STATES:
            bucket["confirmed"] += pledge["amount"]
        bucket["received"] += pledge.get("received") or 0
    return totals


def follow_up_view(event_id: str) -> dict:
    links = database.all("SELECT * FROM pledge_links WHERE event_id = ? ORDER BY id DESC", (event_id,))
    calls = []
    for row in database.all("SELECT * FROM calls WHERE event_id = ? ORDER BY id DESC", (event_id,)):
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            details = {}
        calls.append({"id": row["id"], "pledge_id": row["pledge_id"], "kind": row.get("kind") or "assistant",
                      "outcome": row["outcome"], "promised_date": details.get("promised_date"),
                      "notes": details.get("notes") or details.get("dispute") or "", "created_at": row["created_at"]})
    payments = [{
        "id": row["id"], "pledge_id": row["pledge_id"], "reference": row["reference"],
        "amount": int(row["amount_kobo"]) // 100, "status": row["status"],
        "paid_at": (json.loads(row.get("payload_json") or "{}") or {}).get("paid_at"),
        "created_at": row["created_at"],
    } for row in database.all("SELECT * FROM payments WHERE event_id = ? ORDER BY id DESC", (event_id,))]
    deliveries = database.all(
        "SELECT d.id, d.pledge_id, d.channel, d.recipient, d.status, d.detail, d.created_at, u.name AS sent_by "
        "FROM deliveries d LEFT JOIN users u ON u.id = d.created_by WHERE d.event_id = ? ORDER BY d.id DESC",
        (event_id,),
    )
    current = datetime.now(timezone.utc)
    return {
        "links": [{"id": link["id"], "pledge_id": link["pledge_id"], "url": payment_page_url(link["token"]),
                   "expires_at": link["expires_at"], "opened_at": link["opened_at"],
                   "active": not link["revoked_at"] and (parse_time(link["expires_at"]) or current) > current}
                  for link in links],
        "calls": calls, "payments": payments, "deliveries": deliveries,
    }


def event_state(event_id: str, role: str = "owner") -> dict:
    event = database.one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(404, "Event was not found")
    permissions = PERMISSIONS.get(role, set())
    guests = guests_for(event_id)
    if "contacts" not in permissions:
        guests = [{key: value for key, value in guest.items() if key not in ("phone", "email")} for guest in guests]
    pledges = [serialise_pledge(row) for row in database.all(
        "SELECT * FROM pledges WHERE event_id = ? ORDER BY id DESC", (event_id,))]
    by_currency = currency_totals(pledges)
    main_currency = organisation(event["org_id"]).get("currency", "NGN") if event.get("org_id") else "NGN"
    main = by_currency.get(main_currency, {"pledged": 0, "confirmed": 0, "received": 0})
    state = {
        "event": event, "guests": guests, "pledges": pledges, "role": role,
        "permissions": sorted(permissions),
        "key_terms": keyterm_preview(event_id),
        "totals": {**main, "currency": main_currency, "by_currency": by_currency,
                   "flags": sum(p["state"] == "flagged" for p in pledges),
                   "in_kind": sum(1 for p in pledges if p["item"])},
        "payments": {"mode": settings.paystack_mode},
        "email_configured": settings.email_configured,
        "removed_guests": database.one("SELECT COUNT(*) AS n FROM guests WHERE event_id = ? AND removed_at IS NOT NULL", (event_id,))["n"],
    }
    if "follow_up" in permissions:
        state["follow_up"] = follow_up_view(event_id)
    if event.get("org_id"):
        state["usage"] = {"used": usage_today(event["org_id"]), "limits": usage_limits()}
    return state


def delete_event_data(event_id: str) -> None:
    for table in ("deliveries", "pledge_links", "payments", "calls", "audit_log", "pledges", "guests"):
        database.execute(f"DELETE FROM {table} WHERE event_id = ?", (event_id,))
    database.execute("DELETE FROM invites WHERE event_id = ?", (event_id,))
    database.execute("DELETE FROM events WHERE id = ?", (event_id,))
    shutil.rmtree(settings.data_dir / "audio" / event_id, ignore_errors=True)
    shutil.rmtree(settings.data_dir / "uploads" / event_id, ignore_errors=True)


def purge_audio(event_id: str) -> None:
    shutil.rmtree(settings.data_dir / "audio" / event_id, ignore_errors=True)
    shutil.rmtree(settings.data_dir / "uploads" / event_id, ignore_errors=True)
    database.execute("UPDATE pledges SET audio_path = NULL, safe_audio_path = NULL WHERE event_id = ?", (event_id,))
    database.execute("UPDATE events SET audio_purged_at = ? WHERE id = ?", (now(), event_id))
    database.audit(event_id, "audio_deleted_by_retention", {})


def apply_retention() -> dict:
    """Delete expired sample events and the audio of ended events past their retention."""

    current = datetime.now(timezone.utc)
    samples = 0
    for event in database.all("SELECT id, expires_at FROM events WHERE sample = 1 OR demo = 1"):
        expiry = parse_time(event.get("expires_at"))
        if expiry and expiry <= current:
            delete_event_data(event["id"])
            samples += 1
    purged = 0
    for event in database.all(
        "SELECT e.id, e.ended_at, o.retention_days FROM events e JOIN organisations o ON o.id = e.org_id "
        "WHERE e.ended_at IS NOT NULL AND e.audio_purged_at IS NULL"
    ):
        ended = parse_time(event["ended_at"])
        if ended and ended + timedelta(days=int(event["retention_days"])) <= current:
            purge_audio(event["id"])
            purged += 1
    database.execute("DELETE FROM sessions WHERE expires_at <= ?", (current.isoformat(),))
    return {"sample_events_deleted": samples, "audio_purged": purged}


def safe_data_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).resolve()
    if settings.data_dir.resolve() not in path.parents or not path.is_file():
        return None
    return path
