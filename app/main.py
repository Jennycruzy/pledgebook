from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import csv
from datetime import date
import io
import json
from pathlib import Path
import re
import uuid

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import segno

from . import followup
from .auth import PERMISSIONS, SESSION_COOKIE, SESSION_DAYS, client_ip, limiter, validate_email
from .capture import ListeningSession, normalise_wav, process_uploaded_audio, stop_live_captures, update_live_listening_terms
from .core import (ACCEPTED_STATES, add_usage, apply_retention, auth, database, delete_event_data, event_state, guest_label,
                   guests_for, hub, organisation, require_usage, safe_data_path, settings, usage_limits,
                   usage_today)
from .db import now
from .delivery import phone_digits, valid_phone
from .names import normalize_name
from .sample import create_sample_event, sample_recording_available


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
UPLOAD_LIMIT_SECONDS = 120

async def cleanup_loop() -> None:
    while True:
        try:
            apply_retention()
        except Exception as exc:  # keep the loop alive; the next hour retries
            print(f"retention check failed: {exc}")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Pledgebook", version="0.2.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(followup.router)


CONTENT_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self' wss://agents.assemblyai.com; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def protect_requests(request: Request, call_next):
    # Browsers cannot add a custom header to a cross-site form post, so
    # requiring one on every write blocks cross-site request forgery.
    path = request.url.path
    if (request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/")
            and path != "/api/paystack/webhook" and request.headers.get("x-pledgebook") != "1"):
        return JSONResponse(status_code=403, content={"detail": "This request was blocked because it did not come from Pledgebook."})
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CONTENT_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=()")
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RuntimeError)
async def runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ------------------------------------------------------------------ pages


