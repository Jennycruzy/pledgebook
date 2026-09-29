"""From room audio to a checked pledge record.

Audio is appended to a file on disk while it streams, so a long event does
not grow in memory. Each pledge keeps an exact clip of its own words.
"""

from __future__ import annotations

import asyncio
from array import array
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import uuid
import wave

from .core import add_usage, database, event_keyterms, guests_for, hub, remaining_usage, serialise_pledge, settings
from .db import now
from .extractor import TurnWindow, extract_turn
from .names import match_name
from .services import open_realtime, paced_pcm16, sync_transcribe


BYTES_PER_SECOND = 16000 * 2
USAGE_STEP_SECONDS = 5

# Open listening sessions per event. Each has a lock so a listening-list
# update never interleaves with an audio frame, and an optional browser
# socket so pausing or ending the event can close it.
live_sessions: dict[str, dict[str, dict]] = {}


class CaptureAudio:
    """The raw PCM of one listening session, written to disk as it arrives."""

    def __init__(self, event_id: str):
        self.capture_id = uuid.uuid4().hex
        folder = settings.data_dir / "audio" / event_id
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"capture-{self.capture_id}.pcm"
        self.handle = self.path.open("wb")
        self.size = 0
        self.started_at = datetime.now(timezone.utc)

    def wall_time(self, offset_ms: int) -> str:
        """When a moment in this session's audio was spoken, as a UTC timestamp."""

        return (self.started_at + timedelta(milliseconds=max(0, offset_ms))).isoformat()

    @property
    def seconds(self) -> float:
        return self.size / BYTES_PER_SECOND

    def append(self, chunk: bytes) -> None:
        self.handle.write(chunk)
        self.size += len(chunk)

    def read(self, start_ms: int, end_ms: int) -> bytes:
        self.handle.flush()
        start = max(0, int(max(0, start_ms) * 32))
        end = min(self.size, int(max(start_ms + 80, end_ms) * 32))
        start -= start % 2
        if end <= start:
            return b""
        with self.path.open("rb") as reader:
            reader.seek(start)
            return reader.read(end - start)

    def close(self) -> None:
        try:
            self.handle.close()
        finally:
            self.path.unlink(missing_ok=True)


async def notify(event_id: str, kind: str = "changed", **extra) -> None:
    await hub.publish(event_id, {"type": kind, **extra})


async def update_live_listening_terms(event_id: str) -> int:
    """Apply the current guest list to every active Realtime session."""

    terms = event_keyterms(event_id)
    updated = 0
    for key, session in list(live_sessions.get(event_id, {}).items()):
        try:
            async with session["lock"]:
                await session["aai"].send(json.dumps({"type": "UpdateConfiguration", "keyterms_prompt": terms}))
            updated += 1
        except Exception:
            live_sessions.get(event_id, {}).pop(key, None)
    return updated


async def stop_live_captures(event_id: str, message: str) -> int:
    stopped = 0
    for session in list(live_sessions.get(event_id, {}).values()):
        session["stop"].set()
        browser = session.get("browser")
        if browser is not None:
            try:
                await browser.send_json({"type": "stopped", "message": message})
            except Exception:
                pass
        stopped += 1
    return stopped


