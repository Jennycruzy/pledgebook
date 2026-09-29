from app.core import database
from helpers import add_guest, add_pledge, pledge


def resolve(client, event_id, pledge_id, **body):
    return client.post(f"/api/events/{event_id}/pledges/{pledge_id}/resolve", body)


def test_fixing_the_amount_does_not_clear_an_unclear_name(owner, event):
    pledge_id = add_pledge(event["id"], None, amount=None, state="flagged", reason="Name and amount unclear")
    assert resolve(owner, event["id"], pledge_id, action="amount", amount=20_000).status_code == 200
    row = pledge(pledge_id)
    assert row["state"] == "flagged" and row["amount_minor"] == 20_000
    assert "guest" in row["reason"]


def test_choosing_the_guest_does_not_clear_an_unclear_amount(owner, event):
    guest = add_guest(owner, event["id"])
    pledge_id = add_pledge(event["id"], None, amount=None, state="flagged")
    resolve(owner, event["id"], pledge_id, action="guest", guest_id=guest["id"])
    row = pledge(pledge_id)
    assert row["state"] == "flagged" and row["guest_id"] == guest["id"]
    resolve(owner, event["id"], pledge_id, action="amount", amount=5_000)
    assert pledge(pledge_id)["state"] == "confirmed"


def test_walk_in_is_created_and_matched_in_one_step(owner, event):
    pledge_id = add_pledge(event["id"], None, state="flagged")
    state = resolve(owner, event["id"], pledge_id, action="walk_in", walk_in_name="Bisi Adewale", walk_in_title="Mrs").json()
    assert any(g["name"] == "Bisi Adewale" for g in state["guests"])
    assert pledge(pledge_id)["state"] == "confirmed"
    assert resolve(owner, event["id"], add_pledge(event["id"], None, state="flagged"), action="walk_in", walk_in_name="bisi adewale").status_code == 409


def test_replace_earlier_rejects_the_first_pledge(owner, event):
    guest = add_guest(owner, event["id"])
    first = add_pledge(event["id"], guest, amount=200_000, state="provisional")
    second = add_pledge(event["id"], guest, amount=250_000, state="flagged",
                        reason=f"This guest pledged a different amount moments ago (pledge #{first}). Is this a correction or a second pledge?")
    resolve(owner, event["id"], second, action="replace_earlier")
    assert pledge(first)["state"] == "rejected"
    assert pledge(second)["state"] == "confirmed"
    assert owner.get(f"/api/events/{event['id']}").json()["totals"]["pledged"] == 250_000


def test_rejecting_closes_the_pledge_page(owner, event):
    guest = add_guest(owner, event["id"])
    pledge_id = add_pledge(event["id"], guest)
    url = owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "copy"}).json()["url"]
    assert resolve(owner, event["id"], pledge_id, action="reject").status_code == 400
    resolve(owner, event["id"], pledge_id, action="reject", reason="Not a pledge")
    assert owner.get("/api/pay/" + url.rsplit("/", 1)[-1]).status_code == 410


def test_paid_pledges_cannot_be_rejected_or_cut_below_what_was_paid(owner, event):
    guest = add_guest(owner, event["id"])
    pledge_id = add_pledge(event["id"], guest, amount=10_000)
    database.execute("UPDATE pledges SET received_minor = 4000 WHERE id = ?", (pledge_id,))
    assert resolve(owner, event["id"], pledge_id, action="reject", reason="x").status_code == 409
    assert resolve(owner, event["id"], pledge_id, action="amount", amount=3000).status_code == 409


def test_usher_cannot_change_a_confirmed_pledge(owner, event):
    from conftest import new_account
    guest = add_guest(owner, event["id"])
    confirmed = add_pledge(event["id"], guest)
    token = owner.post("/api/organisation/invites", {"role": "usher", "event_id": event["id"]}).json()["url"].rsplit("/", 1)[-1]
    usher = new_account(invite=token)
    assert resolve(usher, event["id"], confirmed, action="amount", amount=1).status_code == 403
    flagged = add_pledge(event["id"], None, state="flagged")
    assert resolve(usher, event["id"], flagged, action="guest", guest_id=guest["id"]).status_code == 200
