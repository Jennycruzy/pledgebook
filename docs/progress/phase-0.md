# Phase 0 — Verification

**Updated:** 2026-09-27 (Africa/Lagos)  
**Builder status:** Real Sync, Realtime, and Voice Agent checks succeeded on Jenny's recording. The optional Gateway feature is unavailable for the tested models. Paystack is not set up. The Phase 0 evidence is ready for Jenny's review; implementation can proceed with the Gateway and Paystack features disabled until their later setup decisions.  
**Gate:** HARD STOP 1 evidence is complete. Jenny's two decisions are recorded below. The application build is now beginning with those limits visible.

## What was built

- Refreshed `docs/api-verification.md` against current public Sync STT documentation and pricing, in line with revised decision record 4.3 (Sync is the confirming pass; Dictation is not in the runtime path).
- Added a private local `.env` placeholder with `ASSEMBLYAI_API_KEY` and a `.gitignore` rule before Jenny entered the key. Confirmed the file is ignored and permission mode is `600`; the key was never displayed.
- Recorded Jenny's dashboard screenshot reading of $150 credits remaining. The screenshot itself was not copied into the repository.
- Made authenticated structured-output requests to two Gateway models; both were denied for Jenny's account. The optional feature is disabled. No pledge text or audio was sent to Gateway.
- Recorded the open documentation conflicts and remaining account checks.
- Added `scripts/phase0_probe.py` to run real account checks and capture responses; it also supports Sync and Realtime checks once Jenny supplies a human recording. No application code, mocks, stubs, or synthetic audio were created.

## Commands run and output

Initial workspace inventory (from the first Phase 0 turn):

```text
find /Users/user -maxdepth 1 -iname '*pledge*' -print
```

Output before creating the project folder: *(no output; no existing Pledgebook directory)*

```text
printenv | cut -d= -f1 | rg -i 'ASSEMBLY|PAYSTACK' || true
```

Output: *(no matching environment variable names; no AssemblyAI or Paystack variable was exported in that shell)*

```text
mkdir -p /Users/user/pledgebook/docs/progress
```

Output: *(no output; exit code 0)*

Workspace inventory at the start of this turn (before obsolete files were removed):

```text
pwd && rg --files pledgebook | sort
```

Output:

```text
/Users/user
pledgebook/docs/api-verification.md
pledgebook/docs/claude-review-handoff.txt
pledgebook/docs/progress/phase-0.md
pledgebook/docs/question-for-spec-author.txt
```

The earlier root-level `git status --short` showed extensive unrelated user files and changes and was truncated by the tool. Pledgebook is a subdirectory of that existing checkout; no root changes were committed or pushed.

Post-edit scope check:

```text
git status --short -- pledgebook
```

Output:

```text
?? pledgebook/
```

Key-presence check (prints only whether the value is present):

```text
awk -F= '/^ASSEMBLYAI_API_KEY=/ { if (length($2) > 0) print "ASSEMBLYAI_API_KEY is set (value hidden)"; else print "ASSEMBLYAI_API_KEY is empty"; found=1 } END { if (!found) print "ASSEMBLYAI_API_KEY entry is missing" }' pledgebook/.env
```

Output:

```text
ASSEMBLYAI_API_KEY is set (value hidden)
```

Secret-file protection check:

```text
chmod 600 pledgebook/.env && git check-ignore -v pledgebook/.env && stat -f '%Lp %N' pledgebook/.env
```

Output:

```text
pledgebook/.gitignore:2:.env	pledgebook/.env
600 pledgebook/.env
```

Public model-catalog check (retrieved through the approved network request; this endpoint is unauthenticated):

```text
python3 -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("https://llm-gateway.assemblyai.com/v1/models", timeout=20)); items=d.get("data", []) if isinstance(d,dict) else d; print("model count:", len(items)); print("models:", [(m.get("id") or m.get("model"), m.get("capabilities")) for m in items if "json" in str(m.get("capabilities","")).lower()][:8])'
```

Output:

```text
model count: 47
models: []
```

The response parser did not find model IDs/capabilities in the fields it expected, so this check establishes only the public catalog count. It does not establish account entitlements.

