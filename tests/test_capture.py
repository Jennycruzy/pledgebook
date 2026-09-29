import asyncio

from app import capture as capture_module
from app.capture import CaptureAudio, create_live_pledge
from app.core import database
from app.extractor import extract_turn
from helpers import add_guest


def turn(text, guests, start_ms):
    words = [{"text": word, "start": start_ms + i * 300, "end": start_ms + i * 300 + 250} for i, word in enumerate(text.split())]
    return extract_turn(text, words, guests)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def fake_session(event_id):
    audio = CaptureAudio(event_id)
    audio.append(b"\x00\x00" * 16000 * 30)
    return audio


def live(event_id, audio, text, start_ms, guests):
    heard = turn(text, guests, start_ms)
    return run(create_live_pledge(event_id, audio, text, heard, heard))


def test_audio_is_on_disk_and_removed_after_the_session(owner, event):
    audio = fake_session(event["id"])
    assert audio.path.stat().st_size == 16000 * 2 * 30
    assert len(audio.read(1000, 2000)) == 32000
    audio.close()
    assert not audio.path.exists()


def test_same_announcement_repeated_is_counted_once(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Chief Emeka Obi")
    guests = [guest]
    audio = fake_session(event["id"])
    first = live(event["id"], audio, "Chief Emeka Obi 250,000 naira", 1000, guests)
    again = live(event["id"], audio, "Chief Emeka Obi 250,000 naira", 9000, guests)
    assert first and again is None
    assert database.one("SELECT COUNT(*) AS n FROM pledges WHERE event_id = ?", (event["id"],))["n"] == 1
    audio.close()


def test_a_second_amount_from_the_same_guest_is_kept_and_flagged(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Chief Emeka Obi")
    audio = fake_session(event["id"])
    first = live(event["id"], audio, "Chief Emeka Obi 200,000 naira", 1000, [guest])
    second = live(event["id"], audio, "Chief Emeka Obi 250,000 naira", 12000, [guest])
    rows = {row["id"]: row for row in database.all("SELECT * FROM pledges WHERE event_id = ?", (event["id"],))}
    assert rows[first]["amount_minor"] == 200_000 and rows[first]["state"] == "provisional"
    assert rows[second]["state"] == "flagged" and f"#{first}" in rows[second]["reason"]
    audio.close()


def test_a_new_listening_session_is_not_compared_with_the_last_one(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Chief Emeka Obi")
    one, two = fake_session(event["id"]), fake_session(event["id"])
    live(event["id"], one, "Chief Emeka Obi 100,000 naira", 1000, [guest])
    second = live(event["id"], two, "Chief Emeka Obi 100,000 naira", 1000, [guest])
    assert second is not None
    assert database.one("SELECT state FROM pledges WHERE id = ?", (second,))["state"] == "provisional"
    one.close()
    two.close()


def test_every_pledge_keeps_an_evidence_clip(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Chief Emeka Obi")
    audio = fake_session(event["id"])
    pledge_id = live(event["id"], audio, "Chief Emeka Obi 50,000 naira", 2000, [guest])
    row = database.one("SELECT audio_path FROM pledges WHERE id = ?", (pledge_id,))
    assert row["audio_path"].endswith(f"pledge-{pledge_id}.wav")
    assert owner.get(f"/api/events/{event['id']}/pledges/{pledge_id}/audio").status_code == 200
    audio.close()
