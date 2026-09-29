from __future__ import annotations

import asyncio
from array import array
import csv
from datetime import date, datetime, timedelta, timezone
import html
import io
import json
from pathlib import Path
import re
import secrets
import shutil
import sys
import uuid
import wave

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .amounts import parse_amount
from .config import Settings
from .db import Database, now
from .extractor import TurnWindow, extract_turn
from .names import match_name
from .payments import PaystackError, initialize_transaction, valid_webhook_signature, verify_transaction
from .services import AssemblyAIError, open_realtime, paced_pcm16, sync_transcribe, voice_token


ROOT = Path(__file__).resolve().parents[1]
settings = Settings.load()
database = Database(settings.data_dir / "pledgebook.sqlite3")
app = FastAPI(title="Pledgebook", version="0.1.0")

DEMO_AUDIO_LIMIT_SECONDS = 180
DEMO_CALL_LIMIT = 2
DEMO_DAILY_LIMIT = 25
DEMO_RETENTION_HOURS = 24

# One event can have one or more capture tabs. Each connection has a lock so
# an usher's listening-list update cannot interleave with an audio frame.
live_sessions: dict[str, dict[object, asyncio.Lock]] = {}
cleanup_task: asyncio.Task | None = None


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        purge_expired_demo_events()


@app.on_event("startup")
async def start_cleanup_loop() -> None:
    global cleanup_task
    cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def stop_cleanup_loop() -> None:
    global cleanup_task
    if cleanup_task:
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        cleanup_task = None


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    organisation: str = Field(default="Grace Assembly", min_length=1, max_length=160)
    event_date: str = Field(default_factory=lambda: date.today().isoformat())
    target: int = Field(default=0, ge=0)
    minimum: int = Field(default=0, ge=0)
    maximum: int = Field(default=0, ge=0)
    demo: bool = False


class GuestCreate(BaseModel):
    title: str = ""
    name: str = Field(min_length=1, max_length=160)
    phone: str = ""
    email: str = ""
    consent_to_contact: bool = False
    group: str = ""


class ResolveRequest(BaseModel):
    action: str
    guest_id: int | None = None
    amount: int | None = Field(default=None, ge=0)
    reason: str = ""


class VoiceCallStart(BaseModel):
    browser_call_id: str = Field(min_length=8, max_length=120)


class VoiceToolRequest(BaseModel):
    browser_call_id: str = Field(min_length=8, max_length=120)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)


class Hub:
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


def invented_guests() -> list[dict]:
    names = [
        ("Ms", "Amina Yusuf"),
        ("Mr", "Chinedu Obi"),
        ("Dr", "Tola Adeyemi"),
    ]
    return [{"title": title, "name": name, "phone": "", "email": "", "consent_to_contact": False, "group": ""}
            for title, name in names]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def purge_expired_demo_events() -> int:
    """Delete demo rows and audio after the advertised 24-hour retention."""

    cutoff = datetime.now(timezone.utc)
    expired = []
    for event in database.all("SELECT id, expires_at FROM events WHERE demo = 1"):
        expiry = parse_time(event.get("expires_at"))
        if expiry and expiry <= cutoff:
            expired.append(event["id"])
    for event_id in expired:
        for table in ("payments", "calls", "audit_log", "pledges", "guests"):
            database.execute(f"DELETE FROM {table} WHERE event_id = ?", (event_id,))
        database.execute("DELETE FROM events WHERE id = ?", (event_id,))
        shutil.rmtree(settings.data_dir / "audio" / event_id, ignore_errors=True)
        shutil.rmtree(settings.data_dir / "uploads" / event_id, ignore_errors=True)
    return len(expired)


def event_or_404(event_id: str) -> dict:
    purge_expired_demo_events()
    event = database.one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        raise HTTPException(404, "Event was not found")
    return event


def guests_for(event_id: str) -> list[dict]:
    return database.all("SELECT * FROM guests WHERE event_id = ? ORDER BY id", (event_id,))


def serialise_pledge(row: dict) -> dict:
    result = dict(row)
    result["amount"] = result.pop("amount_minor")
    return result


