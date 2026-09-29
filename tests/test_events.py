from app.core import apply_retention, database
from helpers import add_guest, add_pledge


def lifecycle(client, event_id, action):
    return client.post(f"/api/events/{event_id}/lifecycle", {"action": action})


def test_event_moves_through_its_whole_lifecycle(owner, event):
    event_id = event["id"]
    assert lifecycle(owner, event_id, "pause").status_code == 409
    assert lifecycle(owner, event_id, "start").json()["event"]["status"] == "live"
    assert lifecycle(owner, event_id, "pause").json()["event"]["status"] == "paused"
    assert lifecycle(owner, event_id, "resume").json()["event"]["status"] == "live"
    assert lifecycle(owner, event_id, "end").json()["event"]["status"] == "ended"
    assert lifecycle(owner, event_id, "reopen").json()["event"]["status"] == "paused"
    assert lifecycle(owner, event_id, "end").status_code == 200
    assert lifecycle(owner, event_id, "archive").json()["event"]["status"] == "archived"
    assert owner.post(f"/api/events/{event_id}/guests", {"name": "Late Guest"}).status_code == 409
    assert lifecycle(owner, event_id, "unarchive").json()["event"]["status"] == "ended"


def test_my_events_lists_by_status_and_search(owner, event):
    other = owner.post("/api/events", {"name": "Building fund dinner"}).json()["event"]
    lifecycle(owner, other["id"], "end")
    active = owner.get("/api/events?view=active").json()
    assert [e["id"] for e in active["events"]] == [event["id"]]
    assert active["counts"] == {"active": 1, "ended": 1, "archived": 0}
    assert owner.get("/api/events?view=ended&q=dinner").json()["events"][0]["id"] == other["id"]


def test_delete_needs_the_exact_name_and_an_ended_event(owner, event):
    lifecycle(owner, event["id"], "start")
    assert owner.post(f"/api/events/{event['id']}/delete", {"confirm_name": event["name"]}).status_code == 409
    lifecycle(owner, event["id"], "end")
    assert owner.post(f"/api/events/{event['id']}/delete", {"confirm_name": "wrong"}).status_code == 400
    assert owner.post(f"/api/events/{event['id']}/delete", {"confirm_name": event["name"]}).status_code == 200
    assert owner.get(f"/api/events/{event['id']}").status_code == 404


def test_listening_requires_a_live_event(owner, event):
    response = owner.post(f"/api/events/{event['id']}/upload", files={"file": ("a.wav", b"RIFF", "audio/wav")})
    assert response.status_code == 409


def test_sample_event_is_labelled_and_deleted_after_expiry(owner):
    sample = owner.post("/api/events/sample").json()["event"]
    assert sample["sample"] == 1 and sample["expires_at"]
    real = owner.post("/api/events", {"name": "Real"}).json()["event"]
    assert owner.post(f"/api/events/{real['id']}/sample-audio").status_code == 400
    database.execute("UPDATE events SET expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (sample["id"],))
    apply_retention()
    assert owner.get(f"/api/events/{sample['id']}").status_code == 404
    assert owner.get(f"/api/events/{real['id']}").status_code == 200


def test_retention_deletes_audio_of_long_ended_events(owner, event, tmp_path):
    from app.core import settings
    folder = settings.data_dir / "audio" / event["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pledge-1.wav").write_bytes(b"x")
    lifecycle(owner, event["id"], "end")
    database.execute("UPDATE events SET ended_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (event["id"],))
    apply_retention()
    assert not folder.exists()
    assert database.one("SELECT audio_purged_at FROM events WHERE id = ?", (event["id"],))["audio_purged_at"]


def test_totals_are_kept_per_currency(owner, event):
    guest = add_guest(owner, event["id"])
    add_pledge(event["id"], guest, amount=100_000)
    usd = add_pledge(event["id"], guest, amount=500)
    database.execute("UPDATE pledges SET currency = 'USD' WHERE id = ?", (usd,))
    totals = owner.get(f"/api/events/{event['id']}").json()["totals"]
    assert totals["pledged"] == 100_000
    assert totals["by_currency"]["USD"]["pledged"] == 500


def test_activity_names_the_person_who_acted(owner, event):
    add_guest(owner, event["id"])
    rows = owner.get(f"/api/events/{event['id']}/activity").json()["rows"]
    assert rows[0]["label"] == "Guest added"
    assert rows[0]["actor"] == "Ada Staff"