def write_wav(path: Path, frames: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(frames)


def save_pledge_clip(event_id: str, pledge_id: int, audio: CaptureAudio, start_ms: int, end_ms: int) -> Path | None:
    data = audio.read(start_ms, end_ms)
    if not data:
        return None
    path = settings.data_dir / "audio" / event_id / f"pledge-{pledge_id}.wav"
    write_wav(path, data)
    return path


def make_safe_audio_clip(event_id: str, pledge_id: int, audio_path: Path, recheck, text: str, words: list[dict], guest_id: int | None) -> tuple[Path | None, str]:
    """Trim a confirmed pledge to its recheck word span only when it is private."""

    if not guest_id:
        return None, "Audio is not shown because this pledge has no confirmed guest."
    if not words or not audio_path.is_file():
        return None, "Audio is not shown because word timings were not returned."
    normal_text = re.sub(r"[^a-z]+", "", text.lower())
    heard_guests = [guest for guest in guests_for(event_id, include_removed=True)
                    if (name := re.sub(r"[^a-z]+", "", guest.get("name", "").lower())) and name in normal_text]
    if len(heard_guests) != 1 or int(heard_guests[0]["id"]) != int(guest_id):
        return None, "Audio is not shown because it included another guest's name."
    if not recheck.amount.is_clear or recheck.start_ms >= recheck.end_ms:
        return None, "Audio is not shown because the amount was not a single clear phrase."
    try:
        with wave.open(str(audio_path), "rb") as source:
            rate, frame_count = source.getframerate(), source.getnframes()
            if rate != 16000 or source.getnchannels() != 1 or source.getsampwidth() != 2:
                return None, "Audio is not shown because the stored clip has an unsupported format."
            start_frame = max(0, int((recheck.start_ms - 60) * rate / 1000))
            end_frame = min(frame_count, int((recheck.end_ms + 60) * rate / 1000))
            if end_frame <= start_frame:
                return None, "Audio is not shown because its word timings were empty."
            source.setpos(start_frame)
            frames = source.readframes(end_frame - start_frame)
        safe_path = settings.data_dir / "audio" / event_id / f"pledge-{pledge_id}-safe.wav"
        write_wav(safe_path, frames)
        return safe_path, "Audio contains only this guest's rechecked name and amount."
    except (OSError, wave.Error) as exc:
        return None, f"Audio is not shown because the clip could not be trimmed: {exc}"


async def confirm_pledge(event_id: str, pledge_id: int) -> None:
    """Recheck a pledge clip with Sync and reconcile it with the live reading."""

    pledge = database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
    if not pledge or not pledge.get("audio_path"):
        return
    try:
        response, elapsed_ms = await sync_transcribe(settings, Path(pledge["audio_path"]), event_keyterms(event_id))
        pledge = database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
        if not pledge or pledge["state"] in ("rejected", "redeemed"):
            return
        text = response.get("text") or ""
        words = response.get("words") or []
        recheck = extract_turn(text, words, guests_for(event_id))
        current_guest = pledge.get("guest_id")
        recheck_guest = recheck.name_match.guest_id if recheck.name_match else None
        amount = recheck.amount
        anonymous = pledge.get("heard_name") == "Anonymous donor"
        already_flagged = pledge["state"] == "flagged"
        reviewed = database.one("SELECT 1 FROM audit_log WHERE pledge_id = ? AND action = 'usher_review' LIMIT 1", (pledge_id,))
        if reviewed:
            await record_recheck_after_review(event_id, pledge, text, words, recheck, elapsed_ms)
            return
        if not amount.is_clear:
            state, reason = "flagged", amount.reason or "Amount unclear — please check the recording."
        elif bare_small_amount(amount, text):
            state, reason = "flagged", BARE_AMOUNT.format(amount=f"₦{amount.minor:,}")
        elif pledge.get("currency") and amount.currency and pledge["currency"] != amount.currency:
            state, reason = "flagged", "The recheck heard a different currency — please check."
        elif current_guest and recheck_guest and current_guest != recheck_guest:
            state, reason = "flagged", "The recheck heard a different guest — please check."
            current_guest = None
        elif anonymous or (recheck.name_match and recheck.name_match.kind == "anonymous"):
            state, reason = "confirmed", "Anonymous pledge — no follow-up."
            current_guest = None
            anonymous = True
        elif recheck.name_match and recheck.name_match.kind != "matched":
            state, reason = "flagged", recheck.name_match.reason or "The name needs a human check."
            current_guest = None
        elif not current_guest and recheck_guest is None:
            state, reason = "flagged", recheck.name_match.reason if recheck.name_match else "Name not on the guest list — please confirm."
        elif not current_guest:
            # The live reading had no guest but the recheck names one: the
            # two passes disagree about the person, so a person decides.
            state, reason = "flagged", f"The recheck heard {recheck.name_match.guest_name}. Please confirm the guest."
        elif already_flagged:
            # A live-stage flag (possible repeat, below minimum) is a question
            # for a person; a clean recheck does not answer it.
            state, reason = "flagged", pledge["reason"]
        elif pledge["amount_minor"] is not None and amount.minor != pledge["amount_minor"]:
            state, reason = "corrected", f"{pledge['amount_minor']:,} → {amount.minor:,} (rechecked)."
        else:
            state, reason = "confirmed", ""
        matched_name = recheck.name_match.guest_name if recheck.name_match and recheck.name_match.guest_name else pledge["matched_name"]
        safe_path, safe_reason = None, ""
        if state in {"confirmed", "corrected"} and current_guest and amount.is_clear:
            safe_path, safe_reason = make_safe_audio_clip(event_id, pledge_id, Path(pledge["audio_path"]), recheck, text, words, current_guest)
        database.execute(
            "UPDATE pledges SET guest_id = ?, recheck_text = ?, amount_minor = ?, currency = ?, matched_name = ?, state = ?, reason = ?, "
            "safe_audio_path = ?, safe_audio_reason = ?, recheck_amount_minor = ?, recheck_guest_id = ?, recheck_ms = ?, rechecked_at = ?, updated_at = ? WHERE id = ?",
            (current_guest, text, amount.minor if state in ("confirmed", "corrected") and amount.minor is not None else pledge["amount_minor"],
             amount.currency if state in ("confirmed", "corrected") and amount.currency else pledge["currency"],
             matched_name if current_guest else ("Anonymous donor" if anonymous and state == "confirmed" else ""),
             state, reason, str(safe_path) if safe_path else None, safe_reason, amount.minor, recheck_guest, elapsed_ms, now(), now(), pledge_id),
        )
        database.audit(event_id, "rechecked", {"text": text, "elapsed_ms": elapsed_ms, "state": state, "reason": reason}, pledge_id,
                       actor={"label": "AssemblyAI Sync"})
    except Exception as exc:
        database.execute("UPDATE pledges SET reason = ?, updated_at = ? WHERE id = ?", (f"Not rechecked — {exc}", now(), pledge_id))
        database.audit(event_id, "recheck_failed", {"error": str(exc)}, pledge_id)
    await notify(event_id, "pledge", pledge_id=pledge_id)


async def record_recheck_after_review(event_id: str, pledge: dict, text: str, words: list, recheck, elapsed_ms: float) -> None:
    """A person already decided this line. Keep their decision unless the recheck disagrees."""

    recheck_guest = recheck.name_match.guest_id if recheck.name_match else None
    amount = recheck.amount
    problems = []
    if recheck_guest and pledge["guest_id"] and recheck_guest != pledge["guest_id"]:
        problems.append(f"the recheck heard {recheck.name_match.guest_name}")
    if amount.minor is not None and pledge["amount_minor"] is not None and amount.minor != pledge["amount_minor"]:
        problems.append(f"the recheck heard {amount.minor:,}")
    state, reason = pledge["state"], pledge["reason"]
    if problems and state not in ("rejected", "redeemed"):
        state, reason = "flagged", "A person decided this line, but " + " and ".join(problems) + ". Please check again."
    database.execute(
        "UPDATE pledges SET recheck_text = ?, recheck_amount_minor = ?, recheck_guest_id = ?, recheck_ms = ?, rechecked_at = ?, state = ?, reason = ?, updated_at = ? WHERE id = ?",
        (text, amount.minor, recheck_guest, elapsed_ms, now(), state, reason, now(), pledge["id"]),
    )
    database.audit(event_id, "rechecked", {"text": text, "elapsed_ms": elapsed_ms, "state": state, "reason": reason, "after_review": True},
                   pledge["id"], actor={"label": "AssemblyAI Sync"})


SCALE_WORDS = re.compile(r"₦|naira|thousand|million|\d\s*k\b|\bk\b", re.IGNORECASE)
BARE_AMOUNT = "The amount was heard as {amount} with no naira, thousand or million. Please check the recording."


def bare_small_amount(amount, text: str) -> bool:
    """A small number said without naira or a scale ("250") is ambiguous at a launching."""

    return amount.minor is not None and not amount.item and amount.minor < 1000 and not SCALE_WORDS.search(text or "")


ADD_ON = re.compile(r"\b(?:add(?:ing)?|another|plus|extra|in addition)\b", re.IGNORECASE)
SPOKEN_CORRECTION = re.compile(r"\b(?:sorry|correction|rather|I mean)\s*[.!?]*$", re.IGNORECASE)
CORRECTION_GUARD_MS = 60_000
REPEAT_WINDOW_MS = 60000


async def create_live_pledge(event_id: str, capture: CaptureAudio, live_text: str, name_turn, amount_turn) -> int | None:
    event = database.one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not event:
        return None
    guests = guests_for(event_id)
    name_match = name_turn.name_match
    if name_match is None and name_turn.name:
        name_match = match_name(name_turn.name, guests)
    amount = amount_turn.amount
    state, reason = "provisional", ""
    if not amount.is_clear:
        state, reason = "flagged", amount.reason or "Amount unclear — please check."
    elif bare_small_amount(amount, amount_turn.text):
        state, reason = "flagged", BARE_AMOUNT.format(amount=f"₦{amount.minor:,}")
    elif not name_turn.name:
        state, reason = "flagged", "Name unclear — please confirm."
    elif name_match and name_match.kind == "anonymous":
        state, reason = "provisional", "Anonymous pledge — no follow-up."
    elif not name_match or name_match.guest_id is None:
        state, reason = "flagged", name_match.reason if name_match else "Name not on the guest list — please confirm."
    elif amount.minor is not None and event["min_minor"] and amount.minor < event["min_minor"]:
        state, reason = "flagged", "Amount is below this event's allowed minimum."
    elif amount.minor is not None and event["max_minor"] and amount.minor > event["max_minor"]:
        state, reason = "flagged", "Amount is above this event's allowed maximum."
    start_ms = min(name_turn.start_ms, amount_turn.start_ms)
    end_ms = max(name_turn.end_ms, amount_turn.end_ms)

    # A correction cue can cause Realtime to shift every later amount onto
    # the next donor, and its exact turn boundaries vary between identical
    # runs.  Enforce the safety boundary here, after extraction: the cue and
    # the short sequence following it require an usher, regardless of how the
    # speech service partitioned those turns.
    correction_here = bool(SPOKEN_CORRECTION.search(live_text))
    recent_corrections = database.all(
        "SELECT live_text, source_end_ms FROM pledges WHERE event_id = ? AND capture_id = ? "
        "AND source_end_ms IS NOT NULL AND source_end_ms >= ? ORDER BY id DESC",
        (event_id, capture.capture_id, max(0, start_ms - CORRECTION_GUARD_MS)),
    )
    correction_before = any(SPOKEN_CORRECTION.search(row["live_text"] or "") for row in recent_corrections)
    if correction_here or correction_before:
        state, reason = "flagged", "A spoken correction may have shifted the following amounts — please check this sequence."
    guest_id = name_match.guest_id if name_match and name_match.kind == "matched" else None
    recognised_from = recognised_at = None
    if guest_id:
        learned = database.one("SELECT learned_from_pledge_id, learned_at FROM guests WHERE id = ?", (guest_id,))
        if learned and learned.get("learned_from_pledge_id"):
            recognised_from, recognised_at = learned["learned_from_pledge_id"], learned.get("learned_at")

    # MCs often repeat an announcement. Timestamps restart with every
    # listening session, so only compare pledges from this same session.
    # An identical repeat within a minute is recorded in the audit log and
    # not counted twice. Anything else from the same guest becomes its own
    # line; if it could be a correction or a repeat, a person decides.
    if guest_id is not None and not ADD_ON.search(live_text):
        recent = database.one(
            "SELECT * FROM pledges WHERE event_id = ? AND guest_id = ? AND capture_id = ? AND state != 'rejected' "
            "ORDER BY id DESC LIMIT 1",
            (event_id, guest_id, capture.capture_id),
        )
        if recent and recent["source_start_ms"] is not None:
            gap = abs(start_ms - int(recent["source_start_ms"]))
            same = recent["amount_minor"] == amount.minor and recent["currency"] == amount.currency and recent["item"] == amount.item
            if same and gap <= REPEAT_WINDOW_MS:
                database.audit(event_id, "live_repeat_ignored", {"text": live_text, "repeated_pledge_id": recent["id"]}, recent["id"],
                               actor={"label": "AssemblyAI Realtime"})
                return None
            if state == "provisional":
                state = "flagged"
                reason = (f"Possible repeat of pledge #{recent['id']} — keep both or reject one." if same else
                          f"This guest pledged a different amount moments ago (pledge #{recent['id']}). Is this a correction or a second pledge?")

    pledge_id = database.execute(
        "INSERT INTO pledges(event_id, guest_id, heard_name, matched_name, amount_minor, currency, item, live_text, source_start_ms, source_end_ms, "
        "state, reason, recognised_from_pledge_id, recognised_at, capture_id, live_amount_minor, live_guest_id, spoken_end_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, guest_id, name_turn.name or "", name_match.guest_name if guest_id and name_match.guest_name else "",
         amount.minor, amount.currency, amount.item, live_text, start_ms, end_ms, state, reason, recognised_from, recognised_at,
         capture.capture_id, amount.minor, guest_id, capture.wall_time(end_ms), now(), now()),
    )
    # Realtime can occasionally emit an amount-only turn after omitting the
    # donor's preceding words.  Give Sync enough earlier context to recover
    # that name.  A recovered name still goes to a person because the two
    # passes disagreed; this only prevents the evidence from being needlessly
    # truncated to the amount.
    lookback_ms = 6000 if not name_turn.name else 500
    clip = save_pledge_clip(event_id, pledge_id, capture, start_ms - lookback_ms, end_ms + 500)
    if clip:
        database.execute("UPDATE pledges SET audio_path = ? WHERE id = ?", (str(clip), pledge_id))
    database.audit(event_id, "live_pledge", {"text": live_text, "state": state, "guest_id": guest_id}, pledge_id,
                   actor={"label": "AssemblyAI Realtime"})
    await notify(event_id, "pledge", pledge_id=pledge_id)
    if clip:
        asyncio.create_task(confirm_pledge(event_id, pledge_id))
    return pledge_id