Authenticated LLM Gateway account check (the `.env` key was read but never printed; the request contained no Pledgebook audio or pledge data):

```text
python3 -c 'import json, pathlib, urllib.error, urllib.request; lines=pathlib.Path("pledgebook/.env").read_text().splitlines(); key=next((line.split("=",1)[1].strip() for line in lines if line.startswith("ASSEMBLYAI_API_KEY=")),"");
if not key: raise SystemExit("ASSEMBLYAI_API_KEY is empty")
payload={"model":"gemini-3.8-flash","messages":[{"role":"user","content":"Return only the JSON object {\"ok\":true}."}],"max_tokens":20,"response_format":{"type":"json_schema","json_schema":{"name":"phase0_access_check","schema":{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}}}}
request=urllib.request.Request("https://llm-gateway.assemblyai.com/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":key,"Content-Type":"application/json"},method="POST")
try:
 response=urllib.request.urlopen(request,timeout=30); result=json.load(response); choice=result.get("choices",[{}])[0]; print("HTTP",response.status); print("model:",result.get("model")); print("content:",choice.get("message",{}).get("content")); print("usage:",result.get("usage"))
except urllib.error.HTTPError as error:
 print("HTTP",error.code); print("response:",error.read().decode("utf-8","replace")[:600]); raise SystemExit(1)'
```

Output:

```text
HTTP 400
response: {"metadata":{"errors":["Your account does not have access to this LLM Gateway model"]},"request_id":"c2c20550-2b3e-4562-ba91-0f346aeebb14","message":"invalid request body","code":400}
```

This denies access to the tested model; it is not evidence that every Gateway model is disabled. No alternate model has been tested.

Documentation-reference audit:

```text
rg -l "Dictation|Sync API|HARD STOP 1|not in the runtime path" pledgebook/docs
```

Output:

```text
pledgebook/docs/claude-review-handoff.txt
pledgebook/docs/progress/phase-0.md
pledgebook/docs/api-verification.md
```

Public documentation was checked using web searches and direct page opens/clicks. The source URLs and findings are listed in `docs/api-verification.md`. One authenticated LLM Gateway structured-output request was made after Jenny configured the local key; it returned HTTP 400 denying access to `gemini-3.8-flash`. No pledge or audio data was sent. No tests were run. No real voice clip is available yet, so Sync and Realtime audio checks remain pending.

## What was verified

- The revised product decision is Sync for the confirming pass. The current Sync-specific guide documents the versioned endpoint, raw-key auth, model header, request/response shape, WAV/PCM format limits, prompting and key-term fields, optional word timestamps, and short-clip limit.
- Current Sync-specific prompt/key-term documentation permits `prompt` and `keyterms_prompt` together. The current feature-specific limit is 100 terms / 8,000 characters. The Sync situation prompt costs an additional $0.05 per audio hour on top of the $0.45 Sync rate.
- The updated sandbox's illustrative rates still total about $0.33 under its stated assumptions, now including both prompting add-ons. This is internal planning arithmetic, not measured usage or a public claim.
- The updated spec resolves the old Dictation-versus-Sync choice. Dictation is reference-only and does not need to be used by the planned product.
- Jenny supplied a dashboard screenshot showing $150 credits remaining on 2026-09-27. This is a visual dashboard reading, not an API balance query.
- The API key is set in the ignored, permission-restricted local `.env` file. It was not displayed or committed.
- The account rejected the tested `gemini-3.8-flash` structured-output request with HTTP 400 and the message that the account does not have access to that model. Another model may still work; Gateway access is unresolved.

## Confusing or conflicting findings to take to Jenny

