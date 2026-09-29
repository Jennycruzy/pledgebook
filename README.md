# Pledgebook

> **The MC calls it. Pledgebook writes it down — and follows it up until it is paid.**

At a Nigerian church launching or school fundraiser, pledges are shouted across a
noisy hall: *"Chief Emeka Okonkwo — two hundred and fifty thousand naira!"*
Someone scribbles it on paper, half the names are misspelled, and months later
nobody can say who promised what. Pledgebook listens to the MC, writes each
pledge into a register with the exact audio as evidence, asks a person whenever
anything is unclear, and then gives every guest a private page to pay, promise a
date, or say that something is wrong.

**Open it:** [pledgebook.54-154-121-30.sslip.io](https://pledgebook.54-154-121-30.sslip.io/)
— create an account for your organisation, or try the guided path in
[`docs/judge-guide.md`](docs/judge-guide.md).

The hard question it answers: **can a promise shouted across a noisy hall become
money in the bank without ever crediting the wrong person?**

## How it works

1. **Set up.** An owner creates the organisation, invites admins and ushers, and
   adds or imports the guest list. The import shows every row before anything
   is added and catches duplicates by name, phone or email.
2. **Listen.** When the event goes live, the MC's microphone streams to
   AssemblyAI Realtime. Guest names are sent as key terms. Each pledge appears on
   the live screen as *Provisional* within seconds, with a short clip of the
   exact words.
3. **Recheck.** That clip goes to AssemblyAI Sync with the guest list and word
   timings. Agreement becomes *Confirmed*. Anything unclear — an unknown name,
   two amounts in one breath, a currency mismatch, the same guest pledging again
   moments later — becomes *Needs checking*. Nothing is guessed.
4. **Review.** Ushers work the review queue on their own phones: play the clip,
   choose the guest, add a walk-in, enter the amount, or reject the line. A name
   an usher resolves is pushed straight into the live listening session, so the
   next mention is recognised.
5. **Follow up.** Staff send each guest a private pledge page by WhatsApp, SMS or
   email. The guest hears the moment they pledged (only when the clip contains
   nobody else's name), pays all or part through Paystack, chooses a date, or
   reports a problem. They can also talk it through with a clearly disclosed
   AssemblyAI voice assistant on their own phone. Staff log calls they make from
   their own phones and record cash or bank-transfer payments.
6. **Settle.** Ending the event produces a settlement report: pledged, received,
   outstanding, promised dates and last contact per guest, exportable as CSV.
   Every change, and who made it, is in the activity log.

## How AssemblyAI is used

- **Realtime Speech-to-Text** hears the room and receives mid-session
  `UpdateConfiguration` messages when an usher adds or resolves a name.
- **Sync** rechecks each short pledge clip with the event description, guest
  names and word timings. We chose Sync over Dictation because the product needs
  the verbatim transcript and timings, not a rewritten one.
- **Voice Agent** runs the guest-side assistant with a generated voice that
  always introduces itself as automated. It confirms who is speaking before
  recording anything and calls server tools to open checkout, record a promised
  date, record a dispute or stop reminders. It never changes the amount.

## What makes it a real product, not a demo

- Accounts, organisations and **owner / admin / usher roles**. Ushers never see
  guest phone numbers or emails. Every event API, export, audio clip and live
  connection checks membership. Writes need a same-origin header; sign-in and
  guest pages are rate limited.
- A full **event lifecycle**: set up, live, paused, ended, reopened, archived,
  deleted. Pausing or ending closes open microphones.
- **Guest administration**: edit, remove, consent changes, search, duplicate
  detection, import preview, per-guest history.
- **Payments are credited exactly once**, may be partial, and are verified with
  Paystack by reference, amount and currency, from the signed webhook or when the
  guest returns from checkout. Offline payments are recorded by staff.
- **Retention**: audio is deleted a set number of days after an event ends;
  sample events are deleted after 24 hours. Daily usage limits per organisation
  protect the service allowance.

## Honest limits

- Paystack is running in **test mode** on the public deployment. The code
  switches to real payments when a live key is configured; see
  [`docs/operations.md`](docs/operations.md).
- Email delivery needs SMTP settings on the server. Without them, pages are
  sent by WhatsApp, SMS or a copied link from staff phones. There is no
  automated outbound phone calling.
- No accuracy number is published until the benchmark in
  [`docs/evaluation.md`](docs/evaluation.md) is recorded with real voices.
- Pledgebook does not claim to understand Nigerian Pidgin, Igbo or Yoruba. It
  finds names and amounts in mixed English speech and asks a person otherwise.

More in [`LIMITATIONS.md`](LIMITATIONS.md). Architecture:
[`docs/architecture.md`](docs/architecture.md). Privacy:
[`docs/privacy.md`](docs/privacy.md). Measured service behaviour:
[`docs/verification.md`](docs/verification.md). Product decisions:
[`docs/decisions.md`](docs/decisions.md).

## Run it locally

```sh
cd pledgebook
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env        # add your AssemblyAI key; Paystack and SMTP are optional
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, create an account, and create an event or a
sample event. The microphone needs HTTPS when deployed; localhost is allowed.

Tests run without any service keys:

```sh
python3 -m pip install pytest
python3 -m pytest -q
```

CircleCI runs the tests, a compile check and a JavaScript syntax check.
Repository: [github.com/Jennycruzy/pledgebook](https://github.com/Jennycruzy/pledgebook).
