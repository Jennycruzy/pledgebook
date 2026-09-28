# Pledgebook architecture

The first working slice keeps the API key on the server. The browser sends
PCM16 microphone frames to the server. The server relays them to AssemblyAI
Realtime, stores a rolling byte buffer, and sends final turn events back to
the browser. When a final name and amount can be paired, it writes a
provisional row and cuts the exact source audio into a short WAV file.

That clip is sent to AssemblyAI Sync with the event description, guest names,
and word timings. The result is reconciled against the live row. Agreement
becomes **Confirmed**; an amount correction becomes **Rechecked — changed**;
an unclear or conflicting person becomes **Needs checking**. Every transition
is an audit row. The original clip remains the evidence.

```text
browser microphone or real WAV upload
        │ PCM16 frames / normalized WAV
        ▼
FastAPI server ───────► AssemblyAI Realtime (live turns)
   │        │                         │
   │        └──────────► SQLite + audit log + SSE updates
   │                                  │
   └──────────► exact WAV clip ─► AssemblyAI Sync (word timings)
                                  │
                                  ▼
                         reconciliation and usher queue
                                           │
                         browser follow-up ◄┘
                                  │ short-lived token
                                  ▼
                         AssemblyAI Voice Agent
```

The browser never receives the AssemblyAI API key. WAV uploads are real human
recordings and are normalized to the Realtime format before streaming. The
follow-up browser session receives a short-lived Voice Agent token; its
structured tool calls return to the FastAPI server, which writes call outcomes
and refuses to share payment information before identity confirmation.

The payment adapter is intentionally absent from the live path until Jenny
creates Paystack test mode. The optional Gateway integration is also disabled
until an account model accepts the required structured output.