def serialise_payment(row: dict) -> dict:
    try:
        payload = json.loads(row.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    token = row.get("public_token")
    payment_page = f"/pay/{token}" if token else None
    if token and settings.public_url:
        payment_page = f"{settings.public_url}/pay/{token}"
    return {
        "id": row["id"],
        "pledge_id": row["pledge_id"],
        "reference": row["reference"],
        "amount_kobo": row["amount_kobo"],
        "email": row["email"],
        "payment_link": row["authorization_url"],
        "payment_page": payment_page,
        "status": row["status"],
        "paystack_status": row["paystack_status"],
        "paid_at": payload.get("paid_at"),
        "expires_at": row.get("expires_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def event_payments(event_id: str) -> list[dict]:
    return [serialise_payment(row) for row in database.all(
        "SELECT * FROM payments WHERE event_id = ? ORDER BY id DESC", (event_id,)
    )]


def event_calls(event_id: str) -> list[dict]:
    result = []
    for row in database.all("SELECT * FROM calls WHERE event_id = ? ORDER BY id DESC", (event_id,)):
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            details = {}
        result.append({"id": row["id"], "pledge_id": row["pledge_id"], "outcome": row["outcome"],
                       "promised_date": details.get("promised_date"), "dispute": details.get("dispute"),
                       "payment_link": details.get("payment_link"),
                       "payment_reference": details.get("payment_reference"),
                       "created_at": row["created_at"]})
    return result


def event_state(event_id: str) -> dict:
    event = event_or_404(event_id)
    guests = guests_for(event_id)
    pledges = [serialise_pledge(row) for row in database.all(
        "SELECT * FROM pledges WHERE event_id = ? ORDER BY id DESC", (event_id,))]
    pledged = sum((p["amount"] or 0) for p in pledges if p["currency"] in (None, "NGN") and p["state"] not in ("rejected",))
    confirmed = sum((p["amount"] or 0) for p in pledges if p["currency"] in (None, "NGN") and p["state"] in ("confirmed", "corrected", "redeemed"))
    received = sum((p["amount"] or 0) for p in pledges if p["state"] == "redeemed" and p["currency"] in (None, "NGN"))
    demo_expiry = parse_time(event.get("expires_at"))
    return {
        "event": event, "guests": guests, "pledges": pledges,
        "key_terms": keyterm_preview(event_id), "calls": event_calls(event_id),
        "totals": {"pledged": pledged, "confirmed": confirmed, "received": received,
                   "flags": sum(p["state"] == "flagged" for p in pledges),
                   "in_kind": sum(1 for p in pledges if p["item"])},
        "payments": {"configured": bool(settings.paystack_secret_key),
                      "message": "Paystack test mode is not configured yet." if not settings.paystack_secret_key else "Paystack test mode is configured.",
                      "records": event_payments(event_id)},
        "limits": {
            "audio_seconds_used": int(event.get("demo_audio_seconds") or 0),
            "audio_seconds_limit": DEMO_AUDIO_LIMIT_SECONDS if event.get("demo") else None,
            "calls_used": len(event_calls(event_id)) if event.get("demo") else None,
            "calls_limit": DEMO_CALL_LIMIT if event.get("demo") else None,
            "expires_at": event.get("expires_at"),
            "retention_hours": DEMO_RETENTION_HOURS if event.get("demo") else None,
            "expired": bool(demo_expiry and demo_expiry <= datetime.now(timezone.utc)),
        },
    }


@app.get("/healthz")
async def healthz():
    purge_expired_demo_events()
    return {"ok": True, "assemblyai_configured": bool(settings.assemblyai_api_key),
            "paystack_configured": bool(settings.paystack_secret_key), "version": app.version}


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/static/{path:path}")
async def static_file(path: str):
    file = (ROOT / "web" / path).resolve()
    if ROOT / "web" not in file.parents or not file.is_file():
        raise HTTPException(404, "File was not found")
    return FileResponse(file, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.post("/api/events")
async def create_event(payload: EventCreate):
    purge_expired_demo_events()
    if payload.demo:
        today_prefix = datetime.now(timezone.utc).date().isoformat()
        created_today = database.one(
            "SELECT COUNT(*) AS count FROM events WHERE demo = 1 AND created_at >= ?",
            (today_prefix,),
        )
        if int((created_today or {}).get("count") or 0) >= DEMO_DAILY_LIMIT:
            raise HTTPException(429, "Today's public demo limit has been reached. The sample recording remains available.")
    event_id = uuid.uuid4().hex
    created_at = now()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=DEMO_RETENTION_HOURS)).isoformat() if payload.demo else None
    database.execute(
        "INSERT INTO events(id, name, organisation, event_date, target_minor, min_minor, max_minor, demo, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'setup', ?, ?)",
        (event_id, payload.name.strip(), payload.organisation.strip(), payload.event_date,
         payload.target, payload.minimum, payload.maximum, int(payload.demo), created_at, expires_at),
    )
    if payload.demo:
        for guest in invented_guests():
            database.execute("INSERT INTO guests(event_id, title, name, phone, email, consent_to_contact, group_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (event_id, guest["title"], guest["name"], guest["phone"], guest["email"], int(guest["consent_to_contact"]), guest["group"], now()))
    database.audit(event_id, "event_created", {"demo": payload.demo, "invented_names": payload.demo})
    return event_state(event_id)


@app.get("/api/sample-recording")
async def sample_recording():
    path = settings.sample_audio_path
    if not path or not path.is_file():
        raise HTTPException(404, "The owner-approved sample recording is not configured.")
    return FileResponse(path, media_type="audio/wav", filename="pledgebook-demo.wav")


@app.get("/api/events/{event_id}")
async def get_event(event_id: str):
    return event_state(event_id)


@app.post("/api/events/{event_id}/start")
async def start_event(event_id: str):
    event_or_404(event_id)
    database.execute("UPDATE events SET status = 'live' WHERE id = ?", (event_id,))
    database.audit(event_id, "event_started", {})
    await hub.publish(event_id, {"type": "event", "status": "live"})
    return event_state(event_id)


@app.post("/api/events/{event_id}/guests")
async def add_guest(event_id: str, payload: GuestCreate):
    event_or_404(event_id)
    guest_id = database.execute("INSERT INTO guests(event_id, title, name, phone, email, consent_to_contact, group_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (event_id, payload.title.strip(), payload.name.strip(), payload.phone.strip(), payload.email.strip(), int(payload.consent_to_contact), payload.group.strip(), now()))
    database.audit(event_id, "guest_added", {"guest_id": guest_id, "name": payload.name.strip()})
    await update_live_listening_terms(event_id)
    return database.one("SELECT * FROM guests WHERE id = ?", (guest_id,))


@app.post("/api/events/{event_id}/guests/import")
async def import_guests(event_id: str, file: UploadFile = File(...)):
    event_or_404(event_id)
    raw = await file.read()
    try:
        rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "CSV must be UTF-8") from exc
    count = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        database.execute("INSERT INTO guests(event_id, title, name, phone, email, consent_to_contact, group_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (event_id, (row.get("title") or "").strip(), name, (row.get("phone") or "").strip(),
                          (row.get("email") or "").strip(), int((row.get("consent_to_contact") or "").lower() in {"1", "true", "yes"}),
                          (row.get("group") or "").strip(), now()))
        count += 1
    database.audit(event_id, "guests_imported", {"count": count, "filename": file.filename or "guest-list.csv"})
    await update_live_listening_terms(event_id)
    return {"imported": count, "state": event_state(event_id)}


@app.get("/api/events/{event_id}/stream")
async def stream_updates(event_id: str):
    event_or_404(event_id)
    queue = await hub.subscribe(event_id)

    async def generate():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            hub.unsubscribe(event_id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def keyterm_preview(event_id: str) -> dict:
    terms = []
    for guest in guests_for(event_id):
        terms.append(" ".join(part for part in (guest.get("title"), guest.get("name")) if part).strip())
    terms = [term for term in terms if term]
    included = []
    overflow = []
    characters = 0
    for term in terms:
        if len(included) >= 100 or characters + len(term) > 8000:
            overflow.append(term)
            continue
        included.append(term)
        characters += len(term)
    return {"terms": included, "overflow": overflow, "included_count": len(included), "overflow_count": len(overflow), "characters": characters, "term_limit": 100, "character_limit": 8000}


def event_keyterms(event_id: str) -> list[str]:
    return keyterm_preview(event_id)["terms"]


async def update_live_listening_terms(event_id: str) -> int:
    """Apply the current guest list to every active Realtime session."""

    sessions = live_sessions.get(event_id, {})
    terms = event_keyterms(event_id)
    updated = 0
    for aai, lock in list(sessions.items()):
        try:
            async with lock:
                await aai.send(json.dumps({"type": "UpdateConfiguration", "keyterms_prompt": terms}))
            updated += 1
        except Exception:
            sessions.pop(aai, None)
    return updated


def save_pcm_clip(event_id: str, pledge_id: int, pcm: bytes, start_ms: int, end_ms: int) -> Path | None:
    start_byte = max(0, int(max(0, start_ms) * 16 * 2))
    end_byte = min(len(pcm), int(max(start_ms + 80, end_ms) * 16 * 2))
    data = pcm[start_byte:end_byte]
    if not data:
        return None
    folder = settings.data_dir / "audio" / event_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"pledge-{pledge_id}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(data)
    return path


def make_safe_audio_clip(event_id: str, pledge_id: int, audio_path: Path, recheck, text: str, words: list[dict], guest_id: int | None) -> tuple[Path | None, str]:
    """Trim a confirmed pledge to its recheck word span only when it is private."""

    if not guest_id:
        return None, "Audio is not shown because this pledge has no confirmed guest."
    if not words or not audio_path.is_file():
        return None, "Audio is not shown because word timings were not returned."
    guests = guests_for(event_id)
    heard_guests = []
    normal_text = re.sub(r"[^a-z]+", "", text.lower())
    for guest in guests:
        name_norm = re.sub(r"[^a-z]+", "", guest.get("name", "").lower())
        if name_norm and name_norm in normal_text:
            heard_guests.append(guest)
    if len(heard_guests) != 1 or int(heard_guests[0]["id"]) != int(guest_id):
        return None, "Audio is not shown because it included another guest's name."
    if not recheck.amount.is_clear or recheck.start_ms >= recheck.end_ms:
        return None, "Audio is not shown because the amount was not a single clear phrase."
    try:
        with wave.open(str(audio_path), "rb") as source:
            rate = source.getframerate()
            channels = source.getnchannels()
            width = source.getsampwidth()
            frame_count = source.getnframes()
            if rate != 16000 or channels != 1 or width != 2:
                return None, "Audio is not shown because the stored clip has an unsupported format."
            start_frame = max(0, int((recheck.start_ms - 60) * rate / 1000))
            end_frame = min(frame_count, int((recheck.end_ms + 60) * rate / 1000))
            if end_frame <= start_frame:
                return None, "Audio is not shown because its word timings were empty."
            source.setpos(start_frame)
            frames = source.readframes(end_frame - start_frame)
        safe_path = settings.data_dir / "audio" / event_id / f"pledge-{pledge_id}-safe.wav"
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(safe_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(frames)
        return safe_path, "Audio contains only this guest's rechecked name and amount."
    except (OSError, wave.Error) as exc:
        return None, f"Audio is not shown because the clip could not be trimmed: {exc}"


async def confirm_pledge(event_id: str, pledge_id: int):
    pledge = database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
    if not pledge or not pledge.get("audio_path"):
        return
    try:
        response, elapsed_ms = await sync_transcribe(settings, Path(pledge["audio_path"]), event_keyterms(event_id))
        text = response.get("text") or ""
        words = response.get("words") or []
        guests = guests_for(event_id)
        recheck = extract_turn(text, words, guests)
        current_guest = pledge.get("guest_id")
        recheck_guest = recheck.name_match.guest_id if recheck.name_match else None
        amount = recheck.amount
        anonymous = pledge.get("heard_name") == "Anonymous donor"
        if not amount.is_clear:
            state, reason = "flagged", amount.reason or "Amount unclear — please check the recording."
        elif pledge.get("currency") and amount.currency and pledge["currency"] != amount.currency:
            state, reason = "flagged", "The recheck heard a different currency — please check."
        elif current_guest and recheck_guest and current_guest != recheck_guest:
            state, reason = "flagged", "The recheck heard a different guest — please check."
            current_guest = None
        elif anonymous or (recheck.name_match and recheck.name_match.kind == "anonymous"):
            state, reason = "confirmed", "Anonymous pledge — no follow-up call."
            current_guest = None
        elif recheck.name_match and recheck.name_match.kind != "matched":
            state, reason = "flagged", recheck.name_match.reason or "The name needs a human check."
            current_guest = None
        elif not current_guest and recheck_guest is None:
            state, reason = "flagged", recheck.name_match.reason if recheck.name_match else "Name not on the guest list — please confirm."
        elif pledge["amount_minor"] is not None and amount.minor != pledge["amount_minor"]:
            state, reason = "corrected", f"₦{pledge['amount_minor']:,} → ₦{amount.minor:,} (rechecked)."
        else:
            state, reason = "confirmed", ""
        matched_name = recheck.name_match.guest_name if recheck.name_match and recheck.name_match.guest_name else pledge["matched_name"]
        safe_path = None
        safe_reason = ""
        if state in {"confirmed", "corrected"} and current_guest and amount.is_clear:
            safe_path, safe_reason = make_safe_audio_clip(event_id, pledge_id, Path(pledge["audio_path"]), recheck, text, words, current_guest)
        database.execute("UPDATE pledges SET guest_id = ?, recheck_text = ?, amount_minor = ?, currency = ?, matched_name = ?, state = ?, reason = ?, safe_audio_path = ?, safe_audio_reason = ?, updated_at = ? WHERE id = ?",
                         (current_guest, text, amount.minor if amount.minor is not None else pledge["amount_minor"], amount.currency or pledge["currency"], matched_name if current_guest else "", state, reason, str(safe_path) if safe_path else None, safe_reason, now(), pledge_id))
        database.audit(event_id, "rechecked", {"text": text, "elapsed_ms": elapsed_ms, "state": state, "reason": reason}, pledge_id)
        await hub.publish(event_id, {"type": "pledge", "pledge": serialise_pledge(database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))), "state": event_state(event_id)})
    except Exception as exc:
        database.execute("UPDATE pledges SET reason = ?, updated_at = ? WHERE id = ?", (f"Not rechecked — {exc}", now(), pledge_id))
        database.audit(event_id, "recheck_failed", {"error": str(exc)}, pledge_id)
        await hub.publish(event_id, {"type": "pledge", "pledge": serialise_pledge(database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))), "state": event_state(event_id)})


