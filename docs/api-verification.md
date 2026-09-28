# API verification — revised Pledgebook specification

**Checked:** 2026-09-27 (Africa/Lagos) against current public documentation.  
**Phase:** 0 — documentation and live account checks.  
**Status:** Sync, Realtime, Voice Agent, and Paystack Test Mode checks succeeded on Jenny's real recording or account. Gateway is optional and disabled for this account. A successful Paystack test-card payment and public webhook remain outstanding. Phase 0 evidence is ready for independent review.
**Credentials:** `ASSEMBLYAI_API_KEY` is present in the local, Git-ignored `pledgebook/.env` file. Its value is not recorded here. No API key was printed.

## Sync API — selected confirming pass

The current Sync STT guide documents `POST https://sync.assemblyai.com/v1/transcribe`. Raw HTTP requests use the API key directly in `Authorization` (no `Bearer`) and must include `X-AAI-Model: universal-3-5-pro`. The request is `multipart/form-data` with an `audio` part and, when configuration is needed, a JSON `config` part. The Sync guide's executable HTTP examples use the `/v1/transcribe` path. A recent AssemblyAI comparison blog shortens its table entry to `sync.assemblyai.com/transcribe` without `/v1`; use the versioned URL from the current endpoint guide unless a live call says otherwise.

The response includes verbatim `text`, `words`, `confidence`, `audio_duration_ms`, `session_id`, and `request_time_ms`. Word `start`/`end` values are omitted by default. Set `timestamps: true` to request them; AssemblyAI documents an added latency cost, says timings are exact or omitted rather than estimated, and says timing accuracy is best for English audio. We must retain the original audio excerpt as the evidence source if a word cannot be aligned.

Supported input constraints in the current Sync audio-requirements guide:

- 80 ms minimum and 120 seconds maximum per clip; maximum file size 40 MB.
- WAV (`audio/wav`) or raw 16-bit PCM S16LE (`audio/pcm`).
- Mono or stereo; stereo is down-mixed.
- 8,000, 16,000, 22,050, 24,000, 32,000, 44,100, or 48,000 Hz.
- Raw PCM requests need `sample_rate` and `channels` in `config`; WAV metadata is read from its header.

Sync accepts `prompt` for a plain description of the audio and `keyterms_prompt` for an array of names/terms. The Sync-specific guide says `prompt` can be up to 6,000 characters and `keyterms_prompt` can contain up to 100 terms / 8,000 characters total. It explicitly permits both together. A custom `prompt` replaces the managed default; when using one, include the language context in that description because the separate `language_codes` setting is ignored. The documentation advises using a short description rather than placing a list of names in the prompt. `timestamps: true` composes with both fields.

Current pricing lists Sync at **$0.45 per audio hour**, with key-term prompting included. Contextual `prompt` is an optional **additional $0.05 per audio hour**. The pricing page advertises a 134 ms p50 response time; this is not our measured latency. The API response exposes `request_time_ms`; we must measure real 5–15 second Pledgebook clips with Jenny's recording and include warm/cold connection conditions before saying it confirms within 10 seconds. The public guide states a server deadline of 30 seconds and a `504` timeout; client retry behavior must follow `Retry-After` for documented `429`/`503` responses.

### Sync documentation mismatches to carry to HARD STOP 1

1. **Endpoint spelling:** the current Sync guide and its HTTP examples say `/v1/transcribe`; an AssemblyAI blog comparison table says `/transcribe`. Pin the guide URL and verify it with an authenticated call before code depends on it.
2. **Language count:** the Sync getting-started/language-selection docs enumerate 32 codes, while the current pricing page says 18 and an AssemblyAI comparison blog says 19. The enumerated list excludes Yoruba, Igbo, and Nigerian Pidgin. The selected Sync/Realtime English workflow should not be described as supporting those languages. The count conflict remains unresolved.
3. **Key-term limit:** the Sync-specific guide says 100 terms / 8,000 characters. The pricing page's general Universal-3.5 Pro section mentions up to 1,000 terms (maximum six words each), which appears to describe the separate asynchronous API surface. Use the stricter Sync-specific limit and validate it in the first live request; do not transfer the asynchronous limit to Sync.
4. **Latency:** public pricing advertises 134 ms p50, while the spec requires a real 5–15 second clip measurement. Only the latter will answer whether the chosen clips confirm fast enough in this deployment.
5. **Prompt price:** the Sync model is $0.45/hour, but the situation `prompt` is a separately priced add-on at $0.05/hour. Costs that assumed prompting was included need this extra amount.
6. **Guest-list overflow:** Part 6 says names that do not fit in key terms go into the situation prompt. Sync's prompting guide recommends using `keyterms_prompt` for vocabulary lists and says not to pack lists of keywords into `prompt`. Before implementation, decide and test how to handle an event needing more than 100 terms / 8,000 characters (for example, which names to prioritize or how to scope terms per clip). Do not silently treat the situation prompt as an unlimited second key-term list.