- A current AssemblyAI comparison blog omits `/v1` from the Sync endpoint, while the Sync API guide and executable request examples specify `/v1/transcribe`. The versioned official guide is the safest documented choice, but the authenticated Phase 0 request must confirm it.
- Current AssemblyAI pages disagree on the Sync language count: 18 on pricing, 19 in a comparison blog, and 32 in Sync language-selection docs. The enumerated 32-code list excludes Yoruba, Igbo, and Nigerian Pidgin; do not claim recognition support for them.
- The Sync-specific guide says 100 key terms / 8,000 characters, while the general Universal-3.5 Pro pricing section describes up to 1,000 phrases for a different pre-recorded API surface. Use the stricter Sync-specific limit and validate it live.
- Pricing advertises a Sync p50 of about 134 ms, but that is not Pledgebook's measured response time. The spec's 5–15 second real-clip test remains necessary.
- Sync word timings are optional, add latency, and the docs say timing accuracy is best for English audio. They may be missing for words the system cannot align; the original audio clip remains the evidence.
- AssemblyAI's current product pages list the Sync situation-prompt add-on at $0.05/hour. Previous estimates that omitted prompt add-ons need that correction.
- Part 6 says to put names beyond the key-term cap into the situation prompt, while Sync's prompt guide says to use key terms for vocabulary lists and not to pack lists into the situation prompt. A safe overflow policy needs a decision and a test.
- Sync accepts clips only up to 120 seconds; longer benchmark recordings have to be split into pledge clips. The actual clip durations and resulting benchmark cost are unknown until Jenny's recordings exist.
- The supplied fundraising fulfilment percentages remain unsupported by sources linked in the specification.

## Not done or not verified

- Sync and Paystack have not been called. Realtime connected and terminated successfully without audio; Voice Agent token creation returned HTTP 200. Both Gateway models tested were denied. See the continuation evidence below.
- No real Jenny-recorded 5–15 second clip was available to measure Sync response time or inspect the actual transcript/timings.
- Paystack account access/test-mode readiness remains for Jenny to confirm. No transaction or webhook was created.
- Realtime's handshake confirms `universal-3-5-pro` is accepted. Actual speech turns and Voice Agent tool flow still need recordings/session checks.
- No suitable source has yet been selected for the fundraising percentages in Part 1.1.
- No application code, deployment, GitHub repository, commit, or push was created.

## What Jenny needs to provide now

1. Send one of her existing MC recordings, or record the short invented example in `docs/next-step.txt`. A Voice Memos file is fine; the builder will convert a copy and retain the original. Supply the actual words if using a different script.
2. Paystack account readiness is still an owner-only Phase 0 item. It is a separate service, not an AssemblyAI dashboard setting. This does not block the speech checks.

Jenny does not need to select a model or find Gateway settings. The builder owns these checks. The optional Gateway feature has no confirmed accessible model and cannot be claimed as working.

After those checks, the builder will record the exact commands and outputs, refresh this report with the live evidence, and stop for the independent review and Jenny approval required by the spec. No app code before that approval.

Final documentation-scope check:

```text
rg --files pledgebook | sort
```

Output:

```text
pledgebook/docs/api-verification.md
pledgebook/docs/claude-review-handoff.txt
pledgebook/docs/progress/phase-0.md
```

```text
git status --short -- pledgebook
```

Output:

```text
?? pledgebook/
```

```text
rg -l "Dictation|Sync API|HARD STOP 1|not in the runtime path" pledgebook/docs
```

Output:

```text
pledgebook/docs/claude-review-handoff.txt
pledgebook/docs/progress/phase-0.md
pledgebook/docs/api-verification.md
```

## Review

**Pending.** Jenny is the reviewer if no separate reviewer agent is available. Builder has not marked Phase 0 complete.


## Continuation — live account checks, 2026-09-27

The previous command records above are historical. This continuation supersedes earlier statements that no Realtime/Voice Agent requests were made and that Jenny must locate model settings.

Command run from `/Users/user/pledgebook`:

```sh
python3 scripts/phase0_probe.py accounts
```

The first attempt failed because the restricted shell could not resolve service hostnames. That failure is preserved in `docs/evidence/phase-0/20260927T213518326706Z-accounts.json`. The command was rerun with approved network access.

Actual output from the network-enabled run (credentials redacted by the script):