async def create_live_pledge(event_id: str, live_text: str, live_words: list[dict], name_turn, amount_turn, pcm: bytes, browser: WebSocket | None):
    event = event_or_404(event_id)
    guests = guests_for(event_id)
    name_match = name_turn.name_match
    if name_match is None and name_turn.name:
        name_match = match_name(name_turn.name, guests)
    amount = amount_turn.amount
    state = "provisional"
    reason = ""
    if not amount.is_clear:
        state, reason = "flagged", amount.reason or "Amount unclear — please check."
    elif not name_turn.name:
        state, reason = "flagged", "Name unclear — please confirm."
    elif name_match and name_match.kind == "anonymous":
        state, reason = "provisional", "Anonymous pledge — no follow-up call."
    elif not name_match or name_match.guest_id is None:
        state, reason = "flagged", name_match.reason if name_match else "Name not on the guest list — please confirm."
    elif amount.minor is not None and event["min_minor"] and amount.minor < event["min_minor"]:
        state, reason = "flagged", "Amount is below this event's allowed minimum."
    elif amount.minor is not None and event["max_minor"] and amount.minor > event["max_minor"]:
        state, reason = "flagged", "Amount is above this event's allowed maximum."
    start_ms = min(name_turn.start_ms, amount_turn.start_ms)
    end_ms = max(name_turn.end_ms, amount_turn.end_ms)
    recognised_from = None
    recognised_at = None
    if name_match and name_match.kind == "matched" and name_match.guest_id:
        learned_guest = database.one("SELECT learned_from_pledge_id, learned_at FROM guests WHERE id = ?", (name_match.guest_id,))
        if learned_guest and learned_guest.get("learned_from_pledge_id"):
            recognised_from = learned_guest["learned_from_pledge_id"]
            recognised_at = learned_guest.get("learned_at")

    # Realtime can revise a final turn or repeat the same pledge while the
    # speaker is still being segmented. Treat a nearby repeat as one record;
    # keep every change in the audit log. A new pledge from the same guest is
    # still possible when the MC says "adding another", "plus", or similar.
    recent = None
    if name_match and name_match.guest_id is not None:
        recent = database.one(
            "SELECT * FROM pledges WHERE event_id = ? AND guest_id = ? "
            "AND source_start_ms IS NOT NULL AND ABS(source_start_ms - ?) <= 60000 "
            "ORDER BY id DESC LIMIT 1",
            (event_id, name_match.guest_id, start_ms),
        )
    add_on = bool(re.search(r"\b(?:add(?:ing)?|another|plus|extra|in addition)\b", live_text, re.IGNORECASE))
    if recent and not add_on:
        if recent["amount_minor"] == amount.minor and recent["currency"] == amount.currency and recent["item"] == amount.item:
            database.audit(event_id, "live_repeat_ignored", {"text": live_text, "repeated_pledge_id": recent["id"]}, recent["id"])
            return
        database.audit(event_id, "live_revision", {
            "previous_amount": recent["amount_minor"], "previous_currency": recent["currency"],
            "new_amount": amount.minor, "new_currency": amount.currency, "text": live_text,
        }, recent["id"])
        database.execute(
            "UPDATE pledges SET guest_id = ?, heard_name = ?, matched_name = ?, amount_minor = ?, currency = ?, item = ?, "
            "live_text = ?, recheck_text = '', source_start_ms = ?, source_end_ms = ?, state = ?, reason = ?, recognised_from_pledge_id = ?, recognised_at = ?, updated_at = ? WHERE id = ?",
            (name_match.guest_id, name_turn.name or "", name_match.guest_name or "", amount.minor, amount.currency, amount.item,
             live_text, start_ms, end_ms, state, reason, recognised_from, recognised_at, now(), recent["id"]),
        )
        clip = save_pcm_clip(event_id, recent["id"], pcm, start_ms - 500, end_ms + 500)
        if clip:
            database.execute("UPDATE pledges SET audio_path = ? WHERE id = ?", (str(clip), recent["id"]))
        pledge = serialise_pledge(database.one("SELECT * FROM pledges WHERE id = ?", (recent["id"],)))
        if browser is not None:
            await browser.send_json({"type": "pledge", "pledge": pledge, "state": event_state(event_id)})
        await hub.publish(event_id, {"type": "pledge", "pledge": pledge, "state": event_state(event_id)})
        if clip:
            asyncio.create_task(confirm_pledge(event_id, recent["id"]))
        return
    pledge_id = database.execute(
        "INSERT INTO pledges(event_id, guest_id, heard_name, matched_name, amount_minor, currency, item, live_text, source_start_ms, source_end_ms, state, reason, recognised_from_pledge_id, recognised_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, name_match.guest_id if name_match else None, name_turn.name or "", name_match.guest_name if name_match and name_match.guest_name else "",
         amount.minor, amount.currency, amount.item, live_text, start_ms, end_ms, state, reason, recognised_from, recognised_at, now(), now()),
    )
    clip = save_pcm_clip(event_id, pledge_id, pcm, start_ms - 500, end_ms + 500)
    if clip:
        database.execute("UPDATE pledges SET audio_path = ? WHERE id = ?", (str(clip), pledge_id))
    database.audit(event_id, "live_pledge", {"text": live_text, "state": state}, pledge_id)
    pledge = serialise_pledge(database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,)))
    if browser is not None:
        await browser.send_json({"type": "pledge", "pledge": pledge, "state": event_state(event_id)})
    await hub.publish(event_id, {"type": "pledge", "pledge": pledge, "state": event_state(event_id)})
    if clip:
        asyncio.create_task(confirm_pledge(event_id, pledge_id))