The revised specification's reason for Sync is supported as a product-fit decision: verbatim transcript, short-clip request/response, optional per-word timings, and no rewrite field. Documentation does **not** establish that Sync is more accurate than Realtime; Phase 9 must measure that hypothesis. The selected APIs use related Universal-3.5 Pro products, but the real-time and Sync surfaces are distinct, so their relative accuracy must not be inferred from the model-family name.

## Dictation API — reference only; not in the revised runtime path

Jenny's revised decision record 4.3 explicitly excludes Dictation from the confirming path. Earlier planning checks found its endpoint at `POST https://dictation.assemblyai.com/v1/transcribe/live`, raw `Authorization` key, multipart `config` and `audio`, up to 120 seconds, `stt_prompt`, `keyterms_prompt`, and a response containing verbatim `text` plus cleaned `llm_response`. The selected build does not use that cleaned field or depend on Dictation. No reason remains to spend project credits validating Dictation behavior unless Jenny changes the decision.

## Realtime streaming

The current documented WebSocket is `wss://streaming.assemblyai.com/v3/ws`; current integration guidance uses `speech_model=universal-3-5-pro`, though older/current examples also show `u3-rt-pro`. The initial authenticated handshake must settle the identifier before implementation.

For the selected model, current guidance specifies mono PCM16 little-endian at 16 kHz, binary frames 50–1,000 ms, and no faster than real time. Turn events include `turn_order`, `end_of_turn`, `transcript`, `words`, and `utterance`; word timings are included in `words`. `prompt` and `keyterms_prompt` can be combined. The documented key-term limit is 100 terms, each no longer than 50 characters. `UpdateConfiguration` can update prompt and key terms during a live session.

Current pricing lists Universal-3.5 Pro Realtime at **$0.45 per session hour**, key terms included, and situation prompting as an additional **$0.05 per hour**. The public language count conflicts across current AssemblyAI pages (18 versus 19); neither count supports a claim of Yoruba, Igbo, or Nigerian Pidgin support. The official supported-language enumeration and live handshake still need to be recorded before code depends on the exact current model parameter/event shape.

The phrase “Nigerian-accented English is supported well” has no verified accuracy guarantee in the sources reviewed. Treat recognition quality as a benchmark result, not a product fact.

## Voice Agent API

Public docs identify `wss://agents.assemblyai.com/v1/ws` and server-side token creation at `https://agents.assemblyai.com/v1/token`. The browser should receive a short-lived token, not the secret API key. The documented flow initializes with `session.update`, waits for `session.ready`, and uses mono PCM16 at 24 kHz with base64 audio in JSON events. Tool declarations use a flat `type`/`name`/`description`/`parameters` shape. The event reference says to send the JSON-string `tool.result` with matching `call_id` after `reply.done`; confirm actual turn/tool flow in a live session before Phase 8. `ivy` is a documented voice, but Jenny has not selected one. Current published price is $4.50 per connected agent hour. No account handshake or live session has been run.

## AssemblyAI LLM Gateway

Public docs describe `https://llm-gateway.assemblyai.com/v1/chat/completions` and JSON-schema output using `response_format.type = "json_schema"` for supported model families. The public model catalog at `GET https://llm-gateway.assemblyai.com/v1/models` returned 47 model entries on 2026-09-27; this endpoint is public and does not establish account access.

