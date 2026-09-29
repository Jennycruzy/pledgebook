"""Run the Pledgebook benchmark against a deployment and score it.

Each recording gets a fresh event with the benchmark guest list, is streamed
through the same listening path as a microphone, and is scored against
answer_key.json. For script C the runner plays the usher: as soon as the
unlisted name is flagged it adds the walk-in while the session is still open.

    python eval/benchmark/run.py --base https://pledgebook.example \\
        --email you@example.com recordings/*.wav

The password is read from PLEDGEBOOK_PASSWORD or asked for. Results are
written to eval/results/<time>/ as report.md and results.json. The answer key
is fixed before recording; do not edit it after seeing results.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time

import httpx


HERE = Path(__file__).resolve().parent
ACCEPTED = {"provisional", "confirmed", "corrected", "redeemed"}
FILE_PATTERN = re.compile(r"^(?P<speaker>[^-]+)-(?P<script>[ABC])-(?P<condition>[a-z]+)\.wav$", re.IGNORECASE)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def seconds_between(start: str | None, end: str | None) -> float | None:
    a, b = parse_time(start), parse_time(end)
    return round((b - a).total_seconds(), 2) if a and b else None


class Deployment:
    def __init__(self, base: str, email: str, password: str):
        self.http = httpx.Client(base_url=base.rstrip("/"), headers={"X-Pledgebook": "1"}, timeout=90)
        response = self.http.post("/api/auth/login", json={"email": email, "password": password})
        if response.status_code != 200:
            sys.exit(f"Sign-in failed: {response.text}")

    def call(self, method: str, path: str, **kwargs) -> dict:
        response = self.http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} → {response.status_code}: {response.text[:300]}")
        return response.json()

    def new_event(self, name: str) -> str:
        event_id = self.call("POST", "/api/events", json={"name": name})["event"]["id"]
        with (HERE / "guests.csv").open("rb") as handle:
            preview = self.call("POST", f"/api/events/{event_id}/guests/import/preview", files={"file": ("guests.csv", handle, "text/csv")})
        self.call("POST", f"/api/events/{event_id}/guests/import", json={"rows": [r for r in preview["rows"] if r["status"] == "ok"]})
        self.call("POST", f"/api/events/{event_id}/lifecycle", json={"action": "start"})
        return event_id


def run_recording(site: Deployment, path: Path, lines: list[dict], correct_names: bool) -> dict:
    event_id = site.new_event(f"Benchmark {path.stem} {datetime.now(timezone.utc):%H%M%S}")
    learn = next((line for line in lines if line.get("learn")), None)
    learned = None
    with path.open("rb") as handle:
        site.call("POST", f"/api/events/{event_id}/upload", files={"file": (path.name, handle, "audio/wav")})
    started = time.monotonic()
    finished_at = None
    while time.monotonic() - started < 360:
        state = site.call("GET", f"/api/events/{event_id}")
        if learn and correct_names and not learned:
            pattern = re.compile(learn["learn"]["match"], re.IGNORECASE)
            for pledge in state["pledges"]:
                heard = f"{pledge['live_text']} {pledge['heard_name']}"
                if pledge["state"] == "flagged" and pattern.search(heard):
                    site.call("POST", f"/api/events/{event_id}/pledges/{pledge['id']}/resolve",
                              json={"action": "walk_in", "walk_in_title": learn["learn"]["title"], "walk_in_name": learn["learn"]["name"]})
                    learned = {"pledge_id": pledge["id"], "resolved_after_seconds": round(time.monotonic() - started, 1),
                               "first_mention_live_text": pledge["live_text"]}
                    break
        activity = site.call("GET", f"/api/events/{event_id}/activity?limit=40")["rows"]
        done = any(row["action"] in ("audio_upload_finished", "audio_upload_failed") for row in activity)
        if done and finished_at is None:
            finished_at = time.monotonic()
        pending = [p for p in state["pledges"] if p["has_audio"] and not p.get("rechecked_at") and not (p["reason"] or "").startswith("Not rechecked")]
        if finished_at and (not pending or time.monotonic() - finished_at > 45):
            break
        time.sleep(1)
    failure = next((row["details"].get("error") for row in activity if row["action"] == "audio_upload_failed"), None)
    state = site.call("GET", f"/api/events/{event_id}")
    site.call("POST", f"/api/events/{event_id}/lifecycle", json={"action": "end"})
    return {"event_id": event_id, "state": state, "learned": learned, "upload_error": failure}


def tokens_for(line: dict) -> list[str]:
    if line.get("anonymous"):
        return ["anonymous", "son of the soil"]
    name = line.get("guest") or line.get("walk_in") or ""
    words = [w.lower() for w in name.split() if len(w) > 2]
    if line.get("item"):
        words.append("cement")
    return words


def pledge_text(p: dict) -> str:
    return " ".join(str(p.get(k) or "") for k in ("live_text", "recheck_text", "heard_name", "matched_name")).lower()


def align(lines: list[dict], pledges: list[dict]) -> tuple[dict, list[dict]]:
    """Match each expected line to the pledge that captured it, in spoken order."""

    ordered = sorted(pledges, key=lambda p: (p.get("source_start_ms") or 0, p["id"]))
    used: set[int] = set()
    matches: dict[str, dict] = {}
    cursor = 0
    for line in lines:
        if line.get("repeat_of"):
            continue
        best, best_score, best_index = None, 0, None
        for index in range(cursor, min(len(ordered), cursor + 5)):
            pledge = ordered[index]
            if pledge["id"] in used:
                continue
            text = pledge_text(pledge)
            score = 2 * sum(token in text for token in tokens_for(line))
            expected_amount = line.get("amount")
            if expected_amount and expected_amount in (pledge.get("amount"), pledge.get("live_amount_minor")):
                score += 1
            if score > best_score:
                best, best_score, best_index = pledge, score, index
        if best and best_score >= 2:
            matches[line["id"]] = best
            used.add(best["id"])
            cursor = best_index + 1
    extras = [p for p in ordered if p["id"] not in used]
    return matches, extras


def expected_guest_id(line: dict, guests: dict[str, int]) -> int | None:
    name = line.get("guest")
    return guests.get(name.lower()) if name else None


def score_recording(run: dict, lines: list[dict]) -> dict:
    state = run["state"]
    guests = {g["name"].lower(): g["id"] for g in state["guests"]}
    matches, extras = align(lines, state["pledges"])
    rows, latencies_live, latencies_recheck = [], [], []
    counts = {key: 0 for key in ("expected", "correct_accept", "correct_flag", "wrong_person", "wrong_amount", "false_flag",
                                  "accepted_without_person", "missed", "double_counted", "extra_lines",
                                  "realtime_right", "sync_corrected", "person_needed")}
    for line in lines:
        if line.get("repeat_of"):
            original = matches.get(line["repeat_of"])
            repeats = [p for p in extras if original and any(t in pledge_text(p) for t in tokens_for(next(l for l in lines if l["id"] == line["repeat_of"])))]
            outcome = "not counted twice"
            if any(p["state"] in ACCEPTED for p in repeats):
                outcome = "counted twice"
                counts["double_counted"] += 1
            elif repeats:
                outcome = "flagged as possible repeat"
            for p in repeats:
                extras.remove(p)
            rows.append({"id": line["id"], "expect": line["expect"], "outcome": outcome})
            continue
        counts["expected"] += 1
        pledge = matches.get(line["id"])
        row = {"id": line["id"], "expect": line["expect"], "tests": line.get("tests", "")}
        if not pledge:
            counts["missed"] += 1
            rows.append({**row, "outcome": "missed"})
            continue
        want_guest = expected_guest_id(line, guests)
        got_guest = pledge.get("guest_id")
        accepted = pledge["state"] in ACCEPTED
        right_person = (pledge.get("matched_name") == "Anonymous donor" and not got_guest) if line.get("anonymous") else (got_guest == want_guest and want_guest is not None)
        right_amount = bool(pledge.get("item")) if line.get("item") else pledge.get("amount") == line.get("amount")
        live_s = seconds_between(pledge.get("spoken_end_at"), pledge.get("created_at"))
        recheck_s = seconds_between(pledge.get("spoken_end_at"), pledge.get("rechecked_at"))
        if live_s is not None:
            latencies_live.append(live_s)
        if recheck_s is not None:
            latencies_recheck.append(recheck_s)
        if line["expect"] == "accept":
            if accepted and got_guest and not right_person:
                outcome = "WRONG PERSON"
                counts["wrong_person"] += 1
            elif accepted and right_person and not right_amount:
                outcome = "wrong amount accepted"
                counts["wrong_amount"] += 1
            elif accepted and right_person:
                outcome = "correct"
                counts["correct_accept"] += 1
            elif pledge["state"] == "flagged":
                outcome = "flagged (safe, needs a person)"
                counts["false_flag"] += 1
            else:
                outcome = f"state {pledge['state']}"
            live_right = (pledge.get("live_guest_id") == want_guest or (line.get("anonymous") and not pledge.get("live_guest_id"))) and \
                (bool(pledge.get("item")) if line.get("item") else pledge.get("live_amount_minor") == line.get("amount"))
            if pledge["state"] == "flagged":
                counts["person_needed"] += 1
                row["pass"] = "person needed"
            elif live_right:
                counts["realtime_right"] += 1
                row["pass"] = "Realtime right"
            elif outcome == "correct":
                counts["sync_corrected"] += 1
                row["pass"] = "Sync corrected"
        else:
            learned_here = run.get("learned") and run["learned"]["pledge_id"] == pledge["id"]
            if pledge["state"] == "flagged" or learned_here:
                outcome = "correctly flagged" + (" (runner resolved it as the usher)" if learned_here else "")
                counts["correct_flag"] += 1
            elif accepted and got_guest and line.get("guest") and got_guest != want_guest:
                outcome = "WRONG PERSON"
                counts["wrong_person"] += 1
            elif accepted and got_guest and not line.get("guest"):
                outcome = "WRONG PERSON (credited an unlisted speaker to a listed guest)"
                counts["wrong_person"] += 1
            else:
                outcome = "accepted without a person"
                counts["accepted_without_person"] += 1
        rows.append({**row, "outcome": outcome, "pledge_id": pledge["id"], "state": pledge["state"],
                     "live_text": pledge.get("live_text"), "recheck_text": pledge.get("recheck_text"),
                     "final": pledge.get("item") or pledge.get("amount"), "guest": pledge.get("matched_name") or pledge.get("heard_name"),
                     "live_seconds": live_s, "recheck_seconds": recheck_s})
    for pledge in extras:
        counts["extra_lines"] += 1
        if pledge["state"] in ACCEPTED and pledge.get("guest_id"):
            counts["wrong_person"] += 1
            rows.append({"id": "extra", "outcome": "WRONG PERSON (unexpected accepted line)", "pledge_id": pledge["id"], "live_text": pledge.get("live_text"), "guest": pledge.get("matched_name")})
        else:
            rows.append({"id": "extra", "outcome": f"extra line, {pledge['state']}", "pledge_id": pledge["id"], "live_text": pledge.get("live_text")})
    learning = None
    learn_line = next((l for l in lines if l.get("learned_from")), None)
    if learn_line:
        second = matches.get(learn_line["id"])
        learned_guest = guests.get(learn_line["guest"].lower())
        learning = {
            "corrected_during_session": bool(run.get("learned")),
            "first_mention": (run.get("learned") or {}).get("first_mention_live_text") or (matches.get(learn_line["learned_from"]) or {}).get("live_text"),
            "second_mention_live": second.get("live_text") if second else None,
            "second_mention_recognised_live": bool(second and learned_guest and second.get("live_guest_id") == learned_guest),
            "second_mention_marked_learned": bool(second and second.get("recognised_from_pledge_id")),
            "exact_spelling_in_second_live_text": bool(second and learn_line["guest"].lower() in (second.get("live_text") or "").lower()),
        }
    return {"counts": counts, "rows": rows, "latency_live": latencies_live, "latency_recheck": latencies_recheck, "learning": learning}


def summarise(values: list[float]) -> str:
    if not values:
        return "—"
    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return f"median {statistics.median(ordered):.1f} s · p90 {p90:.1f} s · n={len(ordered)}"


def write_report(results: list[dict], folder: Path, correct_names: bool) -> str:
    total: dict[str, int] = {}
    live, recheck = [], []
    for result in results:
        for key, value in result["score"]["counts"].items():
            total[key] = total.get(key, 0) + value
        live += result["score"]["latency_live"]
        recheck += result["score"]["latency_recheck"]
    accept_lines = sum(1 for r in results for row in r["score"]["rows"] if row.get("expect") == "accept")
    lines = [
        f"# Pledgebook benchmark — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
        f"{len(results)} recordings · {total.get('expected', 0)} spoken pledges · usher correction during script C: {'on' if correct_names else 'off (control run)'}", "",
        "## Wrong-person credits", "", f"**{total.get('wrong_person', 0)}**", "",
        "## Outcomes", "",
        "| Measure | Count |", "|---|---:|",
        f"| Right guest and amount reached the ledger without a person | {total.get('correct_accept', 0)} of {accept_lines} |",
        f"| Lines that should go to a person and did | {total.get('correct_flag', 0)} |",
        f"| Clear lines sent to a person anyway (safe, costs usher time) | {total.get('false_flag', 0)} |",
        f"| Wrong amount accepted for the right guest | {total.get('wrong_amount', 0)} |",
        f"| Unclear lines accepted without a person | {total.get('accepted_without_person', 0)} |",
        f"| Pledges missed entirely | {total.get('missed', 0)} |",
        f"| Repeated announcements counted twice | {total.get('double_counted', 0)} |",
        f"| Extra lines not in the script | {total.get('extra_lines', 0)} |", "",
        "## What each pass contributed (clear lines only)", "",
        f"- Realtime was already right: {total.get('realtime_right', 0)}",
        f"- Realtime was wrong or unclear and the Sync recheck corrected it: {total.get('sync_corrected', 0)}",
        f"- Sent to a person: {total.get('person_needed', 0)}", "",
        "## Timing", "",
        f"- Spoken to live screen: {summarise(live)}",
        f"- Spoken to rechecked record: {summarise(recheck)}", "",
    ]
    learning = [r for r in results if r["score"].get("learning")]
    if learning:
        lines += ["## Learning a name during the event", "", "| Recording | First mention (live) | Second mention (live) | Recognised live | Exact spelling |", "|---|---|---|:-:|:-:|"]
        for r in learning:
            l = r["score"]["learning"]
            lines.append(f"| {r['file']} | {l['first_mention'] or '—'} | {l['second_mention_live'] or '—'} | {'yes' if l['second_mention_recognised_live'] else 'no'} | {'yes' if l['exact_spelling_in_second_live_text'] else 'no'} |")
        lines.append("")
    lines += ["## Every line", ""]
    for r in results:
        lines += [f"### {r['file']}", ""]
        if r.get("upload_error"):
            lines += [f"Upload failed: {r['upload_error']}", ""]
        lines += ["| Line | Expected | Outcome | Heard live | Rechecked | Pass | Live s | Recheck s |", "|---|---|---|---|---|---|--:|--:|"]
        for row in r["score"]["rows"]:
            lines.append(f"| {row.get('id')} | {row.get('expect', '')} | {row.get('outcome')} | {(row.get('live_text') or '').replace('|', '/')} | {(row.get('recheck_text') or '').replace('|', '/')} | {row.get('pass', '')} | {row.get('live_seconds') or ''} | {row.get('recheck_seconds') or ''} |")
        lines.append("")
    report = "\n".join(lines)
    (folder / "report.md").write_text(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--no-correction", action="store_true", help="Control run: do not add the walk-in during script C")
    args = parser.parse_args()
    password = os.environ.get("PLEDGEBOOK_PASSWORD") or getpass.getpass("Pledgebook password: ")
    key = json.loads((HERE / "answer_key.json").read_text())["scripts"]
    site = Deployment(args.base, args.email, password)
    folder = HERE.parent / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for path in args.recordings:
        match = FILE_PATTERN.match(path.name)
        if not match:
            print(f"Skipping {path.name}: name it <speaker>-<A|B|C>-<condition>.wav")
            continue
        script = match["script"].upper()
        print(f"{path.name}: running script {script}…", flush=True)
        run = run_recording(site, path, key[script], correct_names=not args.no_correction)
        score = score_recording(run, key[script])
        print(f"  wrong person {score['counts']['wrong_person']} · correct {score['counts']['correct_accept']} · flags {score['counts']['correct_flag']} · false flags {score['counts']['false_flag']} · missed {score['counts']['missed']}")
        results.append({"file": path.name, **match.groupdict(), "event_id": run["event_id"], "upload_error": run["upload_error"],
                        "learned": run["learned"], "score": score})
    (folder / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(write_report(results, folder, not args.no_correction))
    print(f"\nWritten to {folder.relative_to(HERE.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