```text
{"check": "voice_agent_token", "method": "GET", "url": "https://agents.assemblyai.com/v1/token", "http_status": 200, "response": {"token": "[REDACTED]", "expires_in_seconds": 60}, "ok": true, "elapsed_ms": 1014.54, "limits": "Token creation only; no synthesized voice, call, or session started. Token redacted."}
{"check": "realtime_handshake", "url": "wss://streaming.assemblyai.com/v3/ws", "query": {"speech_model": "universal-3-5-pro", "sample_rate": 16000, "prompt": "English speech: a master of ceremonies announces invented donor names and pledged amounts in naira at a Nigerian fundraiser.", "keyterms_prompt": "[\"Chief Emeka Okonkwo\"]"}, "audio_sent": false, "events": [{"type": "Begin", "id": "8c0825fc-bda7-454c-ac74-db43218a3bc2", "expires_at": 1790555745, "configuration": {"model": "universal-3-5-pro", "mode": "balanced", "api_version": "2025-05-12", "speaker_labels": false, "redact_pii": false, "filter_profanity": false, "domain": null, "voice_focus": null}}, {"type": "Termination", "audio_duration_seconds": 0, "session_duration_seconds": 2}], "sent_messages": [{"type": "UpdateConfiguration", "keyterms_prompt": ["Chief Emeka Okonkwo", "Aisha Bello"]}, {"type": "Terminate"}], "ok": true, "limits": "Without spoken audio this verifies connection only, not recognition or the effect of updating names.", "elapsed_ms": 3572.2}
{"check": "gateway_documented_example_model", "method": "POST", "url": "https://llm-gateway.assemblyai.com/v1/chat/completions", "http_status": 400, "response": {"metadata": {"errors": ["Your account does not have access to this LLM Gateway model"]}, "request_id": "72de7ef2-a4b4-4037-a900-6092c0fad594", "message": "invalid request body", "code": 400}, "ok": false, "elapsed_ms": 1219.63, "request_body": {"model": "gemini-2.5-flash-lite", "max_tokens": 32, "messages": [{"role": "user", "content": "Return a JSON object with ok set to true."}], "response_format": {"type": "json_schema", "json_schema": {"name": "access_check", "strict": true, "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": false}}}}}
Evidence: docs/evidence/phase-0/20260927T213548973343Z-accounts.json
```

Exit code: 1, deliberately reporting the Gateway denial even though the other two checks succeeded.

What this establishes:

- Realtime accepts this key and `speech_model=universal-3-5-pro`, returning actual Begin and Termination messages. The measured session duration was 2 seconds, audio duration 0. These are account-check measurements, not product latency or accuracy results.
- A key-term update was sent and no error was observed before termination. This does not prove the names changed recognition; only recorded speech can test that.
- Voice Agent token issuance with Bearer authorization returned HTTP 200. Token creation does not demonstrate tool calling or a working conversation. No voice session or generated speech was started.
- The additional documented `gemini-2.5-flash-lite` model was also denied. Optional Gateway access remains unconfirmed; no owner model-selection task is needed.
- `scripts/phase0_probe.py audio --audio PATH --expected WORDS` is prepared to record a real Sync call and a paced Realtime transcription. That mode has not run, because no human audio file exists in the project.

Sources rechecked:

- https://www.assemblyai.com/docs/streaming/guides/streaming_transcribe_audio_file
- https://www.assemblyai.com/docs/streaming/updating-configuration-mid-stream
- https://www.assemblyai.com/docs/voice-agents/voice-agent-api/browser-integration
- https://www.assemblyai.com/docs/llm-gateway/structured-outputs
- https://www.assemblyai.com/docs/voice-agents/voice-agent-api/voices

The literal ban on synthetic voices conflicts with the requested speaking Voice Agent. No speech was generated. See `docs/spec-clarifications.txt` for this and the other grouped decisions at HARD STOP 1. The current voice catalog does not list the earlier suggested `ivy`; that old documentation claim is withdrawn.

Remaining at this point: Paystack account readiness and independent review. The speech evidence and voice-agent decision are complete. Phase 0 is marked **ready for review**, not self-approved.


## Continuation — Jenny's real recording, 2026-09-28 Africa/Lagos

Jenny supplied `/Users/user/Downloads/Voice 260927_194623.wav`. File inspection returned mono PCM16 at 48 kHz, 70.4 seconds, 6,758,478 bytes. The original was left in Downloads. A 6.4-second excerpt (4.5–10.9 seconds) was resampled to 16 kHz in `eval/private/phase-0/`, which Git ignores. No synthetic audio was created. The excerpt contains the first pledge as confirmed by actual AssemblyAI word timings. The exact words spoken have not yet been independently supplied by Jenny, so no accuracy score is claimed.