An authenticated, minimal structured-output request to `gemini-3.8-flash` returned HTTP 400: `Your account does not have access to this LLM Gateway model` (request ID `c2c20550-2b3e-4562-ba91-0f346aeebb14`). This confirms that this model is not currently available to this account. It does **not** establish whether all Gateway models are unavailable; no alternate model was tried. No pledge text or audio was sent. Until an accessible model is confirmed, Pledgebook must not depend on Gateway output; the rule-based and human-review paths remain.

## Paystack test mode

Official docs confirm server-side `POST https://api.paystack.co/transaction/initialize` with required `email` and `amount`, the amount in the currency's smallest unit (kobo for NGN), an `authorization_url` and `reference` in the response, and `GET /transaction/verify/:reference`. The webhook signature is `x-paystack-signature`, HMAC-SHA512 over the raw request body with the secret key. Test and live modes are separate. Paystack's published successful test card is `4084 0840 8408 4081`, CVV `408`, with an expiry date in the future. Jenny created a Paystack Test Mode account on 2026-09-28 and saved its `sk_test_...` key locally; the key itself is not recorded here.

### Live Paystack check — 2026-09-28 Africa/Lagos

The key was checked without printing it: the local value has the `sk_test_`
prefix, and `.env` permissions are `600`. A real server-side initialization
request returned:

```text
POST https://api.paystack.co/transaction/initialize → HTTP 200
status: true
message: Authorization URL created
reference present: true
authorization URL host: checkout.paystack.com
```

The Pledgebook call tool then created another real Test Mode checkout after an
identity confirmation, stored the reference and link, and called Paystack's
verify endpoint before payment. Paystack returned `abandoned` for that
unfinished checkout, so the pledge stayed `confirmed`. An unsigned local
webhook request returned HTTP 401. A successful card payment and a signed
webhook from a public HTTPS deployment remain to be recorded.

## Hackathon submission facts

The event page lists September 1–30, 2026 and a submission close of **September 30, 2026 at 3:00 PM UTC**. LabLab's general submission guide says the video must be under five minutes and under 300 MB; the event page reviewed did not give a separate media limit. At the check date (September 27), fewer than four days remain. Recheck the event page before submission.

## Planning cost — explicit assumptions, not a measurement

Published-rate arithmetic for the capped sandbox example in the spec, assuming 3 minutes of prompted Realtime audio, eleven 5-second prompted Sync clips (55 seconds total), and two 2-minute Voice Agent calls:

- Realtime: 3 min × ($0.45 + $0.05 prompt add-on)/hour = $0.025.
- Sync: 55 sec × ($0.45 + $0.05 prompt add-on)/hour ≈ $0.00764.
- Voice Agent: 4 min × $4.50/hour = $0.30.
- Total ≈ **$0.33 per capped sandbox**, before LLM Gateway usage, connection/retry, or development usage.

This is only a planning calculation from published rates and the spec's assumed minutes. It is not measured usage or a claim for public materials. It excludes any LLM Gateway cost; actual hard-sentence usage is unknown. Benchmark usage cannot yet be estimated responsibly: recording lengths and actual Sync clip durations are not measured, and any single Sync request longer than 120 seconds is invalid. If a benchmark recording is longer than two minutes, the confirming pass must use short pledge clips rather than submit the entire recording as one Sync request. Measure and record actual seconds/cost from the test account when scripts and clips exist. Jenny supplied a dashboard screenshot showing **$150 credits remaining** on 2026-09-27; this is a screenshot reading, not an API balance check, and the balance may change during testing.

## Claims that need correction or more evidence

- The 84% average pledge-fulfilment and “half or more unpaid at events” claims in Part 1.1 have no source links in the specification. The secondary/historical sources previously reviewed do not substantiate the specific statements strongly enough. Do not use the figures publicly until the sources and exact wording are checked.
- Avoid saying the confirming pass is more accurate than Realtime until Phase 9 demonstrates it.
- Part 1.5's language-limit statement is consistent with the selected Sync code list for Yoruba, Igbo, and Pidgin, but phrase the product limitation narrowly: Pledgebook does not promise recognition of those languages; measure the actual mixed-English recordings.
- Do not claim a specific Nigerian-accent accuracy level without measurements.

