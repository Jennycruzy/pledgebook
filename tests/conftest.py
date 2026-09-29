import os
from pathlib import Path
import tempfile

# The application reads its settings when first imported. Point it at an
# empty data folder and no service keys so tests never touch real data or
# call AssemblyAI, Paystack or an email server.
_DATA = Path(tempfile.mkdtemp(prefix="pledgebook-tests-"))
os.environ.update({
    "PLEDGEBOOK_DATA_DIR": str(_DATA),
    "ASSEMBLYAI_API_KEY": "",
    "PAYSTACK_SECRET_KEY": "sk_test_unit",
    "PLEDGEBOOK_PUBLIC_URL": "https://pledgebook.test",
    "PLEDGEBOOK_SAMPLE_AUDIO": "",
    "SMTP_HOST": "",
    "SMTP_FROM": "",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.auth import limiter  # noqa: E402


HEADERS = {"X-Pledgebook": "1"}


class Client:
    """A signed-in browser: keeps the session cookie and sends the request header."""

    def __init__(self):
        self.http = TestClient(app, base_url="https://pledgebook.test")

    def get(self, url, **kwargs):
        return self.http.get(url, **kwargs)

    def post(self, url, json=None, **kwargs):
        return self.http.post(url, json=json, headers={**HEADERS, **kwargs.pop("headers", {})}, **kwargs)

    def patch(self, url, json=None):
        return self.http.patch(url, json=json, headers=HEADERS)

    def delete(self, url):
        return self.http.delete(url, headers=HEADERS)


_counter = {"n": 0}


def new_account(organisation="Grace Assembly", invite="", name="Ada Staff"):
    _counter["n"] += 1
    client = Client()
    email = f"person{_counter['n']}@example.com"
    body = {"name": name, "email": email, "password": "correct horse battery", "organisation": organisation, "invite": invite}
    response = client.post("/api/auth/signup", body)
    assert response.status_code == 200, response.text
    client.email = email
    return client


@pytest.fixture(autouse=True)
def reset_limits():
    limiter.hits.clear()
    yield


@pytest.fixture
def owner():
    return new_account()


@pytest.fixture
def event(owner):
    response = owner.post("/api/events", {"name": "Harvest launching", "event_date": "2026-10-04"})
    assert response.status_code == 200, response.text
    return response.json()["event"]
