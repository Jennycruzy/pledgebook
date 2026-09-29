import hashlib
import hmac
import json

import pytest

from app import followup
from app.core import database
from conftest import Client
from helpers import add_guest, add_pledge, pledge


@pytest.fixture
def paystack(monkeypatch):
    """A stand-in Paystack that records checkouts and answers verification."""

    state = {"checkouts": [], "status": "success"}

    async def initialize(settings, *, amount_naira, email, reference, metadata, callback_url=""):
        state["checkouts"].append({"amount": amount_naira, "email": email, "reference": reference, "callback": callback_url})
        return {"body": {"message": "ok"}, "data": {"reference": reference, "authorization_url": f"https://checkout.paystack.com/{reference}"},
                "amount_kobo": amount_naira * 100}

    async def verify(settings, reference):
        checkout = next(c for c in state["checkouts"] if c["reference"] == reference)
        return {"data": {"reference": reference, "status": state["status"], "amount": checkout["amount"] * 100, "currency": "NGN", "paid_at": "2026-10-01T10:00:00Z"}}

    monkeypatch.setattr(followup, "initialize_transaction", initialize)
    monkeypatch.setattr(followup, "verify_transaction", verify)
    return state


def open_page(owner, event, amount=50_000, email="guest@example.com"):
    guest = add_guest(owner, event["id"], email=email, phone="08031234567")
    pledge_id = add_pledge(event["id"], guest, amount=amount)
    result = owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "whatsapp"}).json()
    assert result["open"].startswith("https://wa.me/2348031234567?text=")
    return pledge_id, result["url"].rsplit("/", 1)[-1]


def test_guest_pays_in_parts_and_is_redeemed_once_fully_paid(owner, event, paystack):
    pledge_id, token = open_page(owner, event)
    guest = Client()
    page = guest.get(f"/api/pay/{token}").json()
    assert page["pledge"]["outstanding"] == 50_000 and page["payments"]["mode"] == "test"
    first = guest.post(f"/api/pay/{token}/checkout", {"amount": 20_000}).json()
    assert paystack["checkouts"][0]["callback"].endswith(f"/pay/{token}")
    assert guest.post(f"/api/pay/{token}/verify", {"reference": first["reference"]}).json()["redeemed"] is False
    assert pledge(pledge_id)["received_minor"] == 20_000 and pledge(pledge_id)["state"] == "confirmed"
    assert guest.post(f"/api/pay/{token}/checkout", {"amount": 40_000}).status_code == 400
    rest = guest.post(f"/api/pay/{token}/checkout", {}).json()
    assert guest.post(f"/api/pay/{token}/verify", {"reference": rest["reference"]}).json()["redeemed"] is True
    assert pledge(pledge_id)["state"] == "redeemed" and pledge(pledge_id)["received_minor"] == 50_000
    assert owner.get(f"/api/events/{event['id']}").json()["totals"]["received"] == 50_000


def test_the_same_payment_is_never_counted_twice(owner, event, paystack):
    pledge_id, token = open_page(owner, event)
    guest = Client()
    reference = guest.post(f"/api/pay/{token}/checkout", {"amount": 10_000}).json()["reference"]
    payment = database.one("SELECT * FROM payments WHERE reference = ?", (reference,))
    followup.credit_payment_to_pledge(payment, {}, {"label": "test"})
    followup.credit_payment_to_pledge(payment, {}, {"label": "test"})
    assert guest.post(f"/api/pay/{token}/verify", {"reference": reference}).json()["duplicate"] is True
    assert pledge(pledge_id)["received_minor"] == 10_000


def test_amount_corrected_after_checkout_is_not_marked_paid_by_the_old_amount(owner, event, paystack):
    pledge_id, token = open_page(owner, event, amount=50_000)
    guest = Client()
    old = guest.post(f"/api/pay/{token}/checkout", {}).json()["reference"]
    owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/resolve", {"action": "amount", "amount": 80_000})
    guest.post(f"/api/pay/{token}/verify", {"reference": old})
    row = pledge(pledge_id)
    assert row["received_minor"] == 50_000 and row["state"] == "confirmed"
    assert guest.get(f"/api/pay/{token}").json()["pledge"]["outstanding"] == 30_000