async def handle_turn(event_id: str, capture: CaptureAudio, window: TurnWindow, seen: set, event: dict) -> str | None:
    """Turn a final Realtime turn into zero or one pledge. Returns a notice for the operator."""

    if event.get("type") != "Turn" or not event.get("end_of_turn"):
        return None
    turn = extract_turn(event.get("transcript") or "", event.get("words") or [], guests_for(event_id))
    name_turn, amount_turn, pairing_reason = window.add(turn)
    await record_unpaired(event_id, capture, window.take_unpaired())
    if not name_turn or not amount_turn:
        # An amount with no usable name stays visible for an usher; it must
        # never disappear silently.
        if pairing_reason and amount_turn:
            await create_live_pledge(event_id, capture, amount_turn.text, amount_turn, amount_turn)
        return pairing_reason
    key = (name_turn.start_ms, amount_turn.end_ms, f"{name_turn.name}|{amount_turn.text}")
    if key in seen:
        return None
    seen.add(key)
    combined = " ".join(dict.fromkeys(part for part in (name_turn.text, amount_turn.text) if part))
    await create_live_pledge(event_id, capture, combined, name_turn, amount_turn)
    return None


async def record_unpaired(event_id: str, capture: CaptureAudio, turns: list) -> None:
    """A name with no amount, or an amount with no name, becomes a line for a person."""

    for turn in turns:
        await create_live_pledge(event_id, capture, turn.text, turn, turn)