async def process_uploaded_audio(event_id: str, audio_path: Path):
    """Run an uploaded human WAV through the same live and confirming path."""
    aai, _ = await open_realtime(settings, event_keyterms(event_id))
    session_lock = asyncio.Lock()
    live_sessions.setdefault(event_id, {})[aai] = session_lock
    audio = bytearray()
    event = event_or_404(event_id)
    window = TurnWindow()
    seen: set[tuple[int, int, str]] = set()

    async def read_assembly():
        async for raw in aai:
            event = json.loads(raw)
            await hub.publish(event_id, {"type": "realtime", "event": event})
            if event.get("type") != "Turn" or not event.get("end_of_turn"):
                continue
            text = event.get("transcript") or ""
            words = event.get("words") or []
            turn = extract_turn(text, words, guests_for(event_id))
            name_turn, amount_turn, pairing_reason = window.add(turn)
            if not name_turn or not amount_turn:
                if pairing_reason and amount_turn:
                    await create_live_pledge(event_id, amount_turn.text, words, amount_turn, amount_turn, bytes(audio), None)
                continue
            key = (name_turn.start_ms, amount_turn.end_ms, f"{name_turn.name}|{amount_turn.text}")
            if key in seen:
                continue
            seen.add(key)
            await create_live_pledge(event_id, " ".join(part for part in (name_turn.text, amount_turn.text) if part), words, name_turn, amount_turn, bytes(audio), None)

    reader = asyncio.create_task(read_assembly())
    try:
        async for chunk in paced_pcm16(audio_path):
            if event.get("demo") and len(audio) / (16000 * 2) >= DEMO_AUDIO_LIMIT_SECONDS:
                raise RuntimeError("This private demo has used its three-minute microphone limit.")
            audio.extend(chunk)
            async with session_lock:
                await aai.send(chunk)
        await asyncio.sleep(2)
        async with session_lock:
            await aai.send(json.dumps({"type": "Terminate"}))
        await asyncio.wait_for(reader, 12)
    finally:
        if not reader.done():
            reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        if event.get("demo"):
            database.execute("UPDATE events SET demo_audio_seconds = demo_audio_seconds + ? WHERE id = ?", (int(len(audio) / (16000 * 2)), event_id))
        live_sessions.get(event_id, {}).pop(aai, None)
        await aai.close()


async def process_uploaded_audio_safely(event_id: str, audio_path: Path):
    """Keep background upload failures visible to the event and audit log."""
    try:
        await process_uploaded_audio(event_id, audio_path)
        database.audit(event_id, "audio_upload_finished", {"path": str(audio_path)})
        await hub.publish(event_id, {"type": "upload", "status": "finished"})
    except Exception as exc:
        database.audit(event_id, "audio_upload_failed", {"error": str(exc)})
        await hub.publish(event_id, {"type": "error", "message": f"The recording could not be processed: {exc}"})