def page(name: str) -> FileResponse:
    return FileResponse(WEB / name, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.api_route("/", methods=["GET", "HEAD"])
async def index():
    return page("index.html")


@app.get("/pay/{token}")
async def pledge_page(token: str):
    return page("pay.html")


@app.get("/static/{path:path}")
async def static_file(path: str):
    file = (WEB / path).resolve()
    if WEB not in file.parents or not file.is_file():
        raise HTTPException(404, "File was not found")
    return FileResponse(file, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/healthz")
async def healthz():
    return {"ok": True, "assemblyai_configured": bool(settings.assemblyai_api_key),
            "payments": settings.paystack_mode, "email": settings.email_configured, "version": app.version}


# --------------------------------------------------------------- accounts


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=settings.secure_cookies, samesite="lax", path="/")


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    organisation: str = Field(default="", max_length=160)
    invite: str = Field(default="", max_length=200)


@app.post("/api/auth/signup")
async def signup(payload: SignupRequest, request: Request, response: Response):
    limiter.check(client_ip(request), "signup", 5, 3600)
    invite = auth.open_invite(payload.invite) if payload.invite else None
    if not invite and not payload.organisation.strip():
        raise HTTPException(400, "Enter your organisation's name.")
    user = auth.create_user(payload.email, payload.name, payload.password)
    if invite:
        auth.accept_invite(payload.invite, user)
        org_id = invite["org_id"]
    else:
        org_id = auth.create_organisation(payload.organisation, user["id"])
    token, _ = auth.start_session(user["id"], org_id)
    set_session_cookie(response, token)
    return {"ok": True, "event_id": invite["event_id"] if invite else None}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    invite: str = Field(default="", max_length=200)


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    limiter.check(client_ip(request), "login", 10, 900)
    limiter.check(payload.email.strip().lower(), "login-account", 10, 900)
    user = auth.authenticate(payload.email, payload.password)
    event_id, org_id = None, None
    if payload.invite:
        invite = auth.accept_invite(payload.invite, {"id": user["id"], "email": user["email"]})
        event_id, org_id = invite["event_id"], invite["org_id"]
    token, _ = auth.start_session(user["id"], org_id)
    set_session_cookie(response, token)
    return {"ok": True, "event_id": event_id}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    auth.end_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


def me_view(user: dict) -> dict:
    return {"user": {"id": user["id"], "name": user["name"], "email": user["email"]},
            "organisation": {"id": user["org_id"], "name": user["org_name"], "role": user["role"]} if user["org_id"] else None,
            "memberships": [{"id": m["org_id"], "name": m["name"], "role": m["role"]} for m in user["memberships"]],
            "permissions": sorted(PERMISSIONS.get(user["role"], set()))}


@app.get("/api/me")
async def me(request: Request):
    user = auth.user_from_request(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Sign in to continue."})
    return me_view(user)


class SwitchOrg(BaseModel):
    org_id: str


@app.post("/api/me/organisation")
async def switch_organisation(payload: SwitchOrg, request: Request):
    user = auth.require_user(request)
    if not any(m["org_id"] == payload.org_id for m in user["memberships"]):
        raise HTTPException(404, "Organisation was not found")
    auth.set_session_org(user["token"], payload.org_id)
    return me_view(auth.require_user(request))


@app.get("/api/invites/{token}")
async def invite_details(token: str, request: Request):
    limiter.check(client_ip(request), "invite", 30, 600)
    invite = auth.open_invite(token)
    return {"organisation": invite["org_name"], "role": invite["role"], "email": invite["email"]}


@app.post("/api/invites/{token}/accept")
async def accept_invite(token: str, request: Request):
    user = auth.require_user(request)
    invite = auth.accept_invite(token, user)
    auth.set_session_org(user["token"], invite["org_id"])
    return {"ok": True, "event_id": invite["event_id"]}


# ----------------------------------------------------------- organisation


class OrgUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    retention_days: int = Field(ge=7, le=3650)
    link_expiry_days: int = Field(ge=1, le=90)


def org_view(org_id: str) -> dict:
    org = organisation(org_id)
    return {
        "organisation": {key: org.get(key) for key in ("id", "name", "currency", "retention_days", "link_expiry_days", "created_at")},
        "payments": {"mode": settings.paystack_mode,
                     "webhook_url": f"{settings.public_url}/api/paystack/webhook" if settings.public_url else "/api/paystack/webhook"},
        "email": {"configured": settings.email_configured, "from": settings.smtp_from if settings.email_configured else ""},
        "usage": {"used": usage_today(org_id), "limits": usage_limits()},
    }


@app.get("/api/organisation")
async def get_organisation(request: Request):
    user = auth.require_org(request, "view")
    return org_view(user["org_id"])


@app.patch("/api/organisation")
async def update_organisation(payload: OrgUpdate, request: Request):
    user = auth.require_org(request, "settings")
    database.execute("UPDATE organisations SET name = ?, retention_days = ?, link_expiry_days = ? WHERE id = ?",
                     (payload.name.strip(), payload.retention_days, payload.link_expiry_days, user["org_id"]))
    return org_view(user["org_id"])


@app.get("/api/organisation/staff")
async def staff(request: Request):
    user = auth.require_org(request, "staff")
    members = database.all(
        "SELECT u.id, u.name, u.email, m.role, m.created_at FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY m.created_at",
        (user["org_id"],),
    )
    invites = database.all(
        "SELECT i.id, i.email, i.role, i.event_id, i.created_at, i.expires_at, e.name AS event_name FROM invites i "
        "LEFT JOIN events e ON e.id = i.event_id WHERE i.org_id = ? AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > ? ORDER BY i.id DESC",
        (user["org_id"], now()),
    )
    return {"members": members, "invites": invites}


class InviteRequest(BaseModel):
    role: str = Field(pattern="^(admin|usher)$")
    email: str = Field(default="", max_length=200)
    event_id: str = ""


def invite_url(token: str) -> str:
    return f"{settings.public_url}/#/invite/{token}" if settings.public_url else f"/#/invite/{token}"


def qr_svg(data: str) -> str:
    return segno.make(data, error="m").svg_inline(scale=5, border=2, dark="#17211b", light="#ffffff")


@app.post("/api/organisation/invites")
async def create_invite(payload: InviteRequest, request: Request):
    # Admins may invite ushers for an event they run; only owners invite admins.
    user = auth.require_org(request, "staff" if payload.role == "admin" else "run")
    email = validate_email(payload.email) if payload.email.strip() else ""
    event_id = None
    if payload.event_id:
        event, _ = auth.require_event(request, payload.event_id, "run")
        event_id = event["id"]
    token = auth.create_invite(user["org_id"], payload.role, email, user["id"], event_id)
    url = invite_url(token)
    emailed = False
    if email and settings.email_configured:
        from .delivery import send_email
        try:
            require_usage(user["org_id"], "emails_sent")
            await send_email(settings, email, f"Join {user['org_name']} on Pledgebook",
                             f"{user['name']} invited you to help as {payload.role} for {user['org_name']}.\n\nAccept here: {url}\n\nThis invitation expires in 7 days.")
            add_usage(user["org_id"], "emails_sent", 1)
            emailed = True
        except Exception:
            emailed = False
    if event_id:
        database.audit(event_id, "staff_invited", {"role": payload.role, "email": email}, actor=user)
    return {"url": url, "qr_svg": qr_svg(url), "emailed": emailed, "role": payload.role}


@app.delete("/api/organisation/invites/{invite_id}")
async def revoke_invite(invite_id: int, request: Request):
    user = auth.require_org(request, "run")
    changed = database.update("UPDATE invites SET revoked_at = ? WHERE id = ? AND org_id = ? AND accepted_at IS NULL",
                              (now(), invite_id, user["org_id"]))
    if not changed:
        raise HTTPException(404, "Invitation was not found")
    return {"ok": True}


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(owner|admin|usher)$")


def owner_count(org_id: str) -> int:
    return database.one("SELECT COUNT(*) AS n FROM memberships WHERE org_id = ? AND role = 'owner'", (org_id,))["n"]


@app.patch("/api/organisation/members/{user_id}")
async def change_role(user_id: int, payload: RoleUpdate, request: Request):
    user = auth.require_org(request, "staff")
    member = database.one("SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (user["org_id"], user_id))
    if not member:
        raise HTTPException(404, "Member was not found")
    if member["role"] == "owner" and payload.role != "owner" and owner_count(user["org_id"]) <= 1:
        raise HTTPException(400, "An organisation needs at least one owner.")
    database.execute("UPDATE memberships SET role = ? WHERE org_id = ? AND user_id = ?", (payload.role, user["org_id"], user_id))
    return {"ok": True}


@app.delete("/api/organisation/members/{user_id}")
async def remove_member(user_id: int, request: Request):
    user = auth.require_org(request, "staff")
    member = database.one("SELECT role FROM memberships WHERE org_id = ? AND user_id = ?", (user["org_id"], user_id))
    if not member:
        raise HTTPException(404, "Member was not found")
    if member["role"] == "owner" and owner_count(user["org_id"]) <= 1:
        raise HTTPException(400, "An organisation needs at least one owner.")
    database.execute("DELETE FROM memberships WHERE org_id = ? AND user_id = ?", (user["org_id"], user_id))
    database.execute("UPDATE sessions SET org_id = NULL WHERE user_id = ? AND org_id = ?", (user_id, user["org_id"]))
    return {"ok": True}


# ----------------------------------------------------------------- events


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    organisation: str = Field(default="", max_length=160)
    event_date: str = Field(default_factory=lambda: date.today().isoformat(), pattern=r"^\d{4}-\d{2}-\d{2}$")
    target: int = Field(default=0, ge=0)
    minimum: int = Field(default=0, ge=0)
    maximum: int = Field(default=0, ge=0)


def event_summary(event: dict) -> dict:
    totals = database.one(
        "SELECT COUNT(*) AS pledges, COALESCE(SUM(CASE WHEN state != 'rejected' AND item IS NULL AND COALESCE(currency, 'NGN') = 'NGN' THEN amount_minor END), 0) AS pledged, "
        "COALESCE(SUM(received_minor), 0) AS received, SUM(state = 'flagged') AS flags FROM pledges WHERE event_id = ?",
        (event["id"],),
    )
    guests = database.one("SELECT COUNT(*) AS n FROM guests WHERE event_id = ? AND removed_at IS NULL", (event["id"],))["n"]
    return {key: event.get(key) for key in ("id", "name", "organisation", "event_date", "status", "sample", "created_at", "ended_at", "archived_at", "expires_at", "target_minor")} | {
        "pledges": totals["pledges"], "pledged": totals["pledged"], "received": totals["received"], "flags": totals["flags"] or 0, "guests": guests}


@app.get("/api/events")
async def list_events(request: Request, view: str = "active", q: str = ""):
    user = auth.require_org(request, "view")
    filters = {"active": "status IN ('setup', 'live', 'paused')", "ended": "status = 'ended'", "archived": "status = 'archived'"}
    where = filters.get(view, filters["active"])
    params: list = [user["org_id"]]
    if q.strip():
        where += " AND (name LIKE ? OR organisation LIKE ?)"
        params += [f"%{q.strip()}%", f"%{q.strip()}%"]
    rows = database.all(f"SELECT * FROM events WHERE org_id = ? AND {where} ORDER BY event_date DESC, created_at DESC", tuple(params))
    counts = {key: database.one(f"SELECT COUNT(*) AS n FROM events WHERE org_id = ? AND {value}", (user["org_id"],))["n"] for key, value in filters.items()}
    return {"events": [event_summary(row) for row in rows], "counts": counts,
            "sample_recording": sample_recording_available()}


@app.post("/api/events")
async def create_event(payload: EventCreate, request: Request):
    user = auth.require_org(request, "run")
    require_usage(user["org_id"], "events_created")
    if payload.maximum and payload.minimum > payload.maximum:
        raise HTTPException(400, "The minimum cannot be above the maximum.")
    event_id = uuid.uuid4().hex
    database.execute(
        "INSERT INTO events(id, name, organisation, event_date, target_minor, min_minor, max_minor, demo, sample, status, created_at, org_id, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'setup', ?, ?, ?)",
        (event_id, payload.name.strip(), payload.organisation.strip() or user["org_name"], payload.event_date,
         payload.target, payload.minimum, payload.maximum, now(), user["org_id"], user["id"]),
    )
    add_usage(user["org_id"], "events_created", 1)
    database.audit(event_id, "event_created", {"name": payload.name.strip()}, actor=user)
    return event_state(event_id, user["role"])


@app.post("/api/events/sample")
async def create_sample(request: Request):
    user = auth.require_org(request, "run")
    require_usage(user["org_id"], "events_created")
    return event_state(create_sample_event(user["org_id"], user), user["role"])


@app.get("/api/events/{event_id}")
async def get_event(event_id: str, request: Request):
    event, member = auth.require_event(request, event_id, "view")
    return event_state(event_id, member["role"])


class EventUpdate(EventCreate):
    pass


@app.patch("/api/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdate, request: Request):
    event, member = auth.require_event(request, event_id, "run")
    database.execute(
        "UPDATE events SET name = ?, organisation = ?, event_date = ?, target_minor = ?, min_minor = ?, max_minor = ? WHERE id = ?",
        (payload.name.strip(), payload.organisation.strip() or event["organisation"], payload.event_date,
         payload.target, payload.minimum, payload.maximum, event_id),
    )
    database.audit(event_id, "event_details_changed", payload.model_dump(), actor=member)
    await hub.publish(event_id, {"type": "changed"})
    return event_state(event_id, member["role"])


# Allowed lifecycle moves: action -> (states it may start from, new state).
LIFECYCLE = {
    "start": (("setup",), "live"),
    "pause": (("live",), "paused"),
    "resume": (("paused",), "live"),
    "end": (("setup", "live", "paused"), "ended"),
    "reopen": (("ended",), "paused"),
    "archive": (("ended",), "archived"),
    "unarchive": (("archived",), "ended"),
}


class LifecycleRequest(BaseModel):
    action: str


@app.post("/api/events/{event_id}/lifecycle")
async def change_lifecycle(event_id: str, payload: LifecycleRequest, request: Request):
    event, member = auth.require_event(request, event_id, "run")
    if payload.action not in LIFECYCLE:
        raise HTTPException(400, "Unknown event action")
    allowed_from, target = LIFECYCLE[payload.action]
    if event["status"] not in allowed_from:
        raise HTTPException(409, f"An event that is {event['status']} cannot {payload.action}.")
    stamp = now()
    columns = {"start": "started_at = ?", "pause": "paused_at = ?", "resume": "paused_at = NULL, started_at = COALESCE(started_at, ?)",
               "end": "ended_at = ?", "reopen": "ended_at = NULL, paused_at = ?", "archive": "archived_at = ?", "unarchive": "archived_at = NULL, ended_at = COALESCE(ended_at, ?)"}
    changed = database.update(f"UPDATE events SET status = ?, {columns[payload.action]} WHERE id = ? AND status = ?",
                              (target, stamp, event_id, event["status"]))
    if not changed:
        raise HTTPException(409, "The event changed at the same time. Refresh and try again.")
    if target in ("paused", "ended"):
        await stop_live_captures(event_id, "The event was paused." if target == "paused" else "The event has ended.")
    database.audit(event_id, f"event_{payload.action}", {"from": event["status"], "to": target}, actor=member)
    await hub.publish(event_id, {"type": "changed"})
    return event_state(event_id, member["role"])


class DeleteRequest(BaseModel):
    confirm_name: str


@app.post("/api/events/{event_id}/delete")
async def delete_event(event_id: str, payload: DeleteRequest, request: Request):
    event, member = auth.require_event(request, event_id, "run")
    if payload.confirm_name.strip() != event["name"].strip():
        raise HTTPException(400, "Type the event name exactly to delete it.")
    if event["status"] == "live":
        raise HTTPException(409, "End the event before deleting it.")
    received = database.one("SELECT COALESCE(SUM(received_minor), 0) AS n FROM pledges WHERE event_id = ?", (event_id,))["n"]
    if received and member["role"] != "owner":
        raise HTTPException(403, "This event has received payments. Only an owner can delete it.")
    await stop_live_captures(event_id, "The event was deleted.")
    delete_event_data(event_id)
    return {"ok": True}


# ----------------------------------------------------------------- guests


class GuestFields(BaseModel):
    title: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=160)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=200)
    consent_to_contact: bool = False
    group: str = Field(default="", max_length=80)


def clean_guest(fields: dict) -> tuple[dict, list[str]]:
    guest = {
        "title": str(fields.get("title") or "").strip()[:40],
        "name": re.sub(r"\s+", " ", str(fields.get("name") or "")).strip()[:160],
        "phone": str(fields.get("phone") or "").strip()[:40],
        "email": str(fields.get("email") or "").strip().lower()[:200],
        "consent_to_contact": bool(fields.get("consent_to_contact")),
        "group": str(fields.get("group") or "").strip()[:80],
    }
    problems = []
    if not guest["name"]:
        problems.append("Name is missing.")
    if guest["phone"] and not valid_phone(guest["phone"]):
        problems.append("Phone number does not look right.")
    if guest["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", guest["email"]):
        problems.append("Email address does not look right.")
    return guest, problems


def duplicate_of(guest: dict, existing: list[dict], skip_id: int | None = None) -> dict | None:
    name = normalize_name(guest["name"])
    phone = phone_digits(guest["phone"]) if guest["phone"] else ""
    for other in existing:
        if skip_id is not None and other["id"] == skip_id:
            continue
        if name and normalize_name(other["name"]) == name:
            return other
        if phone and other.get("phone") and phone_digits(other["phone"]) == phone:
            return other
        if guest["email"] and other.get("email") and other["email"].lower() == guest["email"]:
            return other
    return None


def insert_guest(event_id: str, guest: dict) -> int:
    return database.execute(
        "INSERT INTO guests(event_id, title, name, phone, email, consent_to_contact, group_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, guest["title"], guest["name"], guest["phone"], guest["email"], int(guest["consent_to_contact"]), guest["group"], now(), now()),
    )


def editable(event: dict) -> None:
    if event["status"] == "archived":
        raise HTTPException(409, "Unarchive the event to change it.")


@app.post("/api/events/{event_id}/guests")
async def add_guest(event_id: str, payload: GuestFields, request: Request):
    event, member = auth.require_event(request, event_id, "guests")
    editable(event)
    guest, problems = clean_guest(payload.model_dump())
    if problems:
        raise HTTPException(400, " ".join(problems))
    duplicate = duplicate_of(guest, guests_for(event_id))
    if duplicate:
        raise HTTPException(409, f"{guest_label(duplicate)} is already on the guest list.")
    guest_id = insert_guest(event_id, guest)
    database.audit(event_id, "guest_added", {"guest_id": guest_id, "name": guest["name"], "consent_to_contact": guest["consent_to_contact"]}, actor=member)
    await update_live_listening_terms(event_id)
    await hub.publish(event_id, {"type": "changed"})
    return database.one("SELECT * FROM guests WHERE id = ?", (guest_id,))


@app.patch("/api/events/{event_id}/guests/{guest_id}")
async def edit_guest(event_id: str, guest_id: int, payload: GuestFields, request: Request):
    event, member = auth.require_event(request, event_id, "guests")
    editable(event)
    before = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ? AND removed_at IS NULL", (guest_id, event_id))
    if not before:
        raise HTTPException(404, "Guest was not found")
    guest, problems = clean_guest(payload.model_dump())
    if problems:
        raise HTTPException(400, " ".join(problems))
    duplicate = duplicate_of(guest, guests_for(event_id), skip_id=guest_id)
    if duplicate:
        raise HTTPException(409, f"{guest_label(duplicate)} already has that name, phone or email.")
    database.execute(
        "UPDATE guests SET title = ?, name = ?, phone = ?, email = ?, consent_to_contact = ?, group_name = ?, updated_at = ? WHERE id = ?",
        (guest["title"], guest["name"], guest["phone"], guest["email"], int(guest["consent_to_contact"]), guest["group"], now(), guest_id),
    )
    changes = {}
    for key, column in (("title", "title"), ("name", "name"), ("phone", "phone"), ("email", "email"), ("group", "group_name")):
        if (before[column] or "") != guest[key]:
            changes[key] = {"from": before[column], "to": guest[key]} if key not in ("phone", "email") else "changed"
    if bool(before["consent_to_contact"]) != guest["consent_to_contact"]:
        changes["consent_to_contact"] = guest["consent_to_contact"]
    if guest["name"] != before["name"]:
        database.execute("UPDATE pledges SET matched_name = ? WHERE guest_id = ?", (guest["name"], guest_id))
    if not guest["consent_to_contact"] and before["consent_to_contact"]:
        for pledge in database.all("SELECT id FROM pledges WHERE guest_id = ?", (guest_id,)):
            followup.revoke_links(event_id, pledge["id"], "Follow-up consent withdrawn", member)
    database.audit(event_id, "guest_edited", {"guest_id": guest_id, "changes": changes}, actor=member)
    await update_live_listening_terms(event_id)
    await hub.publish(event_id, {"type": "changed"})
    return database.one("SELECT * FROM guests WHERE id = ?", (guest_id,))


@app.delete("/api/events/{event_id}/guests/{guest_id}")
async def remove_guest(event_id: str, guest_id: int, request: Request):
    """Take a guest off the list. Pledges already made keep their name."""

    event, member = auth.require_event(request, event_id, "guests")
    editable(event)
    changed = database.update("UPDATE guests SET removed_at = ?, updated_at = ? WHERE id = ? AND event_id = ? AND removed_at IS NULL",
                              (now(), now(), guest_id, event_id))
    if not changed:
        raise HTTPException(404, "Guest was not found")
    database.audit(event_id, "guest_removed", {"guest_id": guest_id}, actor=member)
    await update_live_listening_terms(event_id)
    await hub.publish(event_id, {"type": "changed"})
    return {"ok": True}


@app.get("/api/events/{event_id}/guests/{guest_id}/history")
async def guest_history(event_id: str, guest_id: int, request: Request):
    auth.require_event(request, event_id, "guests")
    guest = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ?", (guest_id, event_id))
    if not guest:
        raise HTTPException(404, "Guest was not found")
    pledges = database.all("SELECT id, amount_minor AS amount, currency, item, state, received_minor AS received, created_at FROM pledges WHERE guest_id = ? ORDER BY id", (guest_id,))
    pledge_ids = [p["id"] for p in pledges]
    marks = ",".join("?" * len(pledge_ids)) or "NULL"
    rows = database.all(
        f"SELECT id, action, details_json, actor_label, pledge_id, created_at FROM audit_log WHERE event_id = ? AND (guest_id = ? OR pledge_id IN ({marks})) ORDER BY id DESC LIMIT 200",
        (event_id, guest_id, *pledge_ids),
    )
    return {"guest": guest, "pledges": pledges, "history": [activity_row(row) for row in rows]}


GUEST_COLUMNS = ("title", "name", "phone", "email", "consent_to_contact", "group")


def read_guest_csv(raw: bytes) -> list[dict]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "Save the CSV as UTF-8 and try again.") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    if "name" not in headers:
        raise HTTPException(400, "The CSV needs a 'name' column. Optional columns: title, phone, email, consent_to_contact, group.")
    rows = []
    for row in reader:
        row = {str(k).strip().lower(): (v or "") for k, v in row.items() if k}
        row["consent_to_contact"] = str(row.get("consent_to_contact") or "").strip().lower() in {"1", "true", "yes", "y"}
        rows.append({key: row.get(key, "") for key in GUEST_COLUMNS})
        if len(rows) > 5000:
            raise HTTPException(413, "Import up to 5,000 guests at a time.")
    return rows


def check_import(event_id: str, rows: list[dict]) -> list[dict]:
    existing = guests_for(event_id)
    accepted: list[dict] = []
    checked = []
    for number, fields in enumerate(rows, start=2):
        guest, problems = clean_guest(fields)
        status, message = "ok", ""
        if problems:
            status, message = "invalid", " ".join(problems)
        else:
            duplicate = duplicate_of(guest, existing) or duplicate_of(guest, [{**a, "id": -i - 1} for i, a in enumerate(accepted)])
            if duplicate:
                status, message = "duplicate", f"Matches {guest_label(duplicate)}."
            else:
                accepted.append({**guest, "phone": guest["phone"], "email": guest["email"]})
        checked.append({"row": number, **guest, "status": status, "message": message})
    return checked


@app.post("/api/events/{event_id}/guests/import/preview")
async def preview_import(event_id: str, request: Request, file: UploadFile = File(...)):
    event, _ = auth.require_event(request, event_id, "guests")
    editable(event)
    rows = check_import(event_id, read_guest_csv(await file.read()))
    return {"rows": rows, "counts": {status: sum(r["status"] == status for r in rows) for status in ("ok", "duplicate", "invalid")}}


class ImportRows(BaseModel):
    rows: list[dict] = Field(max_length=5000)


@app.post("/api/events/{event_id}/guests/import")
async def import_guests(event_id: str, payload: ImportRows, request: Request):
    event, member = auth.require_event(request, event_id, "guests")
    editable(event)
    checked = check_import(event_id, [{key: row.get(key, "") for key in GUEST_COLUMNS} for row in payload.rows])
    imported = 0
    for row in checked:
        if row["status"] == "ok":
            insert_guest(event_id, row)
            imported += 1
    skipped = len(checked) - imported
    database.audit(event_id, "guests_imported", {"imported": imported, "skipped": skipped}, actor=member)
    await update_live_listening_terms(event_id)
    await hub.publish(event_id, {"type": "changed"})
    return {"imported": imported, "skipped": skipped, "state": event_state(event_id, member["role"])}


# ----------------------------------------------------------------- review


class ResolveRequest(BaseModel):
    action: str
    guest_id: int | None = None
    amount: int | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=500)
    walk_in_name: str = Field(default="", max_length=160)
    walk_in_title: str = Field(default="", max_length=40)


