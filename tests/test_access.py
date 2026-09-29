from conftest import Client, new_account
from helpers import add_guest, add_pledge


def test_signed_out_visitor_cannot_read_an_event(owner, event):
    stranger = Client()
    for url in (f"/api/events/{event['id']}", f"/api/events/{event['id']}/export.csv",
                f"/api/events/{event['id']}/stream", f"/api/events/{event['id']}/activity"):
        assert stranger.get(url).status_code == 401


def test_member_of_another_organisation_sees_not_found(owner, event):
    other = new_account(organisation="Another Church")
    assert other.get(f"/api/events/{event['id']}").status_code == 404
    assert other.post(f"/api/events/{event['id']}/lifecycle", {"action": "start"}).status_code == 404


def test_writes_without_the_pledgebook_header_are_blocked(owner):
    response = owner.http.post("/api/events", json={"name": "Forged"})
    assert response.status_code == 403


def test_login_logout_and_wrong_password():
    client = new_account()
    assert client.get("/api/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/auth/login", {"email": client.email, "password": "wrong password!"}).status_code == 401
    assert client.post("/api/auth/login", {"email": client.email, "password": "correct horse battery"}).status_code == 200
    assert client.get("/api/me").json()["organisation"]["role"] == "owner"


def test_short_passwords_and_duplicate_emails_are_refused(owner):
    fresh = Client()
    body = {"name": "A", "email": "short@example.com", "password": "short", "organisation": "X"}
    assert fresh.post("/api/auth/signup", body).status_code == 400
    body = {"name": "A", "email": owner.email, "password": "long enough password", "organisation": "X"}
    assert fresh.post("/api/auth/signup", body).status_code == 409


def test_usher_invite_gives_review_access_without_contacts(owner, event):
    guest = add_guest(owner, event["id"], phone="08031234567", email="emeka@example.com")
    add_pledge(event["id"], guest, state="flagged", reason="Name unclear")
    invite = owner.post("/api/organisation/invites", {"role": "usher", "event_id": event["id"]}).json()
    assert "<svg" in invite["qr_svg"]
    token = invite["url"].rsplit("/", 1)[-1]
    usher = new_account(invite=token, name="Uche Usher")
    state = usher.get(f"/api/events/{event['id']}").json()
    assert state["role"] == "usher"
    assert "phone" not in state["guests"][0] and "email" not in state["guests"][0]
    assert "follow_up" not in state
    assert usher.get(f"/api/events/{event['id']}/export.csv").status_code == 403
    assert usher.post(f"/api/events/{event['id']}/lifecycle", {"action": "start"}).status_code == 403
    assert usher.post(f"/api/events/{event['id']}/guests", {"name": "Someone New"}).status_code == 403
    # The invitation cannot be used twice.
    assert Client().post("/api/auth/signup", {"name": "B", "email": "b@example.com", "password": "long enough password", "invite": token}).status_code == 410


def test_usher_is_scoped_to_the_invited_event(owner, event):
    other = owner.post("/api/events", {"name": "Private second event", "event_date": "2026-10-05"}).json()["event"]
    invite = owner.post("/api/organisation/invites", {"role": "usher", "event_id": event["id"]}).json()
    usher = new_account(invite=invite["url"].rsplit("/", 1)[-1], name="Scoped Usher")
    assert usher.get(f"/api/events/{event['id']}").status_code == 200
    assert usher.get(f"/api/events/{other['id']}").status_code == 404
    listed = usher.get("/api/events").json()
    assert [row["id"] for row in listed["events"]] == [event["id"]]
    assert listed["counts"]["active"] == 1


def test_only_owners_invite_admins(owner, event):
    admin_invite = owner.post("/api/organisation/invites", {"role": "admin"}).json()
    admin = new_account(invite=admin_invite["url"].rsplit("/", 1)[-1])
    assert admin.post("/api/organisation/invites", {"role": "admin"}).status_code == 403
    assert admin.post("/api/organisation/invites", {"role": "usher", "event_id": event["id"]}).status_code == 200
    assert admin.get("/api/organisation/staff").status_code == 403


def test_last_owner_cannot_be_removed(owner):
    me = owner.get("/api/me").json()["user"]
    assert owner.delete(f"/api/organisation/members/{me['id']}").status_code == 400


def test_api_docs_and_old_token_route_are_gone():
    client = Client()
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/voice-token").status_code == 404


def test_security_headers_are_sent():
    response = Client().get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