def normalise_wav(path: Path) -> None:
    """Convert a real PCM16 WAV to the 16 kHz mono format Realtime expects."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        if wav.getcomptype() != "NONE":
            raise ValueError("The WAV must use uncompressed PCM audio")
        if channels not in (1, 2) or width != 2:
            raise ValueError("The WAV must be mono or stereo 16-bit PCM")
        if rate <= 0 or frames <= 0:
            raise ValueError("The WAV has no audio")
        raw = wav.readframes(frames)

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    if channels == 2:
        mono = array("h", ((int(samples[i]) + int(samples[i + 1])) // 2 for i in range(0, len(samples), 2)))
    else:
        mono = samples

    if rate == 16000:
        output = mono
    else:
        output_frames = max(1, round(len(mono) * 16000 / rate))
        output = array("h")
        for index in range(output_frames):
            source = index * rate / 16000
            left = min(len(mono) - 1, int(source))
            right = min(len(mono) - 1, left + 1)
            fraction = source - left
            value = round(mono[left] + (mono[right] - mono[left]) * fraction)
            output.append(max(-32768, min(32767, value)))

    temporary = path.with_suffix(".normalised.wav")
    with wave.open(str(temporary), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(output.tobytes())
    temporary.replace(path)


@app.post("/api/events/{event_id}/upload")
async def upload_audio(event_id: str, file: UploadFile = File(...)):
    event = event_or_404(event_id)
    if event.get("status") != "live":
        raise HTTPException(409, "Start the event before processing a recording.")
    if not (file.filename or "").lower().endswith(".wav"):
        raise HTTPException(415, "Upload a WAV recording")
    raw = await file.read()
    upload_dir = settings.data_dir / "uploads" / event_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}.wav"
    path.write_bytes(raw)
    try:
        with wave.open(str(path), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            if duration > 120:
                path.unlink(missing_ok=True)
                raise HTTPException(413, "The uploaded recording is longer than the 120-second live clip limit.")
            if event.get("demo") and int(event.get("demo_audio_seconds") or 0) + duration > DEMO_AUDIO_LIMIT_SECONDS:
                path.unlink(missing_ok=True)
                raise HTTPException(429, "This private demo has reached its three-minute microphone limit.")
        normalise_wav(path)
    except HTTPException:
        raise
    except (ValueError, wave.Error) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(415, str(exc)) from exc
    database.audit(event_id, "audio_upload_started", {"filename": file.filename, "bytes": len(raw)})
    asyncio.create_task(process_uploaded_audio_safely(event_id, path))
    return {"accepted": True, "message": "The recording is being heard now. Watch the pledge list for updates."}


@app.websocket("/ws/events/{event_id}/capture")
async def capture(event_id: str, browser: WebSocket):
    await browser.accept()
    event = event_or_404(event_id)
    if event.get("status") != "live":
        await browser.send_json({"type": "error", "message": "Start the event before opening the microphone."})
        await browser.close(code=1008)
        return
    try:
        aai, begin = await open_realtime(settings, event_keyterms(event_id))
    except Exception as exc:
        await browser.send_json({"type": "error", "message": str(exc)})
        await browser.close(code=1011)
        return
    await browser.send_json({"type": "connection", "status": "Listening", "begin": begin})
    session_lock = asyncio.Lock()
    live_sessions.setdefault(event_id, {})[aai] = session_lock
    audio = bytearray()
    window = TurnWindow()
    seen: set[tuple[int, int, str]] = set()
    reading_task = None

    async def read_assembly():
        async for raw in aai:
            event = json.loads(raw)
            await browser.send_json({"type": "realtime", "event": event})
            if event.get("type") != "Turn" or not event.get("end_of_turn"):
                continue
            text = event.get("transcript") or ""
            words = event.get("words") or []
            turn = extract_turn(text, words, guests_for(event_id))
            name_turn, amount_turn, pairing_reason = window.add(turn)
            if not name_turn or not amount_turn:
                if pairing_reason:
                    await browser.send_json({"type": "notice", "message": pairing_reason})
                    # Keep an amount with no usable name visible for an usher;
                    # it must never disappear silently.
                    if amount_turn:
                        await create_live_pledge(event_id, amount_turn.text, words, amount_turn, amount_turn, bytes(audio), browser)
                continue
            key = (name_turn.start_ms, amount_turn.end_ms, f"{name_turn.name}|{amount_turn.text}")
            if key in seen:
                continue
            seen.add(key)
            combined = " ".join(part for part in (name_turn.text, amount_turn.text) if part)
            await create_live_pledge(event_id, combined, words, name_turn, amount_turn, bytes(audio), browser)

    reading_task = asyncio.create_task(read_assembly())
    try:
        while True:
            message = await browser.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                if event.get("demo") and (len(audio) + len(chunk)) / (16000 * 2) > DEMO_AUDIO_LIMIT_SECONDS:
                    await browser.send_json({"type": "error", "message": "This private demo has reached its three-minute microphone limit."})
                    async with session_lock:
                        await aai.send(json.dumps({"type": "Terminate"}))
                    break
                audio.extend(chunk)
                async with session_lock:
                    await aai.send(chunk)
            elif message.get("text"):
                try:
                    command = json.loads(message["text"])
                except json.JSONDecodeError:
                    command = {}
                if command.get("type") == "stop":
                    async with session_lock:
                        await aai.send(json.dumps({"type": "Terminate"}))
                    # Termination flushes the last unfinished amount turn. Do
                    # not cancel the reader before AssemblyAI sends that final
                    # Turn, or the pledge would vanish at the button press.
                    try:
                        await asyncio.wait_for(reading_task, 10)
                    except asyncio.TimeoutError:
                        reading_task.cancel()
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if event.get("demo") and audio:
            database.execute("UPDATE events SET demo_audio_seconds = demo_audio_seconds + ? WHERE id = ?", (int(len(audio) / (16000 * 2)), event_id))
        live_sessions.get(event_id, {}).pop(aai, None)
        if not reading_task.done():
            reading_task.cancel()
        try:
            await aai.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass


@app.get("/api/audio/{event_id}/{pledge_id}")
async def pledge_audio(event_id: str, pledge_id: int):
    event_or_404(event_id)
    pledge = database.one("SELECT audio_path FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge or not pledge.get("audio_path"):
        raise HTTPException(404, "The audio moment is not available")
    path = Path(pledge["audio_path"]).resolve()
    if settings.data_dir.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "The audio moment is not available")
    return FileResponse(path, media_type="audio/wav")


def payment_by_token(token: str) -> dict:
    payment = database.one("SELECT * FROM payments WHERE public_token = ?", (token,))
    if not payment:
        raise HTTPException(404, "This payment page was not found.")
    expiry = parse_time(payment.get("expires_at"))
    if expiry and expiry <= datetime.now(timezone.utc):
        raise HTTPException(410, "This payment page has expired. Ask the organiser for a new link.")
    return payment


@app.get("/pay/{token}", response_class=HTMLResponse)
async def payment_page(token: str):
    try:
        payment = payment_by_token(token)
    except HTTPException as exc:
        return HTMLResponse(f"<h1>Pledgebook</h1><p>{html.escape(str(exc.detail))}</p>", status_code=exc.status_code)
    event = event_or_404(payment["event_id"])
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (payment["pledge_id"], payment["event_id"]))
    if not pledge:
        return HTMLResponse("<h1>Pledgebook</h1><p>This pledge is no longer available.</p>", status_code=404)
    guest_name = pledge.get("matched_name") or pledge.get("heard_name") or "Guest"
    amount = pledge.get("amount_minor") or 0
    amount_label = f"₦{int(amount):,}" if (pledge.get("currency") in (None, "NGN")) else f"{pledge.get('currency')} {amount:,}"
    safe_audio = pledge.get("safe_audio_path")
    audio_available = bool(safe_audio and Path(safe_audio).is_file())
    audio_block = (
        f'<audio controls preload="none" src="/api/payment/{html.escape(token)}/audio"></audio>'
        if audio_available else
        f'<p class="muted">{html.escape(pledge.get("safe_audio_reason") or "Audio is not shown because the exact words could not be separated safely.")}</p>'
    )
    transcript = html.escape(pledge.get("recheck_text") or pledge.get("live_text") or "The spoken words are not available.")
    event_name = html.escape(event.get("name") or "Fundraising event")
    organisation = html.escape(event.get("organisation") or "The organiser")
    guest_name_html = html.escape(guest_name)
    amount_html = html.escape(amount_label)
    paystack_link = html.escape(payment["authorization_url"], quote=True)
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pledgebook payment</title><style>body{{font:16px system-ui,sans-serif;background:#f8fafc;color:#1e293b;margin:0;padding:32px}}main{{max-width:620px;margin:auto;background:white;border:1px solid #e2e8f0;border-radius:20px;padding:28px;box-shadow:0 12px 40px #1e293b14}}h1{{margin-top:0}}.amount{{font-size:44px;font-weight:900;margin:12px 0}}audio{{width:100%;margin:12px 0}}a{{display:inline-block;background:#155eef;color:#fff;text-decoration:none;font-weight:800;padding:13px 17px;border-radius:10px}}.muted{{color:#64748b}}.notice{{background:#e8efff;padding:12px;border-radius:10px}}</style></head>
<body><main><p class="muted">Pledgebook · Test payment only</p><h1>Thank you, {guest_name_html}</h1>
<p>{organisation} · {event_name} · {html.escape(event.get("event_date") or "")}</p>
<h2>Here's the moment you pledged</h2>{audio_block}<p class="muted">Words heard: {transcript}</p>
<div class="amount">{amount_html}</div><p class="notice">This is a Paystack Test Mode checkout. No real money moves.</p>
<p><a href="{paystack_link}" target="_blank" rel="noreferrer">Continue to Paystack test checkout</a></p>
<p class="muted">Test card: 4084 0840 8408 4081 · expiry in the future · CVV 408</p></main></body></html>""")


