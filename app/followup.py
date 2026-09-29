"""Private pledge pages, delivery records, call logs and payments.

Staff send a guest a private page by email, SMS or WhatsApp. The guest opens
it on their own device to hear the moment they pledged, pay all or part of
it, choose a date, raise a problem, or talk to the disclosed voice assistant.
Staff calls are made from their own phone and logged here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .auth import client_ip, limiter
from .core import (ACCEPTED_STATES, add_usage, auth, database, guest_label, organisation, parse_time, payment_page_url,
                   require_usage, safe_data_path, settings)
from .capture import notify
from .db import now
from .delivery import message_text, send_email, sms_uri, valid_phone, whatsapp_uri
from .payments import PaystackError, initialize_transaction, valid_webhook_signature, verify_transaction


router = APIRouter()
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ASSISTANT_SESSIONS_PER_LINK_PER_DAY = 3


def money_label(amount: int | None, currency: str | None) -> str:
    if (currency or "NGN") == "NGN":
        return f"₦{int(amount or 0):,}"
    return f"{currency} {int(amount or 0):,}"


def pledge_for_follow_up(event_id: str, pledge_id: int) -> tuple[dict, dict]:
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge:
        raise HTTPException(404, "Pledge was not found")
    if pledge["state"] not in ACCEPTED_STATES:
        raise HTTPException(400, "Only a confirmed pledge can be followed up.")
    guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (pledge.get("guest_id") or -1, event_id))
    if not guest:
        raise HTTPException(400, "This pledge has no confirmed guest.")
    if not guest["consent_to_contact"]:
        raise HTTPException(400, "Follow-up consent is not recorded for this guest.")
    if pledge.get("follow_up_stopped"):
        raise HTTPException(400, "This guest asked not to be contacted again about this pledge.")
    return pledge, guest


def active_link(pledge_id: int) -> dict | None:
    current = datetime.now(timezone.utc).isoformat()
    return database.one(
        "SELECT * FROM pledge_links WHERE pledge_id = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY id DESC LIMIT 1",
        (pledge_id, current),
    )


def ensure_link(event: dict, pledge: dict, actor: dict) -> dict:
    link = active_link(pledge["id"])
    if link:
        return link
    days = int(organisation(event["org_id"]).get("link_expiry_days") or 14)
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    link_id = database.execute(
        "INSERT INTO pledge_links(event_id, pledge_id, token, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event["id"], pledge["id"], token, actor.get("id"), now(), expires),
    )
    database.audit(event["id"], "pledge_page_created", {"expires_at": expires, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=actor)
    return database.one("SELECT * FROM pledge_links WHERE id = ?", (link_id,))


def revoke_links(event_id: str, pledge_id: int, reason: str, actor: dict | None = None) -> None:
    changed = database.update("UPDATE pledge_links SET revoked_at = ? WHERE pledge_id = ? AND revoked_at IS NULL", (now(), pledge_id))
    if changed:
        database.audit(event_id, "pledge_page_closed", {"reason": reason}, pledge_id, actor=actor)


class DeliverRequest(BaseModel):
    channel: str = Field(pattern="^(email|sms|whatsapp|copy)$")


@router.post("/api/events/{event_id}/pledges/{pledge_id}/deliver")
async def deliver_pledge_page(event_id: str, pledge_id: int, payload: DeliverRequest, request: Request):
    event, member = auth.require_event(request, event_id, "follow_up")
    pledge, guest = pledge_for_follow_up(event_id, pledge_id)
    link = ensure_link(event, pledge, member)
    url = payment_page_url(link["token"])
    amount = pledge["item"] or money_label(pledge["amount_minor"], pledge["currency"])
    org_name = organisation(event["org_id"]).get("name") or event["organisation"]
    text = message_text(guest_label(guest), event["organisation"] or org_name, event["name"], amount, url)
    channel = payload.channel
    result = {"ok": True, "url": url, "text": text, "channel": channel}
    recipient, status, detail = "", "prepared", ""
    if channel == "email":
        if not guest["email"]:
            raise HTTPException(400, "Add this guest's email address first.")
        if not settings.email_configured:
            raise HTTPException(409, "Email sending is not configured on this server. Use SMS, WhatsApp or copy the link.")
        require_usage(event["org_id"], "emails_sent")
        recipient = guest["email"]
        try:
            await send_email(settings, recipient, f"Your pledge at {event['name']}", text)
            status = "sent"
            add_usage(event["org_id"], "emails_sent", 1)
        except Exception as exc:
            status, detail = "failed", str(exc)[:300]
            result = {"ok": False, "error": f"The email could not be sent: {detail}", "url": url}
    elif channel in ("sms", "whatsapp"):
        if not valid_phone(guest["phone"]):
            raise HTTPException(400, "Add this guest's phone number first.")
        recipient = guest["phone"]
        result["open"] = sms_uri(recipient, text) if channel == "sms" else whatsapp_uri(recipient, text)
        detail = "Opened on the staff member's phone to send."
    else:
        status, detail = "copied", "Link copied by staff."
    database.execute(
        "INSERT INTO deliveries(event_id, pledge_id, link_id, channel, recipient, status, detail, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, pledge_id, link["id"], channel, recipient, status, detail, member["id"], now()),
    )
    database.audit(event_id, "pledge_page_delivery", {"channel": channel, "status": status, "guest_id": guest["id"]}, pledge_id, actor=member)
    await notify(event_id)
    return result


class ManualCall(BaseModel):
    outcome: str = Field(pattern="^(promised|paid|disputed|no_answer|wrong_number|left_message|opted_out|declined)$")
    promised_date: str = ""
    notes: str = Field(default="", max_length=1000)


@router.post("/api/events/{event_id}/pledges/{pledge_id}/calls")
async def log_manual_call(event_id: str, pledge_id: int, payload: ManualCall, request: Request):
    """Record a phone call a staff member made from their own phone."""

    event, member = auth.require_event(request, event_id, "follow_up")
    pledge, guest = pledge_for_follow_up(event_id, pledge_id)
    details = {"notes": payload.notes.strip(), "by": member["name"]}
    if payload.outcome == "promised":
        if not DATE_PATTERN.match(payload.promised_date):
            raise HTTPException(400, "Choose the date the guest plans to pay.")
        details["promised_date"] = payload.promised_date
    database.execute(
        "INSERT INTO calls(event_id, pledge_id, outcome, details_json, created_at, kind, created_by) VALUES (?, ?, ?, ?, ?, 'phone', ?)",
        (event_id, pledge_id, payload.outcome, json.dumps(details), now(), member["id"]),
    )
    if payload.outcome == "opted_out":
        database.execute("UPDATE pledges SET follow_up_stopped = 1 WHERE id = ?", (pledge_id,))
        revoke_links(event_id, pledge_id, "Guest asked not to be contacted", member)
    database.audit(event_id, "phone_call_logged", {"outcome": payload.outcome, "guest_id": guest["id"], **details}, pledge_id, actor=member)
    await notify(event_id)
    return {"ok": True}


class OfflinePayment(BaseModel):
    amount: int = Field(ge=1)
    method: str = Field(pattern="^(cash|transfer|cheque|pos|other)$")
    note: str = Field(default="", max_length=300)


@router.post("/api/events/{event_id}/pledges/{pledge_id}/payments/offline")
async def record_offline_payment(event_id: str, pledge_id: int, payload: OfflinePayment, request: Request):
    """Record money received outside Paystack, such as cash or a bank transfer."""

    event, member = auth.require_event(request, event_id, "follow_up")
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge or pledge["state"] not in ACCEPTED_STATES:
        raise HTTPException(400, "Only a confirmed pledge can receive payments.")
    if pledge["item"]:
        raise HTTPException(400, "This is an in-kind gift. Mark it received from the register instead.")
    outstanding = int(pledge["amount_minor"] or 0) - int(pledge.get("received_minor") or 0)
    if outstanding <= 0:
        raise HTTPException(409, "This pledge has already been paid in full.")
    if payload.amount > outstanding:
        raise HTTPException(400, f"Enter no more than the outstanding ₦{outstanding:,}.")
    reference = f"offline-{payload.method}-{uuid.uuid4().hex[:12]}"
    payment_id = database.execute(
        "INSERT INTO payments(event_id, pledge_id, reference, amount_kobo, email, authorization_url, status, paystack_status, payload_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, '', '', 'recording', ?, ?, ?, ?)",
        (event_id, pledge_id, reference, payload.amount * 100, payload.method,
         json.dumps({"method": payload.method, "note": payload.note.strip(), "recorded_by": member["name"], "paid_at": now()}), now(), now()),
    )
    payment = database.one("SELECT * FROM payments WHERE id = ?", (payment_id,))
    result = credit_payment_to_pledge(payment, json.loads(payment["payload_json"]), member)
    await notify(event_id, "payment", pledge_id=pledge_id)
    return {"ok": True, **result}


@router.post("/api/events/{event_id}/pledges/{pledge_id}/link/close")
async def close_pledge_page(event_id: str, pledge_id: int, request: Request):
    event, member = auth.require_event(request, event_id, "follow_up")
    revoke_links(event_id, pledge_id, "Closed by staff", member)
    await notify(event_id)
    return {"ok": True}


# ---------------------------------------------------------------- payments


def credit_payment_to_pledge(payment: dict, snapshot: dict, actor: dict) -> dict:
    """Mark a verified payment successful exactly once and add it to the pledge."""

    changed = database.update(
        "UPDATE payments SET status = 'success', paystack_status = 'success', payload_json = ?, updated_at = ? WHERE id = ? AND status != 'success'",
        (json.dumps(snapshot, ensure_ascii=False), now(), payment["id"]),
    )
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (payment["pledge_id"], payment["event_id"]))
    if not pledge:
        raise PaystackError("The payment is not linked to a pledge in this event.")
    if not changed:
        return {"redeemed": pledge["state"] == "redeemed", "status": "success", "duplicate": True}
    amount = int(payment["amount_kobo"]) // 100
    database.execute("UPDATE pledges SET received_minor = received_minor + ?, updated_at = ? WHERE id = ?", (amount, now(), pledge["id"]))
    pledge = database.one("SELECT * FROM pledges WHERE id = ?", (pledge["id"],))
    fully_paid = pledge["amount_minor"] is not None and pledge["received_minor"] >= pledge["amount_minor"]
    if fully_paid and pledge["state"] in ACCEPTED_STATES and pledge["state"] != "redeemed":
        database.execute("UPDATE pledges SET state = 'redeemed', reason = '', updated_at = ? WHERE id = ?", (now(), pledge["id"]))
    database.audit(payment["event_id"], "payment_received", {
        "reference": payment["reference"], "amount": amount, "received_total": pledge["received_minor"],
        "fully_paid": fully_paid, "guest_id": pledge.get("guest_id"),
    }, pledge["id"], actor=actor)
    return {"redeemed": fully_paid, "status": "success", "received": pledge["received_minor"]}


async def verify_payment(payment: dict, actor: dict) -> dict:
    result = await verify_transaction(settings, payment["reference"])
    data = result["data"]
    status = str(data.get("status") or "").lower()
    snapshot = {key: data.get(key) for key in ("reference", "status", "amount", "currency", "paid_at")}
    if data.get("reference") != payment["reference"]:
        raise PaystackError("Paystack returned a different payment reference.")
    if int(data.get("amount") or 0) != int(payment["amount_kobo"]):
        raise PaystackError("Paystack returned a different payment amount.")
    if str(data.get("currency") or "NGN").upper() != "NGN":
        raise PaystackError("Paystack returned a non-naira payment.")
    if status != "success":
        database.execute(
            "UPDATE payments SET status = CASE WHEN status = 'success' THEN status ELSE 'pending' END, paystack_status = ?, payload_json = ?, updated_at = ? WHERE id = ?",
            (status, json.dumps(snapshot, ensure_ascii=False), now(), payment["id"]),
        )
        return {"redeemed": False, "status": status}
    return credit_payment_to_pledge(payment, snapshot, actor)


@router.post("/api/paystack/webhook")
async def paystack_webhook(request: Request):
    """Accept Paystack events only after validating their raw-body signature."""

    raw_body = await request.body()
    if not valid_webhook_signature(settings.paystack_secret_key, raw_body, request.headers.get("x-paystack-signature")):
        raise HTTPException(401, "The payment notification signature could not be verified.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "The payment notification was not valid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("event") != "charge.success":
        return {"ok": True, "ignored": True}
    reference = str((payload.get("data") or {}).get("reference") or "").strip()
    payment = database.one("SELECT * FROM payments WHERE reference = ?", (reference,))
    if not payment:
        return {"ok": True, "ignored": True}
    try:
        result = await verify_payment(payment, {"label": "Paystack notification"})
    except PaystackError as exc:
        database.audit(payment["event_id"], "payment_verification_failed", {"reference": reference, "error": str(exc)}, payment["pledge_id"])
        raise HTTPException(503, str(exc)) from exc
    await notify(payment["event_id"], "payment", pledge_id=payment["pledge_id"])
    return {"ok": True, "reference": reference, **result}


@router.post("/api/events/{event_id}/pledges/{pledge_id}/payment/verify")
async def verify_pledge_payments(event_id: str, pledge_id: int, request: Request):
    """Ask Paystack again about every open checkout for this pledge."""

    event, member = auth.require_event(request, event_id, "follow_up")
    results = []
    for payment in database.all("SELECT * FROM payments WHERE event_id = ? AND pledge_id = ? AND status IN ('initialized', 'pending')", (event_id, pledge_id)):
        try:
            results.append({"reference": payment["reference"], **(await verify_payment(payment, member))})
        except PaystackError as exc:
            results.append({"reference": payment["reference"], "error": str(exc)})
    await notify(event_id, "payment", pledge_id=pledge_id)
    return {"ok": True, "results": results}


# ------------------------------------------------------ the guest's own page


def link_by_token(token: str) -> tuple[dict, dict, dict]:
    link = database.one("SELECT * FROM pledge_links WHERE token = ?", (token,))
    if not link:
        raise HTTPException(404, "This pledge page was not found.")
    if link["revoked_at"]:
        raise HTTPException(410, "This pledge page has been closed. Contact the organiser if you need a new one.")
    expiry = parse_time(link["expires_at"])
    if expiry and expiry <= datetime.now(timezone.utc):
        raise HTTPException(410, "This pledge page has expired. Contact the organiser for a new link.")
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (link["pledge_id"], link["event_id"]))
    event = database.one("SELECT * FROM events WHERE id = ?", (link["event_id"],))
    if not pledge or not event or pledge["state"] not in ACCEPTED_STATES:
        raise HTTPException(410, "This pledge is no longer open. Contact the organiser if you think this is wrong.")
    return link, pledge, event


GUEST_ACTOR = {"label": "Guest (private pledge page)"}


def page_limit(request: Request, token: str, bucket: str, limit: int, window: int) -> None:
    limiter.check(f"{client_ip(request)}|{token[:12]}", bucket, limit, window)


@router.get("/api/pay/{token}")
async def pledge_page_data(token: str, request: Request):
    page_limit(request, token, "page", 60, 60)
    link, pledge, event = link_by_token(token)
    if not link["opened_at"]:
        database.execute("UPDATE pledge_links SET opened_at = ? WHERE id = ?", (now(), link["id"]))
        database.audit(event["id"], "pledge_page_opened", {"guest_id": pledge.get("guest_id")}, pledge["id"], actor=GUEST_ACTOR)
    guest = database.one("SELECT * FROM guests WHERE id = ?", (pledge.get("guest_id") or -1,)) or {}
    amount = int(pledge["amount_minor"] or 0)
    received = int(pledge["received_minor"] or 0)
    calls = database.all("SELECT outcome, details_json FROM calls WHERE pledge_id = ? ORDER BY id DESC LIMIT 1", (pledge["id"],))
    promised = None
    if calls:
        promised = (json.loads(calls[0]["details_json"] or "{}") or {}).get("promised_date")
    return {
        "event": {"name": event["name"], "organisation": event["organisation"], "event_date": event["event_date"]},
        "guest": {"name": guest_label(guest) or pledge["matched_name"], "email_known": bool(guest.get("email"))},
        "pledge": {"amount": amount, "currency": pledge["currency"] or "NGN", "item": pledge["item"], "received": received,
                   "outstanding": max(0, amount - received), "state": pledge["state"],
                   "words": pledge["recheck_text"] or pledge["live_text"],
                   "audio": bool(safe_data_path(pledge.get("safe_audio_path"))),
                   "audio_reason": pledge["safe_audio_reason"] or "Audio is not shown because the exact words could not be separated safely.",
                   "promised_date": promised, "stopped": bool(pledge["follow_up_stopped"])},
        "payments": {"mode": settings.paystack_mode,
                     "available": settings.paystack_mode != "off" and (pledge["currency"] or "NGN") == "NGN" and not pledge["item"]},
        "assistant": {"available": bool(settings.assemblyai_api_key)},
        "expires_at": link["expires_at"],
    }


@router.get("/api/pay/{token}/audio")
async def pledge_page_audio(token: str, request: Request):
    page_limit(request, token, "audio", 30, 60)
    _, pledge, _ = link_by_token(token)
    path = safe_data_path(pledge.get("safe_audio_path"))
    if not path:
        raise HTTPException(404, "The pledge moment is not available.")
    return FileResponse(path, media_type="audio/wav")


class CheckoutRequest(BaseModel):
    amount: int | None = Field(default=None, ge=100)
    email: str = ""


async def start_checkout(token: str, link: dict, pledge: dict, event: dict, amount: int | None, email: str, actor: dict, call_id: int | None = None) -> dict:
    if settings.paystack_mode == "off":
        return {"ok": False, "error": "Online payment is not available for this event. Please contact the organiser."}
    if pledge["item"] or (pledge["currency"] or "NGN") != "NGN":
        return {"ok": False, "error": "This pledge cannot be paid online. Please contact the organiser."}
    outstanding = int(pledge["amount_minor"] or 0) - int(pledge["received_minor"] or 0)
    if outstanding <= 0:
        return {"ok": False, "error": "This pledge is already fully paid. Thank you."}
    amount = outstanding if amount is None else int(amount)
    if amount > outstanding:
        return {"ok": False, "error": f"The most you can pay now is {money_label(outstanding, 'NGN')}."}
    guest = database.one("SELECT * FROM guests WHERE id = ?", (pledge.get("guest_id") or -1,)) or {}
    email = (guest.get("email") or email or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"ok": False, "error": "Enter an email address for your payment receipt.", "needs_email": True}
    recent = datetime.now(timezone.utc) - timedelta(hours=6)
    for existing in database.all(
        "SELECT * FROM payments WHERE pledge_id = ? AND status IN ('initialized', 'pending') AND amount_kobo = ? ORDER BY id DESC",
        (pledge["id"], amount * 100),
    ):
        if (parse_time(existing["created_at"]) or recent) > recent:
            return {"ok": True, "checkout_url": existing["authorization_url"], "reference": existing["reference"], "reused": True}
    reference = f"pb-{event['id'][:10]}-{pledge['id']}-{uuid.uuid4().hex[:10]}"
    try:
        created = await initialize_transaction(
            settings, amount_naira=amount, email=email, reference=reference,
            metadata={"event_id": event["id"], "pledge_id": pledge["id"], "link_id": link["id"], "call_id": call_id, "product": "pledgebook"},
            callback_url=payment_page_url(token),
        )
    except PaystackError as exc:
        database.audit(event["id"], "payment_link_failed", {"error": str(exc)}, pledge["id"], actor=actor)
        return {"ok": False, "error": str(exc)}
    data = created["data"]
    database.execute(
        "INSERT INTO payments(event_id, pledge_id, reference, amount_kobo, email, authorization_url, link_id, status, paystack_status, payload_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'initialized', '', '{}', ?, ?)",
        (event["id"], pledge["id"], data["reference"], created["amount_kobo"], email, data["authorization_url"], link["id"], now(), now()),
    )
    database.audit(event["id"], "checkout_started", {"reference": data["reference"], "amount": amount, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=actor)
    await notify(event["id"], "payment", pledge_id=pledge["id"])
    return {"ok": True, "checkout_url": data["authorization_url"], "reference": data["reference"], "reused": False}


@router.post("/api/pay/{token}/checkout")
async def pledge_page_checkout(token: str, payload: CheckoutRequest, request: Request):
    page_limit(request, token, "checkout", 10, 600)
    link, pledge, event = link_by_token(token)
    result = await start_checkout(token, link, pledge, event, payload.amount, payload.email, GUEST_ACTOR)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result


class VerifyRequest(BaseModel):
    reference: str = Field(min_length=4, max_length=120)


@router.post("/api/pay/{token}/verify")
async def pledge_page_verify(token: str, payload: VerifyRequest, request: Request):
    page_limit(request, token, "verify", 20, 600)
    link, pledge, event = link_by_token(token)
    payment = database.one("SELECT * FROM payments WHERE reference = ? AND pledge_id = ?", (payload.reference, pledge["id"]))
    if not payment:
        raise HTTPException(404, "That payment was not found for this pledge.")
    if payment["status"] == "success":
        return {"ok": True, "status": "success", "duplicate": True}
    try:
        result = await verify_payment(payment, GUEST_ACTOR)
    except PaystackError as exc:
        raise HTTPException(502, str(exc)) from exc
    await notify(event["id"], "payment", pledge_id=pledge["id"])
    return {"ok": True, **result}


class PromiseRequest(BaseModel):
    promised_date: str


def record_guest_call(pledge: dict, event: dict, outcome: str, details: dict, kind: str = "page") -> None:
    database.execute(
        "INSERT INTO calls(event_id, pledge_id, outcome, details_json, created_at, kind) VALUES (?, ?, ?, ?, ?, ?)",
        (event["id"], pledge["id"], outcome, json.dumps(details), now(), kind),
    )


def valid_future_date(value: str) -> str:
    value = str(value or "").strip()
    try:
        chosen = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(400, "Choose a date in year-month-day form.") from exc
    if chosen < datetime.now(timezone.utc).date() or chosen > datetime.now(timezone.utc).date() + timedelta(days=366):
        raise HTTPException(400, "Choose a date within the next year.")
    return value


@router.post("/api/pay/{token}/promise")
async def pledge_page_promise(token: str, payload: PromiseRequest, request: Request):
    page_limit(request, token, "respond", 10, 600)
    _, pledge, event = link_by_token(token)
    date = valid_future_date(payload.promised_date)
    record_guest_call(pledge, event, "promised", {"promised_date": date})
    database.audit(event["id"], "payment_promised", {"promised_date": date, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=GUEST_ACTOR)
    await notify(event["id"])
    return {"ok": True}


class DisputeRequest(BaseModel):
    what_they_said: str = Field(min_length=3, max_length=1000)


@router.post("/api/pay/{token}/dispute")
async def pledge_page_dispute(token: str, payload: DisputeRequest, request: Request):
    page_limit(request, token, "respond", 10, 600)
    _, pledge, event = link_by_token(token)
    record_guest_call(pledge, event, "disputed", {"dispute": payload.what_they_said.strip()})
    database.execute("UPDATE pledges SET state = 'flagged', reason = ?, updated_at = ? WHERE id = ? AND state != 'redeemed'",
                     (f"Guest disputed this pledge: {payload.what_they_said.strip()[:300]}", now(), pledge["id"]))
    revoke_links(event["id"], pledge["id"], "Guest raised a problem", GUEST_ACTOR)
    database.audit(event["id"], "payment_disputed", {"what_they_said": payload.what_they_said.strip(), "guest_id": pledge.get("guest_id")}, pledge["id"], actor=GUEST_ACTOR)
    await notify(event["id"])
    return {"ok": True}


@router.post("/api/pay/{token}/stop")
async def pledge_page_stop(token: str, request: Request):
    page_limit(request, token, "respond", 10, 600)
    _, pledge, event = link_by_token(token)
    database.execute("UPDATE pledges SET follow_up_stopped = 1 WHERE id = ?", (pledge["id"],))
    record_guest_call(pledge, event, "opted_out", {})
    database.audit(event["id"], "follow_up_opted_out", {"guest_id": pledge.get("guest_id")}, pledge["id"], actor=GUEST_ACTOR)
    await notify(event["id"])
    return {"ok": True}


# ------------------------------------------------ the disclosed voice assistant


@router.post("/api/pay/{token}/assistant")
async def start_assistant(token: str, request: Request):
    """Issue a short-lived Voice Agent token for this guest's own device."""

    from .services import AssemblyAIError, voice_token

    page_limit(request, token, "assistant", 3, 3600)
    link, pledge, event = link_by_token(token)
    started_today = database.one(
        "SELECT COUNT(*) AS n FROM calls WHERE link_id = ? AND kind = 'assistant' AND created_at >= ?",
        (link["id"], datetime.now(timezone.utc).date().isoformat()),
    )["n"]
    if started_today >= ASSISTANT_SESSIONS_PER_LINK_PER_DAY:
        raise HTTPException(429, "The assistant has been used several times today on this page. Please use the buttons on the page instead.")
    require_usage(event["org_id"], "assistant_sessions")
    try:
        voice = await voice_token(settings)
    except AssemblyAIError as exc:
        raise HTTPException(503, "The assistant is unavailable right now. Please use the buttons on the page.") from exc
    add_usage(event["org_id"], "assistant_sessions", 1)
    session_id = secrets.token_urlsafe(16)
    call_id = database.execute(
        "INSERT INTO calls(event_id, pledge_id, outcome, details_json, created_at, kind, link_id) VALUES (?, ?, 'incomplete', ?, ?, 'assistant', ?)",
        (event["id"], pledge["id"], json.dumps({"session_id": session_id, "identity_confirmed": False}), now(), link["id"]),
    )
    database.audit(event["id"], "assistant_started", {"call_id": call_id, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=GUEST_ACTOR)
    guest = database.one("SELECT * FROM guests WHERE id = ?", (pledge.get("guest_id") or -1,)) or {}
    return {"token": voice, "call_id": call_id, "session_id": session_id,
            "guest_name": guest_label(guest) or pledge["matched_name"],
            "amount_label": pledge["item"] or money_label(int(pledge["amount_minor"] or 0) - int(pledge["received_minor"] or 0), pledge["currency"]),
            "event": {"name": event["name"], "organisation": event["organisation"], "event_date": event["event_date"]}}


class ToolRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=64)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)