class ListeningSession:
    """One Realtime connection fed by a browser microphone or a WAV file."""

    def __init__(self, event_id: str, org_id: str, browser=None):
        self.event_id = event_id
        self.org_id = org_id
        self.browser = browser
        self.key = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.capture = CaptureAudio(event_id)
        self.window = TurnWindow()
        self.seen: set = set()
        self.billed_seconds = 0
        self.aai = None
        self.reader: asyncio.Task | None = None

    async def open(self) -> dict:
        self.aai, begin = await open_realtime(settings, event_keyterms(self.event_id))
        live_sessions.setdefault(self.event_id, {})[self.key] = {"aai": self.aai, "lock": self.lock, "stop": self.stop, "browser": self.browser}
        self.reader = asyncio.create_task(self._read())
        return begin

    async def _read(self) -> None:
        async for raw in self.aai:
            message = json.loads(raw)
            if self.browser is not None:
                await self.browser.send_json({"type": "realtime", "event": message})
            else:
                await hub.publish(self.event_id, {"type": "realtime", "event": message})
            notice = await handle_turn(self.event_id, self.capture, self.window, self.seen, message)
            if notice and self.browser is not None:
                await self.browser.send_json({"type": "notice", "message": notice})

    def allowance_left(self) -> bool:
        return remaining_usage(self.org_id, "audio_seconds") + self.billed_seconds - self.capture.seconds > 0

    async def send(self, chunk: bytes) -> None:
        self.capture.append(chunk)
        async with self.lock:
            await self.aai.send(chunk)
        whole = int(self.capture.seconds) // USAGE_STEP_SECONDS * USAGE_STEP_SECONDS
        if whole > self.billed_seconds:
            add_usage(self.org_id, "audio_seconds", whole - self.billed_seconds)
            self.billed_seconds = whole

    async def finish(self, wait_seconds: float = 10) -> None:
        """Ask Realtime to flush the last turn, then wait for it to arrive."""

        try:
            async with self.lock:
                await self.aai.send(json.dumps({"type": "Terminate"}))
            await asyncio.wait_for(asyncio.shield(self.reader), wait_seconds)
        except Exception:
            pass
        try:
            await record_unpaired(self.event_id, self.capture, self.window.flush())
        except Exception as exc:
            database.audit(self.event_id, "unpaired_lines_failed", {"error": str(exc)})

    async def close(self) -> None:
        remainder = int(round(self.capture.seconds)) - self.billed_seconds
        add_usage(self.org_id, "audio_seconds", remainder)
        live_sessions.get(self.event_id, {}).pop(self.key, None)
        if self.reader and not self.reader.done():
            self.reader.cancel()
        if self.reader:
            await asyncio.gather(self.reader, return_exceptions=True)
        if self.aai is not None:
            try:
                await self.aai.close()
            except Exception:
                pass
        self.capture.close()


