import asyncio

from app import capture as capture_module
from app.capture import CaptureAudio, confirm_pledge, create_live_pledge
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


def test_amount_only_evidence_keeps_six_seconds_of_earlier_context(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    audio = fake_session(event["id"])
    heard = turn("₦60,000.", [], 10_000)
    pledge_id = run(create_live_pledge(event["id"], audio, heard.text, heard, heard))
    row = database.one("SELECT audio_path, state FROM pledges WHERE id = ?", (pledge_id,))
    import wave
    with wave.open(row["audio_path"], "rb") as clip:
        duration = clip.getnframes() / clip.getframerate()
    assert row["state"] == "flagged"
    assert duration >= 6.5
    audio.close()


def test_both_passes_and_timings_are_kept(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Chief Emeka Obi")
    audio = fake_session(event["id"])
    pledge_id = live(event["id"], audio, "Chief Emeka Obi 200,000 naira", 2000, [guest])

    async def fake_sync(settings, path, terms):
        words = [{"text": w, "start": 500 + i * 300, "end": 750 + i * 300} for i, w in enumerate("Chief Emeka Obi 250,000 naira".split())]
        return {"text": "Chief Emeka Obi 250,000 naira", "words": words}, 812.5

    monkeypatch.setattr(capture_module, "sync_transcribe", fake_sync)
    run(confirm_pledge(event["id"], pledge_id))
    row = database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
    assert row["live_amount_minor"] == 200_000 and row["live_guest_id"] == guest["id"]
    assert row["recheck_amount_minor"] == 250_000 and row["recheck_guest_id"] == guest["id"]
    assert row["state"] == "corrected" and row["amount_minor"] == 250_000
    assert row["recheck_ms"] == 812.5 and row["spoken_end_at"] and row["rechecked_at"]
    audio.close()


def _sync_hearing(text):
    async def fake_sync(settings, path, terms):
        return {"text": text, "words": [{"text": w, "start": 500 + i * 300, "end": 750 + i * 300} for i, w in enumerate(text.split())]}, 900.0
    return fake_sync


def test_a_late_recheck_does_not_undo_a_person_unless_it_disagrees(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    audio = fake_session(event["id"])
    walk_in = live(event["id"], audio, "Chief Nwachukwu Ezenwa 100,000 naira", 2000, [])
    resolved = owner.post(f"/api/events/{event['id']}/pledges/{walk_in}/resolve",
                          {"action": "walk_in", "walk_in_title": "Chief", "walk_in_name": "Nwachukwu Ezenwa"})
    assert resolved.status_code == 200
    monkeypatch.setattr(capture_module, "sync_transcribe", _sync_hearing("Chief Nwachukwu Ezenwa 100,000 naira"))
    run(confirm_pledge(event["id"], walk_in))
    row = database.one("SELECT * FROM pledges WHERE id = ?", (walk_in,))
    assert row["state"] == "confirmed" and row["recheck_amount_minor"] == 100_000
    monkeypatch.setattr(capture_module, "sync_transcribe", _sync_hearing("Chief Nwachukwu Ezenwa 10,000 naira"))
    run(confirm_pledge(event["id"], walk_in))
    row = database.one("SELECT * FROM pledges WHERE id = ?", (walk_in,))
    assert row["state"] == "flagged" and "10,000" in row["reason"]
    audio.close()


def test_a_bare_small_number_goes_to_a_person(owner, event, monkeypatch):
    # From the owner's recording: both passes heard "Engineer Tunde Bakare, 250."
    # where earlier runs heard N100,000. A bare 250 must not be confirmed.
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Tunde Bakare")
    audio = fake_session(event["id"])
    bare = live(event["id"], audio, "Engineer Tunde Bakare, 250.", 1000, [guest])
    row = database.one("SELECT state, reason FROM pledges WHERE id = ?", (bare,))
    assert row["state"] == "flagged" and "no naira" in row["reason"]
    fresh = fake_session(event["id"])
    clear = live(event["id"], fresh, "Engineer Tunde Bakare, 250 thousand naira.", 1000, [guest])
    assert database.one("SELECT state FROM pledges WHERE id = ?", (clear,))["state"] == "provisional"
    audio.close()
    fresh.close()


def test_a_flagged_recheck_never_overwrites_the_live_amount(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    guest = add_guest(owner, event["id"], name="Tunde Bakare")
    audio = fake_session(event["id"])
    pledge_id = live(event["id"], audio, "Engineer Tunde Bakare, 250,000 naira.", 1000, [guest])
    monkeypatch.setattr(capture_module, "sync_transcribe", _sync_hearing("Engineer Tunde Bakare, 250."))
    run(confirm_pledge(event["id"], pledge_id))
    row = database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
    assert row["state"] == "flagged" and row["amount_minor"] == 250_000 and row["recheck_amount_minor"] == 250
    audio.close()


def test_spoken_correction_guards_the_following_sequence(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    one = add_guest(owner, event["id"], name="Ibrahim Musa")
    two = add_guest(owner, event["id"], name="Tola Adeyemi")
    audio = fake_session(event["id"])

    corrected = live(event["id"], audio, "Alhaji Ibrahim Musa 50,000 naira, sorry.", 1000, [one, two])
    shifted = live(event["id"], audio, "Dr Tola Adeyemi 70,000 naira", 9000, [one, two])
    rows = {row["id"]: row for row in database.all("SELECT * FROM pledges WHERE event_id = ?", (event["id"],))}
    assert rows[corrected]["state"] == "flagged"
    assert rows[shifted]["state"] == "flagged"
    assert "shifted" in rows[shifted]["reason"]
    audio.close()


def test_spoken_correction_guard_expires_after_a_minute(owner, event, monkeypatch):
    monkeypatch.setattr(capture_module, "confirm_pledge", lambda *a: asyncio.sleep(0))
    one = add_guest(owner, event["id"], name="Ibrahim Musa")
    two = add_guest(owner, event["id"], name="Tola Adeyemi")
    audio = fake_session(event["id"])

    live(event["id"], audio, "Alhaji Ibrahim Musa 50,000 naira, sorry.", 1000, [one, two])
    later = live(event["id"], audio, "Dr Tola Adeyemi 70,000 naira", 70_000, [one, two])
    assert database.one("SELECT state FROM pledges WHERE id = ?", (later,))["state"] == "provisional"
    audio.close()
