# Phases 1–3 — skeleton, live capture, and extraction

**Builder status:** Ready for review. Local server and real AssemblyAI capture
are working. Deployment and the independent review are still outstanding.

## Built

- FastAPI server with health page, static browser dashboard, and SQLite schema.
- Demo event creation with 61 clearly invented guests.
- Guest add/import endpoints, event start, SSE updates, register and CSV export.
- Server-side Realtime relay with prompt, guest key terms, rolling PCM buffer,
  adjacent final-turn pairing, and reconnect-visible errors.
- Conservative amount parser and guest matcher. Unclear values remain visible.
- Exact WAV evidence clips and Sync recheck with word timings.
- Browser WAV upload. Real PCM16 WAV files are normalized to mono 16 kHz and
  streamed through the same Realtime and Sync path as the microphone.
- Pledge states: provisional, confirmed, corrected, flagged, and rejected.
- Usher actions for choosing a guest or rejecting a line with a reason.
- Payment status explicitly reports Paystack as unavailable.

## Commands and actual output

```sh
python3 -m compileall -q app scripts && echo 'Python compile: ok'
```

```text
Python compile: ok
```

```sh
node --check web/app.js && echo 'Browser JavaScript syntax: ok'
```

```text
Browser JavaScript syntax: ok
```

```sh
python3 -m pytest -q
```

```text
26 passed in 0.44s
```

The local smoke server was started with `python3 -m uvicorn app.main:app
--host 127.0.0.1 --port 8765`. Network-enabled local checks returned:

```text
GET /healthz → {"ok":true,"assemblyai_configured":true,"paystack_configured":false,"version":"0.1.0"}
GET / → HTTP 200, 5053 bytes
POST /api/events → HTTP 200, demo event with 61 invented guests
```

The real 6.4-second Jenny recording excerpt was streamed through the local
WebSocket bridge. The first run exposed a missing final-turn flush and a wrong
event-limit field; both were fixed and rerun. Final database state:

```text
pledge id 1 | heard Emeka Okonkwo | amount 250000 | state confirmed
live: Chief Emeka Okonkwo. ₦250,000. Make una clap for him.
recheck: Chief Emeka Okonkwo, ₦250,000. Make a clap for him.
audit: live_pledge → rechecked
```

The supplied 70.4-second recording was also uploaded through the browser API
path. This was a diagnostic run, not a benchmark: Realtime merged several
nearby turns, so the conservative extractor raised four visible flags and did
not silently credit a disputed name. The run also showed that some amounts can
remain wrong when a short live clip contains more than one amount; those clips
are now marked *Needs checking* rather than selecting one. The final excerpt
smoke on the current code produced one confirmed pledge (₦250,000) with its
live and Sync text and no flags.

The source WAV and API response payloads remain in Git-ignored
`eval/private/phase-0/`. They are not published until Jenny decides that the
recording is safe to share.

## Not done

- HTTPS deployment and signed-out external check.
- Independent review and Jenny approval of this phase.
- Phase 4 walk-in benchmark and matching cut-off decision.
- Voice Agent browser follow-up UI and Paystack integration. Paystack has no
  owner test account yet, so these are not faked.
- Accuracy benchmark, public claims, and submission media.

## Review

Pending independent review and Jenny approval.
