"""Sample events: a practice space with invented guests, kept apart from real events.

A sample event is created on purpose from My Events, is labelled on every
screen, can process the owner-approved sample recording, and is deleted with
all its audio after 24 hours.
"""

from datetime import date, datetime, timedelta, timezone
import uuid

from .core import SAMPLE_RETENTION_HOURS, add_usage, database, settings
from .db import now


SAMPLE_GUESTS = [
    ("Ms", "Amina Yusuf"),
    ("Mr", "Chinedu Obi"),
    ("Dr", "Tola Adeyemi"),
]


def sample_recording_available() -> bool:
    return bool(settings.sample_audio_path and settings.sample_audio_path.is_file())


def create_sample_event(org_id: str, user: dict) -> str:
    event_id = uuid.uuid4().hex
    expires = (datetime.now(timezone.utc) + timedelta(hours=SAMPLE_RETENTION_HOURS)).isoformat()
    database.execute(
        "INSERT INTO events(id, name, organisation, event_date, demo, sample, status, created_at, expires_at, org_id, created_by) "
        "VALUES (?, ?, ?, ?, 0, 1, 'setup', ?, ?, ?, ?)",
        (event_id, "Sample launching", "Sample organisation", date.today().isoformat(), now(), expires, org_id, user["id"]),
    )
    for title, name in SAMPLE_GUESTS:
        database.execute(
            "INSERT INTO guests(event_id, title, name, consent_to_contact, created_at) VALUES (?, ?, ?, 0, ?)",
            (event_id, title, name, now()),
        )
    add_usage(org_id, "events_created", 1)
    database.audit(event_id, "sample_event_created", {"invented_names": True, "expires_at": expires}, actor=user)
    return event_id
