"""Sample events: a practice space with invented guests, kept apart from real events.

A sample event is created on purpose from My Events, is labelled on every
screen, can process the owner-approved sample recording, and is deleted with
all its audio after 24 hours.
"""

from datetime import date, datetime, timedelta, timezone
import uuid

from .core import SAMPLE_RETENTION_HOURS, add_usage, database, settings
from .db import now


# Invented guests. Several share names heard in the owner-approved sample
# recording, so a rehearsal shows confirmed lines as well as review
# questions; the rest never appear in it. Emails use the reserved
# example.org domain so nothing can reach a real person.
SAMPLE_GUESTS = [
    ("Deaconess", "Ngozi Eze", "ngozi.eze@example.org", True),
    ("Engineer", "Tunde Bakare", "tunde.bakare@example.org", True),
    ("Brother", "Segun Ogunleye", "segun.ogunleye@example.org", True),
    ("Mrs", "Aisha Bello", "", False),
    ("Dr", "Ifeanyi Obi", "", False),
    ("Pastor", "Kelechi Amadi", "kelechi.amadi@example.org", True),
    ("Ms", "Amina Yusuf", "", False),
    ("Mr", "Chinedu Obi", "", False),
    ("Dr", "Tola Adeyemi", "", False),
]


def sample_recording_available() -> bool:
    return bool(settings.sample_audio_path and settings.sample_audio_path.is_file())


def create_sample_event(org_id: str, user: dict) -> str:
    event_id = uuid.uuid4().hex
    expires = (datetime.now(timezone.utc) + timedelta(hours=SAMPLE_RETENTION_HOURS)).isoformat()
    database.execute(
        "INSERT INTO events(id, name, organisation, event_date, demo, sample, status, created_at, expires_at, org_id, created_by) "
        "VALUES (?, ?, ?, ?, 0, 1, 'setup', ?, ?, ?, ?)",
        (event_id, "Harvest Thanksgiving Launching", "Grace Chapel (sample)", date.today().isoformat(), now(), expires, org_id, user["id"]),
    )
    for title, name, email, consent in SAMPLE_GUESTS:
        database.execute(
            "INSERT INTO guests(event_id, title, name, email, consent_to_contact, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, title, name, email, int(consent), now()),
        )
    add_usage(org_id, "events_created", 1)
    database.audit(event_id, "sample_event_created", {"invented_names": True, "expires_at": expires}, actor=user)
    return event_id
