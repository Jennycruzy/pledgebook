# Measured service behaviour

Facts recorded against the real AssemblyAI and Paystack accounts, with what each
check does and does not prove. Raw responses containing transcripts of the
owner's voice stay in the Git-ignored `eval/private/` folder.

## AssemblyAI Sync (27–28 September 2026)

- `POST https://sync.assemblyai.com/v1/transcribe`, raw key in `Authorization`,
  `X-AAI-Model: universal-3-5-pro`, multipart `audio` plus a JSON `config` with
  `prompt`, `keyterms_prompt` and `timestamps: true`.
- The owner's 70.4-second recording (mono 16-bit, 48 kHz) returned HTTP 200 with
  85 timestamped words in 8.69 seconds end to end.
- A 6.4-second excerpt returned nine timestamped words in **1.59 s and 1.82 s**
  end to end (server-reported 934 ms and 945 ms). Individual requests, not a
  latency guarantee.
- Limits from the Sync guide: 80 ms to 120 s per clip, 40 MB, up to 100 key
  terms / 8,000 characters. Pledgebook caps uploads at 120 s and sends short
  per-pledge clips.

## AssemblyAI Realtime

- `wss://streaming.assemblyai.com/v3/ws` with `speech_model=universal-3-5-pro`,
  16 kHz PCM, a situation prompt and guest key terms returned `Begin`, `Turn`
  and `Termination` messages with word timings.
- On the excerpt the name and amount finalised in separate turns, and a
  non-final reading of `200,000` became a final `250,000 naira`. Pledgebook
  therefore pairs adjacent final turns and never records non-final text.
- `{"type": "UpdateConfiguration", "keyterms_prompt": [...]}` is accepted
  mid-session. That proves the message is accepted, not that recognition
  improves; see `LIMITATIONS.md`.
- The browser microphone path on the current build (29 September 2026) streamed
  the real recording through a fake Chromium microphone for 75 seconds: seven
  lines, both listed guests confirmed with the right amounts, five flagged, none
  credited to the wrong guest.

- **A pairing error found on the owner's recording (29 September 2026).**
  Realtime ended one turn with the previous donor's amount and the next
  donor's name: "₦500,000. Brother Segun Ogunleye." With Segun on the guest
  list, Pledgebook credited him ₦500,000; the Sync clip contained the same
  words, so the recheck agreed. He had pledged ₦10,000 (the ₦500,000 was
  Pastor Kelechi Amadi's). An amount spoken before a name in one turn now
  closes the earlier announcement instead, and any name or amount left
  without a partner becomes a line for a person. On the same recording
  afterwards Segun's line went to review with the recheck reading
  "Brother Segun Ogunleye, 10,000". Regression tests keep both cases.
- Timing on that run, measured from when the words were spoken: live screen
  1.6 s and 2.3 s, rechecked record 2.2 s and 2.8 s for the two cleanly
  paired pledges (local server, the recording streamed at real speed).

## AssemblyAI Voice Agent

- Token: `GET https://agents.assemblyai.com/v1/token` with a Bearer key returned
  HTTP 200. Pledgebook issues tokens only from a valid guest pledge page, with
  per-page and per-organisation daily limits.
- A scripted session with the `anna` voice and one tool produced
  `session.ready`, assistant audio, a user transcript, a `tool.call`, the
  matching `tool.result` and `session.ended`.
- The tool argument dropped the guest's title ("Emeka Okonkwo" for "Chief Emeka
  Okonkwo"), so the server never trusts assistant text for identity or amounts;
  the page and server hold both.

## Paystack (test mode)

- `POST /transaction/initialize` returned an authorization URL on
  `checkout.paystack.com`; `GET /transaction/verify/:reference` returned
  `abandoned` for an unpaid checkout, which correctly left the pledge unpaid.
- On the current build, a guest pledge page created a real test-mode checkout
  for a ₦40,000 part payment of a ₦100,000 pledge.
- A webhook without a valid HMAC-SHA512 signature returns HTTP 401.
- Still to record on the public deployment: a completed test-card payment and a
  signed webhook delivery.

## Attempts to break the safety rules

`eval/try_to_break.py` runs 21 attempts against a live deployment: signed-out
and cross-organisation reads, a cross-site form post, a reused invitation, an
usher reading contacts, exporting, ending the event or changing a confirmed
pledge, guessed pledge-page links, voice-assistant tokens without a page, the
assistant recording or opening checkout before identity is confirmed, the
assistant trying to change the amount, paying more than was pledged, a page
after rejection, and a forged Paystack notification. On the public deployment
on 29 September 2026 all 21 were refused; the report is in `eval/results/`.

## Not used

AssemblyAI's hosted language-model service denied two documented models for
this account and a third rejected the required JSON-schema output, so it is
not part of the product.
