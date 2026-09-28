# Phase 8 — follow-up assistant and payments

**Builder status:** Follow-up assistant and Paystack Test Mode slice ready for
review. A successful card payment and public webhook still need a deployed
HTTPS run.

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
- With Jenny's `sk_test_...` key present locally, the server initializes a real
  Paystack Test Mode checkout, stores its reference, and returns the checkout
  URL only after identity is confirmed.
- The server validates Paystack's raw-body HMAC-SHA512 webhook signature,
  verifies the transaction reference, amount, and currency with Paystack, and
  makes duplicate success notifications harmless.

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

## Paystack Test Mode verification — 2026-09-28 Africa/Lagos

Jenny saved a Test Secret Key locally. The key was checked without printing
it: it has the `sk_test_` prefix, and `.env` permissions are `600`.

```text
POST https://api.paystack.co/transaction/initialize → HTTP 200
message: Authorization URL created
reference present: true
authorization URL host: checkout.paystack.com
```

The same request was run through the Pledgebook call tool with a temporary
confirmed pledge and a real test email:

```text
start call → HTTP 200
identity check → HTTP 200, ok: true
send payment link → HTTP 200, ok: true
reference present: true
payment link host: checkout.paystack.com
verify before payment → HTTP 200, status: abandoned
pledge state after verification: confirmed
invalid webhook signature → HTTP 401
```

The temporary local event, pledge, call, and payment row were deleted after
the run. No real money was moved. The `abandoned` status is expected for a
checkout that was initialized but not completed; it did not redeem the pledge.

## Not done

- A successful Paystack test-card payment, signed webhook delivery from a
  public HTTPS deployment, and redeemed-state evidence.
- A real browser Voice Agent conversation with Jenny's microphone. The API
  session and the route/tool behavior are verified; the browser interaction
  still needs a manual run.
- Payment acceptance evidence.

## Review

Pending independent review and Jenny approval. The local Test Mode checkout
is ready for review; the successful card run and public webhook still need a
deployed HTTPS demonstration.