def settle_after_review(pledge: dict) -> tuple[str, str]:
    """After a person fixes one thing, keep the line open if something else is still unclear."""

    anonymous = pledge["matched_name"] == "Anonymous donor"
    if not pledge["guest_id"] and not anonymous:
        return "flagged", "The guest still needs to be chosen."
    if pledge["amount_minor"] is None and not pledge["item"]:
        return "flagged", "The amount still needs to be entered."
    if int(pledge.get("received_minor") or 0) and pledge["amount_minor"] is not None and pledge["received_minor"] >= pledge["amount_minor"]:
        return "redeemed", ""
    return "confirmed", ("Anonymous pledge — no follow-up." if anonymous else "")


@app.post("/api/events/{event_id}/pledges/{pledge_id}/resolve")
async def resolve_pledge(event_id: str, pledge_id: int, payload: ResolveRequest, request: Request):
    event, member = auth.require_event(request, event_id, "review")
    editable(event)
    pledge = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    if not pledge:
        raise HTTPException(404, "Pledge was not found")
    # Ushers answer open questions; changing an accepted record is for event staff.
    if pledge["state"] != "flagged" and "run" not in PERMISSIONS[member["role"]]:
        raise HTTPException(403, "Only event staff can change a confirmed pledge.")
    action = payload.action
    details: dict = {"action": action}
    learned_guest = None
    if action == "reject":
        if not payload.reason.strip():
            raise HTTPException(400, "Give a reason for rejecting this line.")
        if int(pledge["received_minor"] or 0) > 0:
            raise HTTPException(409, "This pledge has received payments and cannot be rejected. Record a refund with the payment provider first.")
        database.execute("UPDATE pledges SET state = 'rejected', reason = ?, updated_at = ? WHERE id = ?", (payload.reason.strip(), now(), pledge_id))
        followup.revoke_links(event_id, pledge_id, "Pledge rejected", member)
        details["reason"] = payload.reason.strip()
    else:
        if action == "anonymous":
            database.execute("UPDATE pledges SET guest_id = NULL, matched_name = 'Anonymous donor' WHERE id = ?", (pledge_id,))
            followup.revoke_links(event_id, pledge_id, "Pledge made anonymous", member)
        elif action in ("guest", "walk_in"):
            if action == "walk_in":
                guest, problems = clean_guest({"title": payload.walk_in_title, "name": payload.walk_in_name})
                if problems:
                    raise HTTPException(400, " ".join(problems))
                duplicate = duplicate_of(guest, guests_for(event_id))
                if duplicate:
                    raise HTTPException(409, f"{guest_label(duplicate)} is already on the guest list. Choose them instead.")
                guest_id = insert_guest(event_id, guest)
                database.audit(event_id, "guest_added", {"guest_id": guest_id, "name": guest["name"], "walk_in": True}, pledge_id, actor=member)
            else:
                guest_id = payload.guest_id or -1
            chosen = database.one("SELECT * FROM guests WHERE id = ? AND event_id = ? AND removed_at IS NULL", (guest_id, event_id))
            if not chosen:
                raise HTTPException(400, "Choose a guest from this event.")
            if pledge["guest_id"] and pledge["guest_id"] != chosen["id"]:
                followup.revoke_links(event_id, pledge_id, "Pledge moved to another guest", member)
            database.execute("UPDATE pledges SET guest_id = ?, matched_name = ? WHERE id = ?", (chosen["id"], chosen["name"], pledge_id))
            database.execute("UPDATE guests SET learned_from_pledge_id = ?, learned_at = ? WHERE id = ?", (pledge_id, now(), chosen["id"]))
            learned_guest = chosen["id"]
            details["guest_id"] = chosen["id"]
        elif action == "amount":
            if payload.amount is None or payload.amount <= 0:
                raise HTTPException(400, "Enter the amount the recording clearly says.")
            if payload.amount < int(pledge["received_minor"] or 0):
                raise HTTPException(409, "The amount cannot be less than what has already been paid.")
            database.execute("UPDATE pledges SET amount_minor = ?, item = NULL WHERE id = ?", (payload.amount, pledge_id))
            details.update({"from": pledge["amount_minor"], "to": payload.amount})
        elif action == "keep":
            details["note"] = "Kept as a separate pledge."
        elif action == "replace_earlier":
            match = re.search(r"pledge #(\d+)", pledge["reason"] or "")
            earlier = database.one("SELECT * FROM pledges WHERE id = ? AND event_id = ?", (int(match.group(1)) if match else -1, event_id))
            if not earlier:
                raise HTTPException(400, "The earlier pledge was not found.")
            if int(earlier["received_minor"] or 0) > 0:
                raise HTTPException(409, "The earlier pledge has payments. Correct its amount instead.")
            database.execute("UPDATE pledges SET state = 'rejected', reason = ?, updated_at = ? WHERE id = ?",
                             (f"Replaced by the correction in pledge #{pledge_id}.", now(), earlier["id"]))
            followup.revoke_links(event_id, earlier["id"], "Replaced by a correction", member)
            database.audit(event_id, "usher_review", {"action": "replaced_by_correction", "by_pledge_id": pledge_id}, earlier["id"], actor=member)
            details["replaced_pledge_id"] = earlier["id"]
        else:
            raise HTTPException(400, "Unknown review action")
        state, reason = settle_after_review(database.one("SELECT * FROM pledges WHERE id = ?", (pledge_id,)))
        database.execute("UPDATE pledges SET state = ?, reason = ?, updated_at = ? WHERE id = ?", (state, reason, now(), pledge_id))
        details["state"] = state
    if learned_guest:
        updated = await update_live_listening_terms(event_id)
        database.audit(event_id, "listening_list_updated", {"guest_id": learned_guest, "active_sessions_updated": updated}, pledge_id, actor=member)
    database.audit(event_id, "usher_review", details, pledge_id, actor=member)
    await hub.publish(event_id, {"type": "pledge", "pledge_id": pledge_id})
    return event_state(event_id, member["role"])