@router.post("/api/pay/{token}/assistant/{call_id}/tool")
async def assistant_tool(token: str, call_id: int, payload: ToolRequest, request: Request):
    page_limit(request, token, "tool", 60, 600)
    link, pledge, event = link_by_token(token)
    call = database.one("SELECT * FROM calls WHERE id = ? AND link_id = ? AND kind = 'assistant'", (call_id, link["id"]))
    details = json.loads(call["details_json"]) if call else {}
    if not call or details.get("session_id") != payload.session_id:
        raise HTTPException(404, "This assistant session was not found.")
    args = payload.arguments or {}
    actor = {"label": "Voice assistant on the guest's device"}

    def save(outcome: str | None = None) -> None:
        database.execute("UPDATE calls SET outcome = COALESCE(?, outcome), details_json = ? WHERE id = ?", (outcome, json.dumps(details), call_id))

    tool = payload.tool
    if tool == "confirm_identity":
        confirmed = args.get("is_correct_person") is True
        details["identity_confirmed"] = confirmed
        save(None if confirmed else "wrong_person")
        database.audit(event["id"], "identity_checked", {"is_correct_person": confirmed}, pledge["id"], actor=actor)
        return {"ok": True, "identity_confirmed": confirmed,
                "message": "Identity confirmed. You may discuss the pledge." if confirmed else "Identity not confirmed. Apologise and end the conversation without discussing the pledge."}
    if tool == "end_call":
        allowed = {"checkout_opened", "promised", "disputed", "declined", "opted_out", "wrong_person", "incomplete"}
        outcome = str(args.get("outcome") or "incomplete")
        save(outcome if outcome in allowed else "incomplete")
        database.audit(event["id"], "assistant_ended", {"outcome": outcome}, pledge["id"], actor=actor)
        return {"ok": True}
    if not details.get("identity_confirmed"):
        return {"ok": False, "error": "Identity was not confirmed; nothing was recorded."}
    if tool == "open_checkout":
        result = await start_checkout(token, link, pledge, event, None, "", actor, call_id)
        if result.get("ok"):
            details["reference"] = result["reference"]
            save("checkout_opened")
            return {"ok": True, "message": "A payment button is now showing on the guest's screen.", "checkout_url": result["checkout_url"]}
        return {"ok": False, "error": result["error"]}
    if tool == "record_promise":
        try:
            date = valid_future_date(args.get("promised_date"))
        except HTTPException as exc:
            return {"ok": False, "error": exc.detail}
        details["promised_date"] = date
        save("promised")
        database.audit(event["id"], "payment_promised", {"promised_date": date, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=actor)
        await notify(event["id"])
        return {"ok": True, "message": "The promised date was recorded."}
    if tool == "record_dispute":
        said = str(args.get("what_they_said") or "").strip()[:1000]
        details["dispute"] = said
        save("disputed")
        database.execute("UPDATE pledges SET state = 'flagged', reason = ?, updated_at = ? WHERE id = ? AND state != 'redeemed'",
                         (f"Guest disputed this pledge: {said[:300]}", now(), pledge["id"]))
        database.audit(event["id"], "payment_disputed", {"what_they_said": said, "guest_id": pledge.get("guest_id")}, pledge["id"], actor=actor)
        await notify(event["id"])
        return {"ok": True, "message": "The concern was recorded for the organiser to review."}
    if tool == "record_opt_out":
        details["opted_out"] = True
        save("opted_out")
        database.execute("UPDATE pledges SET follow_up_stopped = 1 WHERE id = ?", (pledge["id"],))
        database.audit(event["id"], "follow_up_opted_out", {"guest_id": pledge.get("guest_id")}, pledge["id"], actor=actor)
        await notify(event["id"])
        return {"ok": True, "message": "The guest will not be contacted again about this pledge."}
    return {"ok": False, "error": "That action is not available."}
