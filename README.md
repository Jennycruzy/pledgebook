# Pledgebook

The MC calls it. Pledgebook writes it down — and makes sure it gets paid.

Pledgebook listens to a fundraiser MC, puts each spoken pledge on a shared
screen, rechecks the exact audio moment with AssemblyAI Sync, and leaves an
audit trail for every correction or question. A human usher resolves anything
unclear. The current build has real AssemblyAI Realtime and Sync capture,
SQLite records, guest lists, audio evidence, the big screen, the usher queue,
and CSV export.

This is a new build for the AssemblyAI Voice Agent Hackathon. Demo names and
amounts are invented. Human test recordings are real. The disclosed automated
assistant may use an AssemblyAI generated voice under Jenny's decision on
2026-09-28. Paystack is not configured yet, so no payment is claimed and no
money can move through this build.

## Run it locally

```sh
cd pledgebook
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
# Put the AssemblyAI key in .env. Keep the file local.
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, press **Start my demo launching**, then press
**Start listening** and **Press to listen**. Read a line from the script in
your own voice, or choose **Play a real WAV recording**. Uploads are real
human recordings and are normalized on the server before the same live path.
The browser needs a secure origin when deployed; localhost is allowed for
local microphone testing.

## What is live

- AssemblyAI Universal-3.5 Pro Realtime receives PCM16 microphone frames.
- The server pairs names and amounts across final turns and keeps unfinished
  readings provisional.
- Sync receives the exact short clip, with the situation description, guest
  names, and word timings.
- Each pledge keeps its live text, recheck text, state, source times, and audio
  clip. Recheck failures remain visible.
- Nearby repeated turns and clips containing multiple names or amounts are
  kept as one audit trail or sent to **Needs checking**; the extractor does
  not choose silently.
- Unknown names, unclear amounts, and event-limit violations stay in **Needs
  checking**. The usher can choose a guest or reject a line with a reason.
- The register exports CSV and shows the recorded history.
- The follow-up screen can open a real AssemblyAI Voice Agent session for a
  guest who gave contact consent. It checks identity first and records the
  structured call outcome. With no Paystack account, the payment tool reports
  that no link was created.

## What is deliberately unavailable

Paystack test mode has not been set up on the owner's account. The payment
screen is therefore disabled rather than simulated. AssemblyAI's optional LLM
Gateway was not available for the tested account models, so hard sentences go
to rules and a human review. Pledgebook does not promise Nigerian Pidgin, Igbo,
or Yoruba recognition; it extracts names and amounts from mixed English speech.

See [Phase 0 evidence](docs/progress/phase-0.md),
[API verification](docs/api-verification.md), and
[the grouped spec decisions](docs/spec-clarifications.txt). Current limits are
listed in [LIMITATIONS.md](LIMITATIONS.md), and evaluation stays empty until
the real Phase 9 benchmark is run.