# ------------------------------------------------------------- listening


def require_live(event: dict) -> None:
    if event["status"] != "live":
        raise HTTPException(409, "Go live before listening. A paused or ended event does not record.")


@app.post("/api/events/{event_id}/upload")
async def upload_audio(event_id: str, request: Request, file: UploadFile = File(...)):
    event, member = auth.require_event(request, event_id, "run")
    require_live(event)
    if not (file.filename or "").lower().endswith(".wav"):
        raise HTTPException(415, "Upload a WAV recording")
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "The recording is larger than 25 MB.")
    folder = settings.data_dir / "uploads" / event_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.wav"
    path.write_bytes(raw)
    return await queue_recording(event, member, path, file.filename or "recording.wav")


async def queue_recording(event: dict, member: dict, path: Path, label: str) -> dict:
    try:
        seconds = normalise_wav(path)
    except (ValueError, EOFError, Exception) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(415, f"The recording could not be read: {exc}") from exc
    if seconds > UPLOAD_LIMIT_SECONDS:
        path.unlink(missing_ok=True)
        raise HTTPException(413, f"Upload recordings of up to {UPLOAD_LIMIT_SECONDS} seconds.")
    try:
        require_usage(event["org_id"], "audio_seconds", int(seconds) + 1)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    database.audit(event["id"], "audio_upload_started", {"file": label, "seconds": round(seconds, 1)}, actor=member)
    asyncio.create_task(process_uploaded_audio(event["id"], event["org_id"], path))
    return {"accepted": True, "message": "The recording is being heard now. Watch the pledge list for updates."}


