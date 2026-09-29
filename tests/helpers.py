from app.core import database
from app.db import now


def add_guest(client, event_id, name="Chief Emeka Obi", **fields):
    body = {"name": name, "phone": fields.pop("phone", ""), "email": fields.pop("email", ""),
            "consent_to_contact": fields.pop("consent", True), **fields}
    response = client.post(f"/api/events/{event_id}/guests", body)
    assert response.status_code == 200, response.text
    return response.json()


def add_pledge(event_id, guest=None, amount=50_000, state="confirmed", reason="", **extra):
    return database.execute(
        "INSERT INTO pledges(event_id, guest_id, heard_name, matched_name, amount_minor, currency, live_text, state, reason, created_at, updated_at, capture_id) "
        "VALUES (?, ?, ?, ?, ?, 'NGN', ?, ?, ?, ?, ?, ?)",
        (event_id, guest["id"] if guest else None, guest["name"] if guest else "", guest["name"] if guest else "",
         amount, f"{guest['name'] if guest else 'Someone'} {amount}", state, reason, now(), now(), extra.get("capture_id")),
    )


def pledge(pledge_id):
    return database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,))