Actual commands and output:

```sh
file '/Users/user/Downloads/Voice 260927_194623.wav'
ffprobe -v error -show_entries format=duration,size -show_entries stream=codec_name,sample_rate,channels,bits_per_sample -of json '/Users/user/Downloads/Voice 260927_194623.wav'
```

```text
/Users/user/Downloads/Voice 260927_194623.wav: RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit, mono 48000 Hz
codec_name=pcm_s16le; sample_rate=48000; channels=1; bits_per_sample=16; duration=70.400000; size=6758478
```

```sh
python3 scripts/phase0_probe.py sync --audio '/Users/user/Downloads/Voice 260927_194623.wav'
```

First attempt: ConnectError `[Errno 8] nodename nor servname provided, or not known`; exit code 1, in `eval/private/phase-0/20260927T235453413872Z-sync.json`. Retried with network access. Actual stdout:

```text
{"check": "sync_real_audio", "http_status": 200, "ok": true, "elapsed_ms": 8691.01, "response_keys": ["text", "words", "confidence", "audio_duration_ms", "session_id", "request_time_ms"], "request_time_ms": 7884.14624001598, "audio_duration_ms": 70400, "word_count": 85}
Evidence: eval/private/phase-0/20260927T235518497729Z-sync.json
```

```sh
ffmpeg -hide_banner -loglevel error -ss 4.5 -t 6.4 -i '/Users/user/Downloads/Voice 260927_194623.wav' -ac 1 -ar 16000 -c:a pcm_s16le '/Users/user/pledgebook/eval/private/phase-0/pledge-1-4p5-to-10p9.wav'
```

Output: none; exit code 0. `ffprobe` showed PCM16 mono 16 kHz, 6.4 seconds, 204,878 bytes.

```sh
python3 scripts/phase0_probe.py audio --audio eval/private/phase-0/pledge-1-4p5-to-10p9.wav
```

First attempt: Sync ConnectError and Realtime gaierror, both DNS restriction, exit code 1; preserved in `eval/private/phase-0/20260927T235544044399Z-audio.json`. Network-enabled retry stdout:

```text
{"check": "sync_real_audio", "http_status": 200, "ok": true, "elapsed_ms": 1594.71, "response_keys": ["text", "words", "confidence", "audio_duration_ms", "session_id", "request_time_ms"], "request_time_ms": 934.3982189893723, "audio_duration_ms": 6400, "word_count": 9}
{"check": "realtime_audio", "ok": true, "elapsed_ms": 11427.2, "response_keys": [], "request_time_ms": null, "audio_duration_ms": null, "word_count": 0, "event_types": ["Begin", "SpeechStarted", "Turn", "Turn", "Turn", "SpeechStarted", "Turn", "Turn", "Turn", "SpeechStarted", "Turn", "Turn", "Termination"]}
Evidence: eval/private/phase-0/20260927T235610619235Z-audio.json
```

The verification script was then updated to record event arrival times. One network-enabled timed rerun stdout:

```text
{"check": "sync_real_audio", "http_status": 200, "ok": true, "elapsed_ms": 1818.81, "response_keys": ["text", "words", "confidence", "audio_duration_ms", "session_id", "request_time_ms"], "request_time_ms": 945.1934029930271, "audio_duration_ms": 6400, "word_count": 9}
{"check": "realtime_audio", "ok": true, "elapsed_ms": 11272.09, "response_keys": [], "request_time_ms": null, "audio_duration_ms": null, "word_count": 0, "event_types": ["Begin", "SpeechStarted", "Turn", "Turn", "Turn", "SpeechStarted", "Turn", "Turn", "Turn", "SpeechStarted", "Turn", "Turn", "Termination"]}
Evidence: eval/private/phase-0/20260927T235708681413Z-audio.json
```