@app.post("/api/events/{event_id}/sample-audio")
async def process_sample_audio(event_id: str, request: Request):
    event, member = auth.require_event(request, event_id, "run")
    if not event.get("sample"):
        raise HTTPException(400, "The sample recording can only be used in a sample event.")
    require_live(event)
    if not sample_recording_available():
        raise HTTPException(404, "The sample recording is not configured on this server.")
    folder = settings.data_dir / "uploads" / event_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"sample-{uuid.uuid4().hex}.wav"
    path.write_bytes(settings.sample_audio_path.read_bytes())
    return await queue_recording(event, member, path, "sample recording")


def origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin") or ""
    host = websocket.headers.get("host") or ""
    allowed = {f"https://{host}", f"http://{host}"}
    if settings.public_url:
        allowed.add(settings.public_url)
    return origin in allowed


@app.websocket("/ws/events/{event_id}/capture")
async def capture(event_id: str, browser: WebSocket):
    await browser.accept()
    try:
        if not origin_allowed(browser):
            raise HTTPException(403, "This connection did not come from Pledgebook.")
        event, member = auth.require_event(browser, event_id, "run")
        require_live(event)
        if remaining_audio(event["org_id"]) <= 0:
            raise HTTPException(429, "Your organisation has used today's listening allowance.")
    except HTTPException as exc:
        await browser.send_json({"type": "error", "message": exc.detail})
        await browser.close(code=1008)
        return
    session = ListeningSession(event_id, event["org_id"], browser)
    try:
        begin = await session.open()
    except Exception as exc:
        session.capture.close()
        await browser.send_json({"type": "error", "message": str(exc)})
        await browser.close(code=1011)
        return
    database.audit(event_id, "listening_started", {}, actor=member)
    await browser.send_json({"type": "connection", "status": "Listening", "begin": begin})
    stopper = asyncio.create_task(session.stop.wait())
    try:
        while True:
            receiver = asyncio.create_task(browser.receive())
            done, _ = await asyncio.wait({receiver, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                receiver.cancel()
                await session.finish()
                break
            message = receiver.result()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if not session.allowance_left():
                    await browser.send_json({"type": "stopped", "message": "Your organisation has used today's listening allowance."})
                    await session.finish()
                    break
                await session.send(message["bytes"])
            elif message.get("text"):
                try:
                    command = json.loads(message["text"])
                except json.JSONDecodeError:
                    command = {}
                if command.get("type") == "stop":
                    # Termination flushes the last unfinished turn; wait for
                    # it or the final pledge would vanish at the button press.
                    await session.finish()
                    break
    except Exception:
        # A closed browser or service connection ends the session; the
        # finally block below records it and releases everything.
        pass
    finally:
        stopper.cancel()
        database.audit(event_id, "listening_stopped", {"seconds": round(session.capture.seconds, 1)}, actor=member)
        await session.close()
        try:
            await browser.close()
        except Exception:
            pass


def remaining_audio(org_id: str) -> int:
    return usage_limits()["audio_seconds"] - int(usage_today(org_id).get("audio_seconds") or 0)


@app.get("/api/events/{event_id}/stream")
async def stream_updates(event_id: str, request: Request):
    event, member = auth.require_event(request, event_id, "view")
    role = member["role"]
    queue = await hub.subscribe(event_id)

    async def generate():
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), 25)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if message.get("type") != "realtime":
                    try:
                        message = {**message, "state": event_state(event_id, role)}
                    except HTTPException:
                        message = {"type": "deleted"}
                yield f"data: {json.dumps(message, ensure_ascii=False)}\n\n"
        finally:
            hub.unsubscribe(event_id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/events/{event_id}/pledges/{pledge_id}/audio")
async def pledge_audio(event_id: str, pledge_id: int, request: Request):
    auth.require_event(request, event_id, "review")
    pledge = database.one("SELECT audio_path FROM pledges WHERE id = ? AND event_id = ?", (pledge_id, event_id))
    path = safe_data_path((pledge or {}).get("audio_path"))
    if not path:
        raise HTTPException(404, "The audio moment is not available")
    return FileResponse(path, media_type="audio/wav")


# ------------------------------------------------------ records and reports


ACTION_LABELS = {
    "event_created": "Event created", "sample_event_created": "Sample event created", "event_start": "Event went live",
    "event_pause": "Event paused", "event_resume": "Event resumed", "event_end": "Event ended", "event_reopen": "Event reopened",
    "event_archive": "Event archived", "event_unarchive": "Event restored from archive", "event_details_changed": "Event details changed",
    "guest_added": "Guest added", "guest_edited": "Guest edited", "guest_removed": "Guest removed", "guests_imported": "Guests imported",
    "live_pledge": "Pledge heard", "live_repeat_ignored": "Repeated announcement not counted twice", "rechecked": "Pledge rechecked",
    "recheck_failed": "Recheck failed", "usher_review": "Line reviewed", "listening_list_updated": "Listening list updated",
    "listening_started": "Listening started", "listening_stopped": "Listening stopped", "audio_upload_started": "Recording sent",
    "audio_upload_finished": "Recording finished", "audio_upload_failed": "Recording failed",
    "pledge_page_created": "Private pledge page created", "pledge_page_delivery": "Pledge page sent", "pledge_page_opened": "Guest opened pledge page",
    "pledge_page_closed": "Pledge page closed", "phone_call_logged": "Phone call logged", "checkout_started": "Guest started a payment",
    "payment_received": "Payment received", "payment_link_failed": "Payment could not start", "payment_verification_failed": "Payment check failed",
    "payment_promised": "Payment date promised", "payment_disputed": "Guest raised a problem", "follow_up_opted_out": "Guest opted out of follow-up",
    "assistant_started": "Guest started the voice assistant", "assistant_ended": "Voice assistant finished", "identity_checked": "Identity checked",
    "staff_invited": "Staff invited", "audio_deleted_by_retention": "Audio deleted after the retention period",
}


def activity_row(row: dict) -> dict:
    try:
        details = json.loads(row.get("details_json") or "{}")
    except json.JSONDecodeError:
        details = {}
    return {"id": row["id"], "action": row["action"], "label": ACTION_LABELS.get(row["action"], row["action"].replace("_", " ").capitalize()),
            "actor": row.get("actor_label") or "", "pledge_id": row.get("pledge_id"), "details": details, "created_at": row["created_at"]}


@app.get("/api/events/{event_id}/activity")
async def activity(event_id: str, request: Request, before: int | None = None, limit: int = 100):
    auth.require_event(request, event_id, "run")
    limit = max(1, min(limit, 500))
    params: tuple = (event_id, before, limit) if before else (event_id, limit)
    rows = database.all(
        "SELECT * FROM audit_log WHERE event_id = ?" + (" AND id < ?" if before else "") + " ORDER BY id DESC LIMIT ?", params)
    return {"rows": [activity_row(row) for row in rows], "more": len(rows) == limit}


def settlement_rows(event_id: str) -> list[dict]:
    rows = []
    for pledge in database.all("SELECT * FROM pledges WHERE event_id = ? AND state != 'rejected' ORDER BY id", (event_id,)):
        guest = database.one("SELECT title, name, phone, email, consent_to_contact FROM guests WHERE id = ?", (pledge["guest_id"] or -1,)) or {}
        last_call = database.one("SELECT outcome, details_json, created_at FROM calls WHERE pledge_id = ? ORDER BY id DESC LIMIT 1", (pledge["id"],))
        last_delivery = database.one("SELECT channel, status, created_at FROM deliveries WHERE pledge_id = ? ORDER BY id DESC LIMIT 1", (pledge["id"],))
        promised = (json.loads(last_call["details_json"] or "{}") or {}).get("promised_date") if last_call else None
        amount = pledge["amount_minor"]
        received = int(pledge["received_minor"] or 0)
        rows.append({
            "pledge_id": pledge["id"], "guest": guest_label(guest) or pledge["matched_name"] or pledge["heard_name"] or "Name unclear",
            "phone": guest.get("phone", ""), "email": guest.get("email", ""),
            "amount": amount, "currency": pledge["currency"] or "NGN", "item": pledge["item"], "received": received,
            "outstanding": max(0, (amount or 0) - received) if not pledge["item"] else None, "state": pledge["state"],
            "promised_date": promised, "last_contact": (last_call or last_delivery or {}).get("created_at"),
            "last_outcome": (last_call or {}).get("outcome") or ((last_delivery or {}).get("channel") and f"page sent by {last_delivery['channel']}"),
            "follow_up": "stopped" if pledge["follow_up_stopped"] else ("allowed" if guest.get("consent_to_contact") else "no consent"),
        })
    return rows


@app.get("/api/events/{event_id}/settlement")
async def settlement(event_id: str, request: Request):
    event, member = auth.require_event(request, event_id, "follow_up")
    rows = settlement_rows(event_id)
    state = event_state(event_id, member["role"])
    return {"rows": rows, "totals": state["totals"],
            "counts": {"pledges": len(rows), "fully_paid": sum(r["state"] == "redeemed" for r in rows),
                       "part_paid": sum(0 < r["received"] < (r["amount"] or 0) for r in rows),
                       "unpaid": sum(r["received"] == 0 and r["state"] in ACCEPTED_STATES and not r["item"] for r in rows),
                       "needs_checking": sum(r["state"] == "flagged" for r in rows), "in_kind": sum(bool(r["item"]) for r in rows)}}


def csv_response(filename: str, fields: list[str], rows: list[dict]) -> StreamingResponse:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in fields})
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