def test_guest_without_email_is_asked_for_one(owner, event, paystack):
    _, token = open_page(owner, event, email="")
    guest = Client()
    response = guest.post(f"/api/pay/{token}/checkout", {})
    assert response.status_code == 400 and "email" in response.json()["detail"]
    assert guest.post(f"/api/pay/{token}/checkout", {"email": "me@example.com"}).status_code == 200


def test_offline_payment_is_recorded_by_staff(owner, event):
    pledge_id, _ = open_page(owner, event, amount=30_000)
    result = owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/payments/offline", {"amount": 30_000, "method": "transfer"}).json()
    assert result["redeemed"] is True
    assert pledge(pledge_id)["state"] == "redeemed"


def test_guest_can_promise_dispute_or_stop(owner, event):
    pledge_id, token = open_page(owner, event)
    guest = Client()
    assert guest.post(f"/api/pay/{token}/promise", {"promised_date": "2000-01-01"}).status_code == 400
    assert guest.post(f"/api/pay/{token}/stop").status_code == 200
    assert pledge(pledge_id)["follow_up_stopped"] == 1
    assert owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "copy"}).status_code == 400
    assert guest.post(f"/api/pay/{token}/dispute", {"what_they_said": "I pledged 5,000 not 50,000"}).status_code == 200
    assert pledge(pledge_id)["state"] == "flagged"
    assert guest.get(f"/api/pay/{token}").status_code == 410


def test_follow_up_needs_consent(owner, event):
    guest = add_guest(owner, event["id"], name="No Consent", consent=False)
    pledge_id = add_pledge(event["id"], guest)
    assert owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "copy"}).status_code == 400


def test_email_delivery_says_when_email_is_not_configured(owner, event):
    pledge_id, _ = open_page(owner, event)
    assert owner.post(f"/api/events/{event['id']}/pledges/{pledge_id}/deliver", {"channel": "email"}).status_code == 409


def test_manual_call_log_requires_a_date_for_a_promise(owner, event):
    pledge_id, _ = open_page(owner, event)
    url = f"/api/events/{event['id']}/pledges/{pledge_id}/calls"
    assert owner.post(url, {"outcome": "promised"}).status_code == 400
    assert owner.post(url, {"outcome": "promised", "promised_date": "2026-11-01", "notes": "After salary"}).status_code == 200
    calls = owner.get(f"/api/events/{event['id']}").json()["follow_up"]["calls"]
    assert calls[0]["kind"] == "phone" and calls[0]["promised_date"] == "2026-11-01"


def test_webhook_rejects_bad_signatures_and_credits_good_ones(owner, event, paystack):
    pledge_id, token = open_page(owner, event, amount=15_000)
    reference = Client().post(f"/api/pay/{token}/checkout", {}).json()["reference"]
    body = json.dumps({"event": "charge.success", "data": {"reference": reference}}).encode()
    http = Client().http
    assert http.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": "bad"}).status_code == 401
    signature = hmac.new(b"sk_test_unit", body, hashlib.sha512).hexdigest()
    assert http.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": signature}).status_code == 200
    assert http.post("/api/paystack/webhook", content=body, headers={"x-paystack-signature": signature}).json()["duplicate"] is True
    assert pledge(pledge_id)["received_minor"] == 15_000


def test_assistant_is_only_reachable_through_a_valid_pledge_page(owner, event):
    assert Client().post("/api/pay/not-a-real-token/assistant").status_code == 404


def test_assistant_tools_refuse_before_identity_is_confirmed(owner, event, monkeypatch):
    async def fake_token(settings):
        return "short-lived"
    monkeypatch.setattr("app.services.voice_token", fake_token)
    _, token = open_page(owner, event)
    guest = Client()
    session = guest.post(f"/api/pay/{token}/assistant").json()
    url = f"/api/pay/{token}/assistant/{session['call_id']}/tool"
    refused = guest.post(url, {"session_id": session["session_id"], "tool": "record_promise", "arguments": {"promised_date": "2026-12-01"}}).json()
    assert refused["ok"] is False
    guest.post(url, {"session_id": session["session_id"], "tool": "confirm_identity", "arguments": {"is_correct_person": True}})
    assert guest.post(url, {"session_id": session["session_id"], "tool": "record_promise", "arguments": {"promised_date": "2026-12-01"}}).json()["ok"] is True
    assert guest.post(url, {"session_id": "wrong-session-id", "tool": "record_opt_out"}).status_code == 404