## Account checks still needed for Phase 0

Realtime, Sync, Voice Agent, and Paystack Test Mode checks were run; see the dated continuations below. A successful Paystack card and public webhook still need a deployed HTTPS run. To continue without exposing secrets:

1. Jenny later creates a Paystack test account and enters its test secret locally when the payment phase begins. No payment path is enabled before then.
2. The optional Gateway integration stays disabled. The tested Gemini models were denied; Qwen was reachable but rejected the requested JSON-schema format. Rules and human review handle hard sentences.

The speech checks are complete. Phase 0 remains ready for independent review; application work proceeds with the Gateway and Paystack paths visibly disabled.

## Sources checked on 2026-09-27

### AssemblyAI Sync, Realtime, and pricing

- [Sync STT: Transcribe a short audio file](https://www.assemblyai.com/docs/sync-stt/getting-started/transcribe-a-short-audio-file)
- [Sync STT: Prompting and keyterms](https://www.assemblyai.com/docs/sync-stt/prompting-and-keyterms)
- [Sync STT: Audio requirements](https://www.assemblyai.com/docs/sync-stt/audio-requirements)
- [Sync STT: Word timestamps](https://www.assemblyai.com/docs/sync-stt/word-timestamps)
- [Sync STT: Language selection](https://www.assemblyai.com/docs/sync-stt/language-selection)
- [Sync STT: Error handling](https://www.assemblyai.com/docs/sync-stt/error-handling)
- [AssemblyAI pricing](https://www.assemblyai.com/pricing)
- [AssemblyAI: Sync API vs. Dictation API](https://www.assemblyai.com/blog/sync-api-vs-dictation-api)
- [AssemblyAI Realtime Speech-to-Text](https://www.assemblyai.com/products/streaming-speech-to-text)
- [AssemblyAI streaming audio file guide](https://www.assemblyai.com/docs/streaming/guides/streaming_transcribe_audio_file)
- [AssemblyAI streaming best practices and key terms](https://www.assemblyai.com/docs/voice-agents/best-practices)
- [AssemblyAI integration reference](https://github.com/AssemblyAI/assemblyai-skill/blob/main/skills/assemblyai/SKILL.md)

### Voice Agent and LLM Gateway

- [Voice Agent session configuration](https://www.assemblyai.com/docs/voice-agents/voice-agent-api/session-configuration)
- [Voice Agent events reference](https://www.assemblyai.com/docs/voice-agents/voice-agent-api/events-reference)
- [Voice Agent browser integration](https://www.assemblyai.com/docs/voice-agents/voice-agent-api/browser-integration)
- [Voice Agent voice catalog](https://www.assemblyai.com/docs/voice-agents/voice-agent-api/voices)
- [LLM Gateway overview](https://www.assemblyai.com/docs/llm-gateway/overview)
- [LLM Gateway structured outputs](https://www.assemblyai.com/docs/llm-gateway/structured-outputs)
- [LLM Gateway public models endpoint announcement](https://www.assemblyai.com/changelog?3b7e7275_page=3)
- [Gemini 3.8 Flash availability and features](https://www.assemblyai.com/changelog?3b7e7275_page=3)

### Paystack, LabLab, and fundraising context

- [Paystack accept payments](https://paystack.com/docs/payments/accept-payments/)
- [Paystack transactions API](https://paystack.com/docs/api/transaction/)
- [Paystack webhooks](https://paystack.com/docs/payments/webhooks/)
- [Paystack test payments](https://paystack.com/docs/payments/test-payments/)
- [AssemblyAI Voice Agent Hackathon](https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon)
- [LabLab general submission guide](https://lablab.ai/ai-articles/hackathon-guidelines)
- [RallyUp pledge fulfilment page](https://rallyup.com/blog/pledge-fulfillment-percentage/)
- [Study of telethon pledges](https://www.sciencedirect.com/science/article/abs/pii/S0167487017304385)


## Live continuation — 2026-09-27 21:35 UTC

Captured by `scripts/phase0_probe.py accounts`. Evidence: [recorded responses](evidence/phase-0/20260927T213548973343Z-accounts.json).

- **Realtime:** the documented `universal-3-5-pro` identifier succeeded with this account. Received Begin and Termination. Prompt and initial keyterms were included in the connection query. Sent UpdateConfiguration with a replacement list; no error observed. No audio was sent, so transcript shape, timings, and the effectiveness of updates remain unverified.
- **Voice Agent:** GET token with Bearer authorization, expiry 60 seconds and maximum session duration 60 seconds returned HTTP 200. The secret returned token is redacted. No conversation or synthesis occurred.
- **Gateway:** the structured-output guide's `gemini-2.5-flash-lite` example also returned HTTP 400, account lacks access to this model. Request ID `72de7ef2-a4b4-4037-a900-6092c0fad594`. Two model denials do not prove every model is unavailable. No alternate provider is selected.
- **Voice correction:** the current voice catalog lists `alba`, `eve`, `george`, `jane`, `jean`, `mary`, `michael`, `anna`, `charles`, `paul`, `vera` for English; it does not list `ivy`. The earlier claim about `ivy` is withdrawn. This is documentation evidence, not a tested voice.
- **Spec conflict:** Voice Agent synthesized output conflicts with the spec's universal synthetic-voice ban. Record the proposed narrow exception in `spec-clarifications.txt` for Jenny's decision before generating any speech.

Additional sources checked today:

- https://www.assemblyai.com/docs/streaming/updating-configuration-mid-stream
- https://www.assemblyai.com/docs/voice-agents/voice-agent-api/browser-integration
- https://www.assemblyai.com/docs/voice-agents/voice-agent-api/voices
- https://www.assemblyai.com/docs/llm-gateway/structured-outputs


## Live speech verification — 2026-09-28 Africa/Lagos

Jenny supplied a real human WAV recording. The original was 70.4 seconds, mono 16-bit PCM at 48 kHz. The official Sync endpoint `POST https://sync.assemblyai.com/v1/transcribe` accepted it with raw-key authorization, `X-AAI-Model: universal-3-5-pro`, and `prompt`, `keyterms_prompt`, `timestamps: true` inside the JSON config. It returned HTTP 200 with text, 85 words, word start/end milliseconds, confidence, session ID, audio duration, and request time. Wall-clock duration: 8.69 seconds. The earlier blog's unversioned endpoint spelling is not needed: the versioned guide path worked live.

A 6.4-second real excerpt, resampled from the original and kept private, returned HTTP 200 twice with nine timestamped words. End-to-end Sync times were **1.59 and 1.82 seconds**. Server-reported request times were **934 and 945 ms**. These are measured individual requests, not general latency guarantees. The real audio shows the confirming path can finish within the spec's roughly 10-second budget in this case.

The same excerpt, paced through Realtime, produced actual `Begin`, `SpeechStarted`, `Turn`, and `Termination` messages. The final name and amount were in separate turns, and `words` carried timestamps. A partial amount `200,000.` changed to a final `250,000 naira.` later in the same turn. The timed rerun observed the final amount 6,496 ms after connection attempt began; that includes connection and real-time audio playback and is **not** a measured time to on-screen display.

Private evidence and source SHA-256 are recorded under `eval/private/phase-0/` and ignored by Git pending publication review. See `docs/progress/phase-0.md` for commands, outputs, and exact file names. No claim of recognition accuracy is made because Jenny has not provided an independent answer key.

## Live Voice Agent verification — 2026-09-28 Africa/Lagos

Jenny approved generated speech for the clearly disclosed automated assistant only. The builder ran the Voice Agent probe on the same real human excerpt, using a `session.update` with the documented `anna` voice and one JSON-schema tool. Token creation returned HTTP 200. The session produced `session.ready`, assistant audio, user transcript, a `tool.call`, the matching `tool.result`, final assistant transcript, and `session.ended`. Evidence: `eval/private/phase-0/20260928T000213440991Z-voice.json` (Git-ignored).

The assistant transcript heard `Chief Emeka Okonkwo, ₦250,000. Make una clap for him.` The tool argument was `Emeka Okonkwo`, omitting the title. This is a real observed limitation; the product must preserve the transcript and apply its own guest matching before any financial record. The verification tool created no pledge or payment. Paystack Test Mode is now configured separately; the payment tool uses it only after identity confirmation.
