from __future__ import annotations

import asyncio
from array import array
import csv
from datetime import date
import io
import json
from pathlib import Path
import re
import sys
import uuid
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .amounts import parse_amount
from .config import Settings
from .db import Database, now
from .extractor import TurnWindow, extract_turn
from .names import match_name
from .services import AssemblyAIError, open_realtime, paced_pcm16, sync_transcribe, voice_token


ROOT = Path(__file__).resolve().parents[1]
settings = Settings.load()
database = Database(settings.data_dir / "pledgebook.sqlite3")
app = FastAPI(title="Pledgebook", version="0.1.0")


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
        ("Chief", "Emeka Okonkwo"), ("Mrs", "Oluwaseun Adebayo"), ("", "Eseu Mommy"),
        ("Alhaji", "Ibrahim Musa"), ("Deaconess", "Ngozi Eze"), ("Engineer", "Tunde Bakare"),
        ("Dr", "Ifeomobi Nwachukwu"), ("Pastor", "Kelechi Amadi"), ("Brother", "Segun Ogunleye"),
        ("Mrs", "Aisha Bello"), ("", "Youth Fellowship"),
    ] + [("", f"Demo Guest {i:02d}") for i in range(1, 51)]
    return [{"title": title, "name": name, "phone": "", "email": "", "consent_to_contact": False, "group": ""}
            for title, name in names]


def event_or_404(event_id: str) -> dict:
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


def event_calls(event_id: str) -> list[dict]:
    result = []
    for row in database.all("SELECT * FROM calls WHERE event_id = ? ORDER BY id DESC", (event_id,)):
        try:
            details = json.loads(row["details_json"])
        except (TypeError, json.JSONDecodeError):
            details = {}
        result.append({"id": row["id"], "pledge_id": row["pledge_id"], "outcome": row["outcome"],
                       "promised_date": details.get("promised_date"), "dispute": details.get("dispute"),
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
    return {
        "event": event, "guests": guests, "pledges": pledges,
        "key_terms": keyterm_preview(event_id), "calls": event_calls(event_id),
        "totals": {"pledged": pledged, "confirmed": confirmed, "received": received,
                   "flags": sum(p["state"] == "flagged" for p in pledges),
                   "in_kind": sum(1 for p in pledges if p["item"])},
        "payments": {"configured": bool(settings.paystack_secret_key),
                      "message": "Paystack test mode is not configured yet." if not settings.paystack_secret_key else "Paystack test mode is configured."},
    }


@app.get("/healthz")
async def healthz():
    return {"ok": True, "assemblyai_configured": bool(settings.assemblyai_api_key),
            "paystack_configured": bool(settings.paystack_secret_key), "version": app.version}


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/static/{path:path}")
async def static_file(path: str):
    file = (ROOT / "web" / path).resolve()
    if ROOT / "web" not in file.parents or not file.is_file():
        raise HTTPException(404, "File was not found")
    return FileResponse(file)


@app.post("/api/events")
async def create_event(payload: EventCreate):
    event_id = uuid.uuid4().hex
    database.execute(
        "INSERT INTO events(id, name, organisation, event_date, target_minor, min_minor, max_minor, demo, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'setup', ?)",
        (event_id, payload.name.strip(), payload.organisation.strip(), payload.event_date,
         payload.target, payload.minimum, payload.maximum, int(payload.demo), now()),
    )
    if payload.demo:
        for guest in invented_guests():
            database.execute("INSERT INTO guests(event_id, title, name, phone, email, consent_to_contact, group_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (event_id, guest["title"], guest["name"], guest["phone"], guest["email"], int(guest["consent_to_contact"]), guest["group"], now()))
    database.audit(event_id, "event_created", {"demo": payload.demo, "invented_names": payload.demo})
    return event_state(event_id)


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
        database.execute("UPDATE pledges SET guest_id = ?, recheck_text = ?, amount_minor = ?, currency = ?, matched_name = ?, state = ?, reason = ?, updated_at = ? WHERE id = ?",
                         (current_guest, text, amount.minor if amount.minor is not None else pledge["amount_minor"], amount.currency or pledge["currency"], matched_name if current_guest else "", state, reason, now(), pledge_id))
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
            "live_text = ?, recheck_text = '', source_start_ms = ?, source_end_ms = ?, state = ?, reason = ?, updated_at = ? WHERE id = ?",
            (name_match.guest_id, name_turn.name or "", name_match.guest_name or "", amount.minor, amount.currency, amount.item,
             live_text, start_ms, end_ms, state, reason, now(), recent["id"]),
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
        "INSERT INTO pledges(event_id, guest_id, heard_name, matched_name, amount_minor, currency, item, live_text, source_start_ms, source_end_ms, state, reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, name_match.guest_id if name_match else None, name_turn.name or "", name_match.guest_name if name_match and name_match.guest_name else "",
         amount.minor, amount.currency, amount.item, live_text, start_ms, end_ms, state, reason, now(), now()),
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
    audio = bytearray()
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
            audio.extend(chunk)
            await aai.send(chunk)
        await asyncio.sleep(2)
        await aai.send(json.dumps({"type": "Terminate"}))
        await asyncio.wait_for(reader, 12)
    finally:
        if not reader.done():
            reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
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
    event_or_404(event_id)
    if not (file.filename or "").lower().endswith(".wav"):
        raise HTTPException(415, "Upload a WAV recording")
    raw = await file.read()
    upload_dir = settings.data_dir / "uploads" / event_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{uuid.uuid4().hex}.wav"
    path.write_bytes(raw)
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnframes() / wav.getframerate() > 120:
                path.unlink(missing_ok=True)
                raise HTTPException(413, "The uploaded recording is longer than the 120-second live clip limit.")
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
    event_or_404(event_id)
    try:
        aai, begin = await open_realtime(settings, event_keyterms(event_id))
    except Exception as exc:
        await browser.send_json({"type": "error", "message": str(exc)})
        await browser.close(code=1011)
        return
    await browser.send_json({"type": "connection", "status": "Listening", "begin": begin})
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
                audio.extend(chunk)
                await aai.send(chunk)
            elif message.get("text"):
                try:
                    command = json.loads(message["text"])
                except json.JSONDecodeError:
                    command = {}
                if command.get("type") == "stop":
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
    elif action == "guest":
        guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (payload.guest_id or -1, event_id))
        if not guest:
            raise HTTPException(400, "Choose a guest from this event")
        state = "confirmed"
        update = (state, "")
        database.execute("UPDATE pledges SET guest_id = ?, matched_name = ? WHERE id = ?", (guest["id"], guest["name"], pledge_id))
    elif action == "amount":
        if payload.amount is None:
            raise HTTPException(400, "Enter an amount")
        state = "confirmed"
        update = (state, "")
        database.execute("UPDATE pledges SET amount_minor = ? WHERE id = ?", (payload.amount, pledge_id))
    else:
        raise HTTPException(400, "Unknown review action")
    database.execute("UPDATE pledges SET state = ?, reason = ?, updated_at = ? WHERE id = ?", (*update, now(), pledge_id))
    database.audit(event_id, "usher_review", {"action": action, "reason": payload.reason}, pledge_id)
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


@app.post("/api/events/{event_id}/pledges/{pledge_id}/call/start")
async def start_follow_up_call(event_id: str, pledge_id: int, payload: VoiceCallStart):
    event = event_or_404(event_id)
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
        raise HTTPException(503, "Paystack transaction initialization is awaiting live verification; no payment link was created.")

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
