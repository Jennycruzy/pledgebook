# Phase 8 — follow-up assistant and payments

**Builder status:** Follow-up assistant slice ready for review. Payment work
is intentionally blocked until Jenny creates a Paystack test account.

## Built

- Browser follow-up screen for confirmed, corrected, or redeemed pledges.
- Short-lived AssemblyAI Voice Agent token fetched by the server; the browser
  never receives the AssemblyAI API key.
- A disclosed assistant session using the verified `anna` voice, 24 kHz PCM
  input/output, and the six structured follow-up tools from the specification.
- Identity check before any amount discussion. A wrong-person result records an
  outcome and returns no pledge amount or payment information.
- Server-side call and tool audit records for identity, promises, disputes,
  opt-outs, unavailable payment links, and the final call outcome.
- Payment tool fails clearly when `PAYSTACK_SECRET_KEY` is absent. It does not
  return a fake URL or mark a pledge paid.

## Commands and actual output

```sh
python3 -m pytest -q
```

```text
28 passed in 0.24s
```

```sh
node --check web/app.js
python3 -m compileall -q app scripts
```

```text
both commands completed successfully
```

With the local server and the real confirmed excerpt pledge:

```text
GET /api/voice-token → HTTP 200
POST /api/events/.../pledges/34/call/start → HTTP 200
confirm_identity(false) → {"ok":true,"identity_confirmed":false,"message":"Identity was not confirmed. End the call without discussing the pledge."}
send_payment_link after wrong identity → {"ok":false,"error":"Identity was not confirmed; no payment information was shared."}
```

The verified live Voice Agent session itself is recorded in
`eval/private/phase-0/20260928T000213440991Z-voice.json`: token HTTP 200,
`session.ready`, assistant audio, a real human user transcript, one tool call,
the tool result, final reply, and clean session end.

## Not done

- Paystack account, test secret, transaction initialization, verification,
  signed webhook, and redeemed state.
- A real browser Voice Agent conversation with Jenny's microphone. The API
  session and the route/tool behavior are verified; the browser interaction
  still needs a manual run.
- Payment acceptance evidence.

## Review

Pending independent review and Jenny approval. This phase cannot be complete
until the Paystack owner account is available or Jenny explicitly records the
payment feature as out of scope for submission.
