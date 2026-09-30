import hashlib
import sqlite3

from app.core import database
from app.db import Database
from helpers import add_guest, add_pledge


def send_copy(owner, event_id, pledge_id):
    url = owner.post(f"/api/events/{event_id}/pledges/{pledge_id}/deliver", {"channel": "copy"}).json()["url"]
    return url.rsplit("/", 1)[-1]


def test_pledge_page_tokens_are_stored_only_as_hashes(owner, event):
    pledge_id = add_pledge(event["id"], add_guest(owner, event["id"], name="Tunde Bello"))
    token = send_copy(owner, event["id"], pledge_id)
    rows = database.all("SELECT * FROM pledge_links WHERE pledge_id = ?", (pledge_id,))
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert all(token not in str(value) for row in rows for value in row.values())
    assert owner.get(f"/api/pay/{token}").status_code == 200


def test_sending_again_issues_a_new_link_and_keeps_the_old_one(owner, event):
    pledge_id = add_pledge(event["id"], add_guest(owner, event["id"], name="Ngozi Eze"))
    first = send_copy(owner, event["id"], pledge_id)
    second = send_copy(owner, event["id"], pledge_id)
    assert first != second
    assert owner.get(f"/api/pay/{first}").status_code == 200
    assert owner.get(f"/api/pay/{second}").status_code == 200


def test_links_stored_as_issued_are_hashed_on_upgrade(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE pledge_links (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, "
                     "pledge_id INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, created_by INTEGER, created_at TEXT NOT NULL, "
                     "expires_at TEXT NOT NULL, opened_at TEXT, revoked_at TEXT)")
        conn.execute("INSERT INTO pledge_links(event_id, pledge_id, token, created_at, expires_at) VALUES ('e', 1, 'old-token', 'x', 'y')")
    upgraded = Database(path)
    Database(path)  # a second start must not hash the hash again
    row = upgraded.one("SELECT * FROM pledge_links")
    assert "token" not in row
    assert row["token_hash"] == hashlib.sha256(b"old-token").hexdigest()