@app.get("/api/payment/{token}/audio")
async def payment_audio(token: str):
    payment = payment_by_token(token)
    pledge = database.one("SELECT safe_audio_path FROM pledges WHERE id = ? AND event_id = ?", (payment["pledge_id"], payment["event_id"]))
    path = Path((pledge or {}).get("safe_audio_path") or "").resolve()
    if not pledge or not path.is_file() or settings.data_dir.resolve() not in path.parents:
        raise HTTPException(404, "The safe pledge moment is not available.")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/events/{event_id}/pledges/{pledge_id}/resolve")
async def resolve_pledge(event_id: str, pledge_id: int, payload: ResolveRequest):
    event_or_404(event_id)
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge:
        raise HTTPException(404, "Pledge was not found")
    action = payload.action
    if action == "reject":
        if not payload.reason.strip():
            raise HTTPException(400, "A reason is required when rejecting a pledge")
        state = "rejected"
        update = (state, payload.reason.strip())
    elif action == "anonymous":
        state = "confirmed"
        update = (state, "Anonymous pledge — no follow-up call.")
        database.execute("UPDATE pledges SET guest_id = NULL, matched_name = 'Anonymous donor' WHERE id = ?", (pledge_id,))
    elif action == "guest":
        guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (payload.guest_id or -1, event_id))
        if not guest:
            raise HTTPException(400, "Choose a guest from this event")
        state = "confirmed"
        update = (state, "")
        database.execute("UPDATE pledges SET guest_id = ?, matched_name = ? WHERE id = ?", (guest["id"], guest["name"], pledge_id))
        learned_at = now()
        database.execute("UPDATE guests SET learned_from_pledge_id = ?, learned_at = ? WHERE id = ?", (pledge_id, learned_at, guest["id"]))
    elif action == "amount":
        if payload.amount is None:
            raise HTTPException(400, "Enter an amount")
        state = "confirmed"
        update = (state, "")
        database.execute("UPDATE pledges SET amount_minor = ? WHERE id = ?", (payload.amount, pledge_id))
    else:
        raise HTTPException(400, "Unknown review action")
    database.execute("UPDATE pledges SET state = ?, reason = ?, updated_at = ? WHERE id = ?", (*update, now(), pledge_id))
    details = {"action": action, "reason": payload.reason}
    if action == "guest":
        updated_sessions = await update_live_listening_terms(event_id)
        details.update({"listening_list_updated": True, "active_sessions_updated": updated_sessions, "guest_id": payload.guest_id})
        database.audit(event_id, "listening_list_updated", {"guest_id": payload.guest_id, "by_pledge_id": pledge_id, "active_sessions_updated": updated_sessions}, pledge_id)
    database.audit(event_id, "usher_review", details, pledge_id)
    await hub.publish(event_id, {"type": "pledge", "pledge": serialise_pledge(database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))), "state": event_state(event_id)})
    return event_state(event_id)


@app.get("/api/voice-token")
async def get_voice_token():
    try:
        return {"token": await voice_token(settings)}
    except AssemblyAIError as exc:
        raise HTTPException(503, str(exc)) from exc


def call_row(event_id: str, pledge_id: int, browser_call_id: str) -> dict:
    rows = database.all("SELECT * FROM calls WHERE event_id = ? AND pledge_id = ? ORDER BY id DESC", (event_id, pledge_id))
    for row in rows:
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            details = {}
        if details.get("browser_call_id") == browser_call_id:
            row["details"] = details
            return row
    raise HTTPException(404, "This follow-up call was not found")


def latest_payment(event_id: str, pledge_id: int) -> dict | None:
    return database.one(
        "SELECT * FROM payments WHERE event_id = ? AND pledge_id = ? ORDER BY id DESC LIMIT 1",
        (event_id, pledge_id),
    )


def payment_page_url(token: str) -> str:
    relative = f"/pay/{token}"
    return f"{settings.public_url}{relative}" if settings.public_url else relative


