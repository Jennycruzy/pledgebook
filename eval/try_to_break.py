"""Try to break Pledgebook's safety rules on a live deployment.

Creates throwaway accounts, a sample event and one real pledge from the
owner-approved sample recording, then attempts what an outsider, an usher or
a misbehaving voice assistant should not be able to do. Every attempt must
be refused for the run to pass.

    python eval/try_to_break.py --base https://pledgebook.example
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sys
import time

import httpx


PASSWORD = "try-to-break " + secrets.token_hex(4)


def client(base: str, header: bool = True) -> httpx.Client:
    return httpx.Client(base_url=base, headers={"X-Pledgebook": "1"} if header else {}, timeout=60)


def sign_up(base: str, name: str, organisation: str = "", invite: str = "") -> httpx.Client:
    c = client(base)
    email = f"break-{secrets.token_hex(5)}@example.com"
    r = c.post("/api/auth/signup", json={"name": name, "email": email, "password": PASSWORD, "organisation": organisation, "invite": invite})
    r.raise_for_status()
    return c


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    base = parser.parse_args().base.rstrip("/")
    results: list[tuple[str, str, bool]] = []

    def check(attempt: str, response: httpx.Response | dict, refused: bool, detail: str = "") -> None:
        shown = detail or (f"HTTP {response.status_code}" if isinstance(response, httpx.Response) else str(response)[:80])
        results.append((attempt, shown, refused))
        print(f"{'refused ' if refused else 'ALLOWED '} {attempt}: {shown}", flush=True)

    print("Setting up a sample event with a real pledge (about 90 seconds)…", flush=True)
    owner = sign_up(base, "Owner", "Try To Break Parish")
    event = owner.post("/api/events/sample").json()["event"]
    eid = event["id"]
    owner.post(f"/api/events/{eid}/guests", json={"title": "Chief", "name": "Emeka Okonkwo", "email": "emeka.break@example.com",
                                                 "phone": "08030000001", "consent_to_contact": True}).raise_for_status()
    owner.post(f"/api/events/{eid}/lifecycle", json={"action": "start"}).raise_for_status()
    owner.post(f"/api/events/{eid}/sample-audio").raise_for_status()
    pledge = None
    for _ in range(150):
        time.sleep(1)
        state = owner.get(f"/api/events/{eid}").json()
        pledge = next((p for p in state["pledges"] if p.get("matched_name") == "Emeka Okonkwo" and p["state"] in ("confirmed", "corrected")), None)
        if pledge and pledge.get("rechecked_at"):
            break
    if not pledge:
        sys.exit("The sample recording did not produce a confirmed pledge; cannot continue.")
    link = owner.post(f"/api/events/{eid}/pledges/{pledge['id']}/deliver", json={"channel": "copy"}).json()["url"]
    token = link.rsplit("/", 1)[-1]

    stranger = sign_up(base, "Stranger", "Another Parish")
    invite = owner.post("/api/organisation/invites", json={"role": "usher", "event_id": eid}).json()["url"].rsplit("/", 1)[-1]
    usher = sign_up(base, "Usher", invite=invite)
    signed_out = client(base)

    check("Signed-out visitor reads the event", signed_out.get(f"/api/events/{eid}"), signed_out.get(f"/api/events/{eid}").status_code == 401)
    r = signed_out.get(f"/api/events/{eid}/export.csv")
    check("Signed-out visitor downloads the register", r, r.status_code == 401)
    r = stranger.get(f"/api/events/{eid}")
    check("Member of another organisation reads the event", r, r.status_code == 404)
    r = client(base, header=False)
    r.cookies = owner.cookies
    r = r.post("/api/events", json={"name": "Forged from another site"})
    check("Cross-site form posts as the signed-in owner", r, r.status_code == 403)
    r = client(base).post("/api/auth/signup", json={"name": "Second", "email": f"again-{secrets.token_hex(3)}@example.com", "password": PASSWORD, "invite": invite})
    check("Invitation used a second time", r, r.status_code == 410)

    state = usher.get(f"/api/events/{eid}").json()
    leaked = any("phone" in g or "email" in g for g in state["guests"])
    check("Usher sees guest phone numbers or emails", {"leaked": leaked}, not leaked, "no contact fields in the usher's view" if not leaked else "contact fields present")
    r = usher.get(f"/api/events/{eid}/export.csv")
    check("Usher downloads the register", r, r.status_code == 403)
    r = usher.post(f"/api/events/{eid}/pledges/{pledge['id']}/resolve", json={"action": "amount", "amount": 1})
    check("Usher changes a confirmed pledge to ₦1", r, r.status_code == 403)
    r = usher.post(f"/api/events/{eid}/lifecycle", json={"action": "end"})
    check("Usher ends the event", r, r.status_code == 403)
    r = usher.post(f"/api/events/{eid}/pledges/{pledge['id']}/deliver", json={"channel": "copy"})
    check("Usher opens the guest's private pledge page link", r, r.status_code == 403)

    r = signed_out.get(f"/api/pay/{token[:-4]}AAAA")
    check("Guessed pledge-page link", r, r.status_code == 404)
    r = signed_out.post("/api/pay/not-a-real-page/assistant", headers={"X-Pledgebook": "1"})
    check("Voice assistant token without a pledge page", r, r.status_code == 404)
    r = signed_out.get("/api/voice-token")
    check("Old open voice-token address", r, r.status_code == 404)

    guest = client(base)
    session = guest.post(f"/api/pay/{token}/assistant")
    if session.status_code == 200:
        s = session.json()
        tool = f"/api/pay/{token}/assistant/{s['call_id']}/tool"
        r = guest.post(tool, json={"session_id": s["session_id"], "tool": "record_promise", "arguments": {"promised_date": "2026-12-01"}}).json()
        check("Assistant records a promise before identity is confirmed", r, r.get("ok") is False, r.get("error", ""))
        r = guest.post(tool, json={"session_id": s["session_id"], "tool": "open_checkout", "arguments": {}}).json()
        check("Assistant opens checkout before identity is confirmed", r, r.get("ok") is False, r.get("error", ""))
        r = guest.post(tool, json={"session_id": "someone-elses-session", "tool": "record_opt_out", "arguments": {}})
        check("Tool call with another session's id", r, r.status_code == 404)
        guest.post(tool, json={"session_id": s["session_id"], "tool": "confirm_identity", "arguments": {"is_correct_person": True}})
        r = guest.post(tool, json={"session_id": s["session_id"], "tool": "change_amount", "arguments": {"amount": 1}}).json()
        check("Assistant, after identity is confirmed, tries to change the amount", r, r.get("ok") is False, r.get("error", ""))
        amount_after = owner.get(f"/api/events/{eid}").json()
        unchanged = next(p for p in amount_after["pledges"] if p["id"] == pledge["id"])["amount"] == pledge["amount"]
        check("Pledge amount after that attempt", {"unchanged": unchanged}, unchanged, f"still {pledge['amount']:,}" if unchanged else "changed")
    else:
        check("Assistant session could not start", session, False)

    r = guest.post(f"/api/pay/{token}/checkout", json={"amount": 10_000_000})
    check("Guest pays more than they pledged", r, r.status_code == 400)
    owner.post(f"/api/events/{eid}/pledges/{pledge['id']}/resolve", json={"action": "reject", "reason": "Try-to-break check"})
    r = guest.get(f"/api/pay/{token}")
    check("Pledge page after the pledge was rejected", r, r.status_code == 410)
    body = b'{"event":"charge.success","data":{"reference":"forged"}}'
    r = httpx.post(f"{base}/api/paystack/webhook", content=body, headers={"x-paystack-signature": "0" * 128})
    check("Forged Paystack payment notification", r, r.status_code == 401)

    passed = all(ok for _, _, ok in results)
    folder = Path(__file__).resolve().parent / "results"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = [f"# Try to break it — {stamp}", "", f"Deployment: {base}", "",
              f"**{sum(ok for _, _, ok in results)} of {len(results)} attempts refused.**", "",
              "| Attempt | Result | Refused |", "|---|---|:-:|"]
    report += [f"| {a} | {d} | {'yes' if ok else '**NO**'} |" for a, d, ok in results]
    (folder / f"try-to-break-{stamp}.md").write_text("\n".join(report) + "\n")
    print(f"\n{sum(ok for _, _, ok in results)} of {len(results)} refused. Report: eval/results/try-to-break-{stamp}.md")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
