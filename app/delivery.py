"""Sending a guest their private pledge page.

Email is sent through the organiser's SMTP service when it is configured.
SMS and WhatsApp open on the staff member's own phone with the message
prepared, so nothing is sent without a person pressing send.
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
import re
import smtplib
from urllib.parse import quote

from .config import Settings


def phone_digits(phone: str) -> str:
    """Return an international number without symbols, assuming Nigeria for a leading 0."""

    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = "234" + digits[1:]
    return digits


def valid_phone(phone: str) -> bool:
    return 7 <= len(re.sub(r"\D", "", phone or "")) <= 15


def message_text(guest_name: str, organisation: str, event_name: str, amount_label: str, url: str) -> str:
    return (
        f"Dear {guest_name}, thank you for your pledge of {amount_label} at {event_name}. "
        f"Your private pledge page from {organisation}: {url} "
        "You can pay, choose a date, or tell us if anything is wrong."
    )


def sms_uri(phone: str, text: str) -> str:
    return f"sms:+{phone_digits(phone)}?body={quote(text)}"


def whatsapp_uri(phone: str, text: str) -> str:
    return f"https://wa.me/{phone_digits(phone)}?text={quote(text)}"


def _send_email_blocking(settings: Settings, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)


async def send_email(settings: Settings, recipient: str, subject: str, body: str) -> None:
    if not settings.email_configured:
        raise RuntimeError("Email sending is not configured on this server.")
    await asyncio.to_thread(_send_email_blocking, settings, recipient, subject, body)