def ensure_payment_page_token(payment: dict) -> dict:
    token = payment.get("public_token")
    expires_at = payment.get("expires_at")
    if not token or not expires_at:
        token = token or secrets.token_urlsafe(32)
        expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(hours=DEMO_RETENTION_HOURS)).isoformat()
        database.execute("UPDATE payments SET public_token = ?, expires_at = ? WHERE id = ?", (token, expires_at, payment["id"]))
        payment = {**payment, "public_token": token, "expires_at": expires_at}
    return payment


def payment_snapshot(data: dict) -> dict:
    """Keep only the Paystack fields needed for an audit trail."""

    return {
        "reference": data.get("reference"),
        "status": data.get("status"),
        "amount": data.get("amount"),
        "currency": data.get("currency"),
        "gateway_response": data.get("gateway_response"),
        "paid_at": data.get("paid_at"),
    }


async def verify_and_redeem_payment(payment: dict) -> dict:
    """Verify a Paystack transaction and redeem its pledge once only."""

    result = await verify_transaction(settings, payment["reference"])
    data = result["data"]
    status = str(data.get("status") or "").lower()
    snapshot = payment_snapshot(data)
    if data.get("reference") != payment["reference"]:
        raise PaystackError("Paystack returned a different payment reference.")
    if int(data.get("amount") or 0) != int(payment["amount_kobo"]):
        raise PaystackError("Paystack returned a different payment amount.")
    if str(data.get("currency") or "NGN").upper() != "NGN":
        raise PaystackError("Paystack returned a non-naira payment.")
    if status != "success":
        database.execute(
            "UPDATE payments SET status = ?, paystack_status = ?, payload_json = ?, updated_at = ? WHERE id = ?",
            ("pending", status, json.dumps(snapshot, ensure_ascii=False), now(), payment["id"]),
        )
        return {"redeemed": False, "status": status, "data": snapshot}

    database.execute(
        "UPDATE payments SET status = 'success', paystack_status = ?, payload_json = ?, updated_at = ? WHERE id = ?",
        (status, json.dumps(snapshot, ensure_ascii=False), now(), payment["id"]),
    )
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (payment["pledge_id"], payment["event_id"]))
    if not pledge:
        raise PaystackError("The payment is not linked to a pledge in this event.")
    if pledge["state"] != "redeemed":
        database.execute(
            "UPDATE pledges SET state = 'redeemed', reason = '', updated_at = ? WHERE id = ? AND state != 'redeemed'",
            (now(), pledge["id"]),
        )
        database.audit(payment["event_id"], "payment_redeemed", {"reference": payment["reference"], "amount_kobo": payment["amount_kobo"]}, pledge["id"])
    return {"redeemed": True, "status": status, "data": snapshot}


async def create_payment_link(event_id: str, pledge: dict, call: dict, guest: dict) -> dict:
    """Create or reuse a test checkout for a confirmed naira pledge."""

    if pledge.get("item"):
        return {"ok": False, "error": "This is an in-kind gift, so no payment link was created."}
    if pledge.get("currency") not in (None, "NGN"):
        return {"ok": False, "error": "Only naira pledges can use this Paystack test link."}
    amount_naira = int(pledge.get("amount_minor") or 0)
    if amount_naira <= 0:
        return {"ok": False, "error": "This pledge has no clear naira amount, so no payment link was created."}
    email = str(guest.get("email") or "").strip()
    if not email:
        return {"ok": False, "error": "This guest has no email address. Add one before sending a payment link."}

    existing = latest_payment(event_id, pledge["id"])
    if existing and existing["status"] in {"initialized", "pending", "success"}:
        existing = ensure_payment_page_token(existing)
        return {
            "ok": True,
            "payment_link": existing["authorization_url"],
            "payment_page": payment_page_url(existing["public_token"]),
            "reference": existing["reference"],
            "payment_status": existing["status"],
            "reused": True,
        }

    reference = f"pb-{event_id[:12]}-{pledge['id']}-{uuid.uuid4().hex[:10]}"
    try:
        created = await initialize_transaction(
            settings,
            amount_naira=amount_naira,
            email=email,
            reference=reference,
            metadata={"event_id": event_id, "pledge_id": pledge["id"], "call_id": call["id"], "product": "pledgebook"},
        )
    except PaystackError as exc:
        database.audit(event_id, "payment_link_failed", {"error": str(exc)}, pledge["id"])
        return {"ok": False, "error": str(exc)}
    data = created["data"]
    created_at = now()
    public_token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=DEMO_RETENTION_HOURS)).isoformat()
    database.execute(
        "INSERT INTO payments(event_id, pledge_id, reference, amount_kobo, email, authorization_url, public_token, expires_at, status, paystack_status, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'initialized', '', ?, ?, ?)",
        (event_id, pledge["id"], data["reference"], created["amount_kobo"], email, data["authorization_url"], public_token, expires_at, json.dumps({"message": created["body"].get("message")}, ensure_ascii=False), created_at, created_at),
    )
    database.audit(event_id, "payment_link_created", {"reference": data["reference"], "amount_kobo": created["amount_kobo"], "email": email}, pledge["id"])
    return {"ok": True, "payment_link": data["authorization_url"], "payment_page": payment_page_url(public_token), "reference": data["reference"], "payment_status": "initialized", "reused": False}


@app.post("/api/events/{event_id}/pledges/{pledge_id}/call/start")
async def start_follow_up_call(event_id: str, pledge_id: int, payload: VoiceCallStart):
    event = event_or_404(event_id)
    if event.get("demo") and len(event_calls(event_id)) >= DEMO_CALL_LIMIT:
        raise HTTPException(429, "This private demo allows two follow-up calls. Start again for a fresh sandbox.")
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge:
        raise HTTPException(404, "Pledge was not found")
    if pledge["state"] not in ("confirmed", "corrected", "redeemed"):
        raise HTTPException(400, "Only a confirmed pledge can start a follow-up")
    guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (pledge.get("guest_id") or -1, event_id))
    if not guest:
        raise HTTPException(400, "This pledge has no confirmed guest")
    if not guest["consent_to_contact"]:
        raise HTTPException(400, "Follow-up consent is not recorded for this guest")
    details = {"browser_call_id": payload.browser_call_id, "identity_confirmed": False, "pledge_id": pledge_id}
    call_id = database.execute(
        "INSERT INTO calls(event_id, pledge_id, outcome, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_id, pledge_id, "incomplete", json.dumps(details), now()),
    )
    database.audit(event_id, "follow_up_started", {"call_id": call_id}, pledge_id)
    return {"call_id": call_id, "event": {"name": event["name"], "organisation": event["organisation"], "event_date": event["event_date"]},
            "pledge": serialise_pledge(pledge), "guest": guest}