Verbatim speech results from the short excerpt: Sync `Chief Emeka Okonkwo, ₦250,000. Make a clap for him.` Realtime finalized `Chief Emeka Okonkwo.` as turn 0 and `250,000 naira.` as turn 1. A non-final live turn briefly read `200,000.` at 4,947 ms after the connection began. Realtime finalized the correct amount at 6,496 ms after the connection began. Therefore the name and amount must be paired across turns and non-final text cannot become a settled financial amount. The time from speech to on-screen display has **not** been measured; there is no screen or extractor yet.

Sync returned nine words with word `start` and `end` milliseconds for the excerpt. The public guide's endpoint `/v1/transcribe` and the request fields `prompt`, `keyterms_prompt`, and `timestamps` all worked in a real call. The first 70.4-second request took 8.69 seconds end to end; the two 6.4-second requests took 1.59 and 1.82 seconds. This meets the Phase 0 question of whether a 5–15-second clip can recheck in roughly 10 seconds in this environment, but only for this one excerpt and these two requests. The results do not establish benchmark accuracy or performance in production.

Full response payloads are in ignored private evidence while the source recording's publication status is unknown. This phase report includes the actual command output, measured durations, and only a short excerpt matching the invented names in the spec. No recording was committed or shared publicly.

Open owner-specific items: Paystack test-mode access and the decisions in `docs/spec-clarifications.txt`. Technical items: Voice Agent conversation/tool events cannot be exercised under the spec's literal ban on generated voices until Jenny resolves that contradiction. Application code remains on hold at the Phase 0 HARD STOP.

## Continuation — Voice Agent check and owner decisions, 2026-09-28 Africa/Lagos

Jenny decided that generated speech is permitted only for the clearly disclosed automated assistant. All MC recordings, benchmark recordings, and donor speech remain real human recordings. Jenny also confirmed that she does not have Paystack test mode yet. Paystack stays disabled and no payment claim will be shown as working until a separate Paystack account and test key exist.

The builder ran:

```sh
python3 scripts/phase0_voice_probe.py --audio eval/private/phase-0/pledge-1-24k.wav
```

The first run hit the same restricted-shell DNS failure. The approved network retry returned:

```text
{"ok": true, "token_http_status": 200, "event_counts": {"session.updated": 1, "session.ready": 1, "reply.started": 3, "reply.audio": 903, "transcript.agent.delta": 18, "transcript.agent": 2, "reply.done": 3, "input.speech.started": 1, "transcript.user.delta": 5, "input.speech.stopped": 1, "transcript.user": 1, "tool.call": 1, "session.ended": 1}, "assistant_audio_frames": 903, "tool_calls": 1, "error_type": null, "error": null, "elapsed_ms": 23730.0}
Evidence: eval/private/phase-0/20260928T000213440991Z-voice.json
```

The agent used the documented `anna` voice, announced itself, received the real recording, produced a `transcript.user` event, called the registered tool, accepted the JSON `tool.result`, produced a final reply, and ended cleanly. The tool argument was `Emeka Okonkwo` while the transcript contained `Chief Emeka Okonkwo`; this is a measured name-loss case. Pledgebook must retain the original transcript and require its own matching rules before recording a person. The verification tool itself created no pledge or payment record.

Phase 0 review findings:

- Sync and Realtime account access, real speech responses, timestamps, and short-clip response times are evidenced in the 2026-09-28 sections above.
- Voice Agent token, generated assistant speech, structured tool call, tool result, and clean teardown are evidenced in the private voice response file.
- The Gateway remains optional and disabled. The tested Gemini models were denied; Qwen was reachable but rejected the requested JSON-schema format. No Pledgebook feature depends on it.
- Paystack is explicitly unavailable until Jenny creates that separate account. The app must say payments are not configured and must not pretend to redeem pledges.

## Owner update — 2026-09-28 Africa/Lagos

Jenny has now created the separate Paystack Test Mode account and saved its
`sk_test_...` key locally. The payment integration was enabled after this
owner decision. A real initialization call returned an authorization URL and
reference; an unfinished checkout verified as `abandoned` and stayed
unredeemed. The historical notes above describe the state before this update.
- The builder is proceeding with Phase 1–3 implementation while this report remains ready for independent review. The builder does not mark the review as passed.
