# Pledgebook

> **The MC calls it. Pledgebook writes it down — and makes sure it gets paid.**

## Try the live demo

**[Open Pledgebook](https://pledgebook.54-154-121-30.sslip.io/)**

Start a private demo launching, add yourself to the invented guest list, read
the script in your own voice, and watch the spoken pledge move from the live
screen to a checked record. The follow-up assistant can create a Paystack Test
Mode checkout after it confirms who is speaking. No real money moves.

The sharper question is: **can a promise shouted across a noisy hall become
money in the bank without ever crediting the wrong person?**

## Three things Pledgebook does

- **It learns names during the event.** When an usher resolves an unclear name,
  the active AssemblyAI listening session receives the new guest term and later
  pledges show that they were recognised after the correction.
- **It can show the moment you pledged.** The private payment page uses Sync's
  word timings to trim a pledge clip. If the words cannot be separated safely
  from another guest, it shows the transcript instead of playing audio.
- **It flags instead of guessing.** An unclear name, unclear amount, walk-in,
  or disagreement stays visible for a human, with the live words, recheck, and
  audio evidence retained.

## What a judge should see in two minutes

1. Press **Start my demo launching**.
2. Open **Guest list**, add your name and tick follow-up consent. Your name is
   inserted into the MC script.
3. Press **Start listening**, then read the script, or use the owner-approved
   sample recording button. Pledges arrive as **Provisional**, then become
   **Confirmed** or **Needs checking** after the recheck.
4. Open **Needs checking** and choose a guest or **New walk-in**. The correction
   is written to the audit trail and updates the listening list.
5. In **Follow-up**, choose **Call about this**. The disclosed assistant checks
   identity before discussing money, then offers the private pledge page and
   Paystack Test Mode checkout.

## The evidence we will publish

The benchmark is deliberately empty until it is run on the deployed build. We
will report the **wrong-person count first**, then names and amounts right,
needed flags, time to the live screen, time to a rechecked record, and the
number of corrected names recognised on their next mention. No number appears
here until it is measured and committed in [`docs/evaluation.md`](docs/evaluation.md).

## How AssemblyAI is used

- **Realtime Speech-to-Text** hears the room while the MC is speaking.
- **Sync** rechecks the exact short audio clip with the situation description,
  guest names, and word timings. We chose Sync over Dictation because this
  build uses the verbatim transcript and timings; Dictation's rewrite would be
  discarded. The decision is recorded in [`docs/architecture.md`](docs/architecture.md).
- **Voice Agent** runs the disclosed follow-up conversation, confirms identity,
  and calls structured server actions for the payment link, promise, dispute,
  opt-out, and final outcome.

Paystack is a separate payment provider. The server uses its Test Mode secret
only, verifies the signed webhook and transaction reference, and marks a pledge
**Redeemed** only after the amount and currency match.

## What Pledgebook does not do

- It does not claim Nigerian Pidgin, Igbo, or Yoruba understanding. It listens
  for names and amounts in mixed English speech and ignores the rest.
- It does not decide about money when the words are unclear. A person resolves
  every flag.
- It does not pressure donors. The follow-up is a disclosed reminder with a
  payment link and an opt-out.

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

Open `http://127.0.0.1:8000`. The microphone needs HTTPS when deployed;
localhost is allowed for local testing. All demo names and amounts are
invented. Every transcript in the product comes from AssemblyAI processing a
real human recording. The clearly disclosed follow-up assistant may use
AssemblyAI generated speech under the owner's decision; MC and test recordings
are never synthetic.

## Engineering notes and limits

The server keeps API keys out of the browser, relays 16 kHz mono microphone
audio to AssemblyAI Realtime, stores event state in SQLite, and keeps the exact
audio evidence for each pledge. It supports a real WAV upload through the same
path, reconnect-safe live updates, guest CSV import, an usher queue, register
history, CSV export, private expiring payment pages, and a signed Paystack
webhook. Public demo sandboxes allow three minutes of audio and two follow-up
calls, then expire after 24 hours; a daily cap is visible in the app.

The optional AssemblyAI LLM Gateway was not available for the tested account,
so hard sentences go to rules and a human. See [`LIMITATIONS.md`](LIMITATIONS.md),
[`docs/api-verification.md`](docs/api-verification.md),
[`docs/privacy.md`](docs/privacy.md), and
[`docs/judge-guide.md`](docs/judge-guide.md) for the full record.

CircleCI runs the repository checks in clean Python and Node jobs. The public
repository is [github.com/Jennycruzy/pledgebook](https://github.com/Jennycruzy/pledgebook).