async def process_uploaded_audio(event_id: str, org_id: str, audio_path: Path) -> None:
    """Run a real human WAV through the same live and confirming path."""

    session = ListeningSession(event_id, org_id)
    try:
        await session.open()
        async for chunk in paced_pcm16(audio_path):
            if session.stop.is_set():
                break
            if not session.allowance_left():
                raise RuntimeError("Your organisation has used today's listening allowance.")
            await session.send(chunk)
        await asyncio.sleep(2)
        await session.finish(12)
        database.audit(event_id, "audio_upload_finished", {"seconds": round(session.capture.seconds, 1)})
        await notify(event_id, "upload", status="finished")
    except Exception as exc:
        database.audit(event_id, "audio_upload_failed", {"error": str(exc)})
        await notify(event_id, "error", message=f"The recording could not be processed: {exc}")
    finally:
        await session.close()


def normalise_wav(path: Path) -> float:
    """Convert a real PCM16 WAV to the 16 kHz mono format Realtime expects. Returns seconds."""

    with wave.open(str(path), "rb") as wav:
        channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
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
    mono = array("h", ((int(samples[i]) + int(samples[i + 1])) // 2 for i in range(0, len(samples) - 1, 2))) if channels == 2 else samples
    if rate == 16000:
        output = mono
    else:
        output = array("h")
        for index in range(max(1, round(len(mono) * 16000 / rate))):
            source = index * rate / 16000
            left = min(len(mono) - 1, int(source))
            right = min(len(mono) - 1, left + 1)
            value = round(mono[left] + (mono[right] - mono[left]) * (source - left))
            output.append(max(-32768, min(32767, value)))
    temporary = path.with_suffix(".normalised.wav")
    write_wav(temporary, output.tobytes())
    temporary.replace(path)
    return len(output) / 16000