@app.post("/api/events/{event_id}/pledges/{pledge_id}/call/tool")
async def follow_up_tool(event_id: str, pledge_id: int, payload: VoiceToolRequest):
    call = call_row(event_id, pledge_id, payload.browser_call_id)
    details = call["details"]
    args = payload.arguments or {}
    tool = payload.tool

    if tool == "confirm_identity":
        is_correct = args.get("is_correct_person") is True
        details["identity_confirmed"] = is_correct
        outcome = "incomplete" if is_correct else "wrong_person"
        message = "Identity confirmed. You may now discuss the pledge." if is_correct else "Identity was not confirmed. End the call without discussing the pledge."
        database.execute("UPDATE calls SET outcome = ?, details_json = ? WHERE id = ?", (outcome, json.dumps(details), call["id"]))
        database.audit(event_id, "identity_checked", {"is_correct_person": is_correct}, pledge_id)
        return {"ok": True, "identity_confirmed": is_correct, "message": message}

    if tool == "send_payment_link":
        if not details.get("identity_confirmed"):
            return {"ok": False, "error": "Identity was not confirmed; no payment information was shared."}
        if not settings.paystack_secret_key:
            database.audit(event_id, "payment_link_unavailable", {"reason": "Paystack test mode is not configured"}, pledge_id)
            return {"ok": False, "error": "Paystack test mode is not configured, so no payment link was created."}
        pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
        guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (pledge.get("guest_id") if pledge else -1, event_id))
        if not pledge or not guest:
            return {"ok": False, "error": "This pledge no longer has a confirmed guest."}
        result = await create_payment_link(event_id, pledge, call, guest)
        if result.get("ok"):
            details["payment_link"] = result.get("payment_link")
            details["payment_reference"] = result.get("reference")
            details["payment_status"] = result.get("payment_status")
            database.execute("UPDATE calls SET details_json = ? WHERE id = ?", (json.dumps(details), call["id"]))
            await hub.publish(event_id, {"type": "payment", "pledge_id": pledge_id, "payment": result, "state": event_state(event_id)})
        return result

    if tool == "record_promise":
        if not details.get("identity_confirmed"):
            return {"ok": False, "error": "Identity was not confirmed; no promise was recorded."}
        promised_date = str(args.get("promised_date") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", promised_date):
            return {"ok": False, "error": "Please give a date in year-month-day form."}
        details["promised_date"] = promised_date
        database.execute("UPDATE calls SET outcome = ?, details_json = ? WHERE id = ?", ("promised", json.dumps(details), call["id"]))
        database.audit(event_id, "payment_promised", {"promised_date": promised_date}, pledge_id)
        return {"ok": True, "message": "The promised date was recorded."}

    if tool == "record_dispute":
        details["dispute"] = str(args.get("what_they_said") or "").strip()[:1000]
        database.execute("UPDATE calls SET outcome = ?, details_json = ? WHERE id = ?", ("disputed", json.dumps(details), call["id"]))
        database.audit(event_id, "payment_disputed", {"what_they_said": details["dispute"]}, pledge_id)
        return {"ok": True, "message": "The dispute was recorded for a human to review."}

    if tool == "record_opt_out":
        details["opted_out"] = True
        database.execute("UPDATE calls SET outcome = ?, details_json = ? WHERE id = ?", ("opted_out", json.dumps(details), call["id"]))
        database.audit(event_id, "follow_up_opted_out", {}, pledge_id)
        return {"ok": True, "message": "The opt-out was recorded."}

    if tool == "end_call":
        allowed = {"paid_link_sent", "promised", "disputed", "declined", "opted_out", "wrong_person", "incomplete"}
        outcome = str(args.get("outcome") or "incomplete")
        if outcome not in allowed:
            outcome = "incomplete"
        database.execute("UPDATE calls SET outcome = ?, details_json = ? WHERE id = ?", (outcome, json.dumps(details), call["id"]))
        database.audit(event_id, "follow_up_ended", {"outcome": outcome}, pledge_id)
        return {"ok": True, "message": "The call outcome was recorded."}

    return {"ok": False, "error": "That follow-up action is not available."}


@app.post("/api/paystack/webhook")
async def paystack_webhook(request: Request):
    """Accept Paystack events only after validating their raw-body signature."""

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not valid_webhook_signature(settings.paystack_secret_key, raw_body, signature):
        raise HTTPException(401, "The payment notification signature could not be verified.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "The payment notification was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "The payment notification was not an object.")
    if payload.get("event") != "charge.success":
        return {"ok": True, "ignored": True}
    data = payload.get("data") or {}
    reference = str(data.get("reference") or "").strip()
    payment = database.one("SELECT * FROM payments WHERE reference = ?", (reference,))
    if not payment:
        # A webhook can arrive before a local record is available after a
        # restart. Acknowledge unknown references without inventing a pledge.
        return {"ok": True, "ignored": True}
    if payment["status"] == "success":
        return {"ok": True, "duplicate": True, "reference": reference}
    try:
        result = await verify_and_redeem_payment(payment)
    except PaystackError as exc:
        database.audit(payment["event_id"], "payment_verification_failed", {"reference": reference, "error": str(exc)}, payment["pledge_id"])
        raise HTTPException(503, str(exc)) from exc
    await hub.publish(payment["event_id"], {"type": "payment", "pledge_id": payment["pledge_id"], "payment": {"reference": reference, **result}, "state": event_state(payment["event_id"])})
    return {"ok": True, "reference": reference, **result}


@app.post("/api/events/{event_id}/pledges/{pledge_id}/payment/verify")
async def verify_pledge_payment(event_id: str, pledge_id: int):
    """Manually verify the current checkout after a test payment completes."""

    event_or_404(event_id)
    payment = latest_payment(event_id, pledge_id)
    if not payment:
        raise HTTPException(404, "No payment link exists for this pledge.")
    if payment["status"] == "success":
        return {"ok": True, "duplicate": True, "payment": serialise_payment(payment), "state": event_state(event_id)}
    try:
        result = await verify_and_redeem_payment(payment)
    except PaystackError as exc:
        database.audit(event_id, "payment_verification_failed", {"reference": payment["reference"], "error": str(exc)}, pledge_id)
        raise HTTPException(502, str(exc)) from exc
    await hub.publish(event_id, {"type": "payment", "pledge_id": pledge_id, "payment": {"reference": payment["reference"], **result}, "state": event_state(event_id)})
    refreshed = database.one("SELECT * FROM payments WHERE id = ?", (payment["id"],))
    return {"ok": True, "payment": serialise_payment(refreshed), "verification": result, "state": event_state(event_id)}


@app.get("/api/events/{event_id}/export.csv")
async def export_csv(event_id: str):
    event_or_404(event_id)
    rows = database.all("SELECT * FROM pledges WHERE event_id = ? ORDER BY id", (event_id,))
    stream = io.StringIO()
    fields = ["id", "heard_name", "matched_name", "amount_minor", "currency", "item", "live_text", "recheck_text", "state", "reason", "created_at", "updated_at"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({field: row.get(field) for field in fields} for row in rows)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=pledgebook-{event_id}.csv"})


@app.exception_handler(RuntimeError)
async def runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"error": str(exc)})
