"""Small, server-only Paystack integration.

The browser never receives the Paystack secret.  The server creates a
checkout, stores its reference, and verifies the transaction again before a
pledge can become redeemed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from .config import Settings


PAYSTACK_BASE = "https://api.paystack.co"


class PaystackError(RuntimeError):
    """A clear, safe error returned by Paystack or by our validation."""


def _headers(settings: Settings) -> dict[str, str]:
    if not settings.paystack_secret_key:
        raise PaystackError("Paystack is not configured.")
    return {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise PaystackError(f"Paystack returned an unreadable response (HTTP {response.status_code}).") from exc
    if not isinstance(body, dict):
        raise PaystackError("Paystack returned an unexpected response.")
    return body


async def initialize_transaction(
    settings: Settings,
    *,
    amount_naira: int,
    email: str,
    reference: str,
    metadata: dict[str, Any],
    callback_url: str = "",
) -> dict[str, Any]:
    """Create a Paystack checkout for a whole-naira pledge amount."""

    if amount_naira <= 0:
        raise PaystackError("The pledge amount must be greater than zero.")
    if not email.strip():
        raise PaystackError("A guest email is required to create a payment link.")
    payload = {
        "email": email.strip(),
        # Pledgebook stores naira as an integer; Paystack expects kobo.
        "amount": str(amount_naira * 100),
        "reference": reference,
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }
    if callback_url:
        payload["callback_url"] = callback_url
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{PAYSTACK_BASE}/transaction/initialize", headers=_headers(settings), json=payload)
    except httpx.HTTPError as exc:
        raise PaystackError(f"Paystack could not be reached: {exc}") from exc
    body = _json(response)
    if response.status_code >= 400 or body.get("status") is not True:
        message = str(body.get("message") or f"HTTP {response.status_code}")
        raise PaystackError(f"Paystack could not create the payment link: {message}")
    data = body.get("data")
    if not isinstance(data, dict) or not data.get("authorization_url") or not data.get("reference"):
        raise PaystackError("Paystack did not return a payment link and reference.")
    return {"body": body, "data": data, "amount_kobo": amount_naira * 100}


async def verify_transaction(settings: Settings, reference: str) -> dict[str, Any]:
    """Fetch the transaction status from Paystack using its reference."""

    if not reference.strip():
        raise PaystackError("A payment reference is required.")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{PAYSTACK_BASE}/transaction/verify/{reference}", headers=_headers(settings))
    except httpx.HTTPError as exc:
        raise PaystackError(f"Paystack could not be reached: {exc}") from exc
    body = _json(response)
    if response.status_code >= 400 or body.get("status") is not True:
        message = str(body.get("message") or f"HTTP {response.status_code}")
        raise PaystackError(f"Paystack could not verify the payment: {message}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise PaystackError("Paystack returned no transaction details.")
    return {"body": body, "data": data}


def valid_webhook_signature(secret: str, raw_body: bytes, signature: str | None) -> bool:
    """Validate Paystack's HMAC-SHA512 signature over the raw request body."""

    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip())