def file_slug(event: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", event["name"].lower()).strip("-")[:40] or "event"


@app.get("/api/events/{event_id}/export.csv")
async def export_register(event_id: str, request: Request):
    event, _ = auth.require_event(request, event_id, "export")
    rows = database.all("SELECT * FROM pledges WHERE event_id = ? ORDER BY id", (event_id,))
    for row in rows:
        row["amount"], row["received"] = row["amount_minor"], row["received_minor"]
    return csv_response(f"pledgebook-register-{file_slug(event)}.csv",
                        ["id", "heard_name", "matched_name", "amount", "currency", "item", "received", "state", "reason", "live_text", "recheck_text", "created_at", "updated_at"], rows)


@app.get("/api/events/{event_id}/settlement.csv")
async def export_settlement(event_id: str, request: Request):
    event, _ = auth.require_event(request, event_id, "export")
    return csv_response(f"pledgebook-settlement-{file_slug(event)}.csv",
                        ["pledge_id", "guest", "phone", "email", "amount", "currency", "item", "received", "outstanding", "state", "promised_date", "last_outcome", "last_contact", "follow_up"],
                        settlement_rows(event_id))


@app.get("/api/events/{event_id}/activity.csv")
async def export_activity(event_id: str, request: Request):
    event, _ = auth.require_event(request, event_id, "export")
    rows = [activity_row(row) for row in database.all("SELECT * FROM audit_log WHERE event_id = ? ORDER BY id", (event_id,))]
    for row in rows:
        row["details"] = json.dumps(row["details"], ensure_ascii=False)
    return csv_response(f"pledgebook-activity-{file_slug(event)}.csv", ["id", "created_at", "label", "actor", "pledge_id", "details"], rows)
