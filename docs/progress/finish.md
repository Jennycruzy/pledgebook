# Finishing work

## Verified submission close

- Source: [official AssemblyAI Voice Agent Hackathon page](https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon)
- The event schedule says: **30 September 2026, 3:00 PM Coordinated Universal Time — End of Submissions.**
- Exact close used for planning: **30 September 2026 at 15:00 UTC (16:00 WAT, Africa/Lagos).**
- The page headline also displays **“3:00 PM CUT.”** “CUT” is inconsistent with the explicit schedule line, so this record preserves the discrepancy and uses the schedule's UTC wording.
- Checked: **28 September 2026, Africa/Lagos.**

## Finishing stages

| Stage | Status | Evidence |
|---|---|---|
| 1. Deploy and finish payment | Deployed; payment still needs the owner's checkout | Public HTTPS health check and real WAV upload pass; Paystack browser payment pending |
| 2. Learn names during the event | Built; real before/after recording pending | Live-list update code and real AssemblyAI handshake |
| 3. Show the exact pledge moment | Built; public payment-page check pending | Safe clip checks on Jenny's real recording |
| 4. Big screen polish | Implemented; screenshot review pending | Public UI serves large totals, progress and state changes |
| 5. Complete the judge path | Implemented; timed stranger walk-through pending | Add-yourself, script, sample, QR, call and reset controls |
| 6. Benchmark | Not started | — |
| 7. README and repository front page | Not started | — |
| 8. Submission materials | Not started | — |

## Stage 1 — deployment

Status: **deployed; payment proof still needs the owner's browser and Paystack webhook setting.**

The isolated service is running on Jenny's Lightsail host at `127.0.0.1:8400`, behind nginx and a Let's Encrypt certificate. The public URL is:

`https://pledgebook.54-154-121-30.sslip.io/`

This hostname is a public DNS name that resolves to the server's static IP. It avoids changing another application on `isobars.xyz`; a branded subdomain can be added later if desired.

Commands and real output:

```text
git ls-remote origin refs/heads/main
276f7027a2af4fcffa7e48b53ae67936c305b720	refs/heads/main

sudo systemctl --no-pager --full status pledgebook.service
Active: active (running)
Uvicorn running on http://127.0.0.1:8400

curl -fsS https://pledgebook.54-154-121-30.sslip.io/healthz
{"ok":true,"assemblyai_configured":true,"paystack_configured":true,"version":"0.1.0"}

curl -L http://pledgebook.54-154-121-30.sslip.io/healthz
status=200 effective=https://pledgebook.54-154-121-30.sslip.io/ ip=54.154.121.30
```

The server environment contains the AssemblyAI and Paystack keys with values hidden from this record. The repository was searched before deployment; `.env` remains ignored and is not in the public tree.

The Paystack Test Mode webhook still must be set by the account owner to:

`https://pledgebook.54-154-121-30.sslip.io/api/paystack/webhook`

A complete test-card payment has not been claimed yet. The exact Paystack reference will be added here only after the browser checkout succeeds and the signed webhook plus server-side verification turn one pledge to `Redeemed`.

### Public request and real-recording smoke check

The first public POST check returned `422 body required` even though the same
request worked on the server. The cause was the nginx WebSocket upgrade header
being applied to every request, which dropped ordinary JSON and multipart
bodies. The nginx config now limits upgrade headers to `/ws/`; API requests use
the normal proxy location.

Commands and real output after the fix:

```text
sudo nginx -t
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful

POST https://pledgebook.54-154-121-30.sslip.io/api/events
HTTP/1.1 200 OK
{"event":{"id":"551acf90db84420e8867006c916d2598", ...}, "guests":[...], "pledges":[]}

POST https://pledgebook.54-154-121-30.sslip.io/api/events/551acf90db84420e8867006c916d2598/upload
HTTP/1.1 200 OK
{"accepted":true,"message":"The recording is being heard now. Watch the pledge list for updates."}
```

The upload was the real human recording supplied by Jenny at
`/Users/user/Downloads/Voice 260927_194623.wav` (70.4 seconds, 48 kHz mono).
AssemblyAI processed it on the deployed server. The resulting four pledge
records were:

```text
2 confirmed: ₦250,000 (Chief Emeka Okonkwo), ₦100,000 (Deaconess Ngozi Eze)
2 flagged: a clip with two amounts, and a currency disagreement
Pledged total: ₦350,000
Received total: ₦0
```

The temporary smoke event and its audio were deleted from the server after the
check. This is ingestion evidence, not a benchmark or a payment claim.

## Stage 2 — learning during the event

Status: **built; the required before/after walk-in recording is still pending.**

An active Realtime capture session is registered on the server. When a guest is
added or an usher resolves a flag, the server sends
`UpdateConfiguration` with the current guest terms to that session and writes a
`listening_list_updated` audit entry. Later pledges store the source pledge and
time in `recognised_from_pledge_id` and `recognised_at` when the guest came from
that correction.

Checks run:

```text
python3 -m compileall -q app
python3 -m pytest -q
28 passed in 0.22s
```

The API handshake with the real AssemblyAI account already accepted the same
`UpdateConfiguration` message; that evidence is in
[`docs/api-verification.md`](../api-verification.md). It did not contain a
walk-in recording, so no recognition improvement number is claimed.

## Stage 3 — private pledge moment

Status: **built; public browser payment proof is still pending.**

Payment links now receive an unguessable token and a 24-hour expiry. The private
page shows the event, guest, amount, verbatim words, a safe trimmed audio clip
when exactly one guest name and one amount are present, and the Paystack Test
Mode button. An adjacent or ambiguous pledge is shown as text instead of audio.

Real recording check using Jenny's private AssemblyAI excerpt:

```text
recheck_span_ms=[583, 5962]
safe_seconds=5.499
reason=Audio contains only this guest's rechecked name and amount.
```

The same helper refused the full multi-pledge clip with:
`Audio is not shown because the amount was not a single clear phrase.`

## Stages 4–5 — screen and judge path

Status: **implemented; a stranger's timed walk-through is still required.**

The deployed UI now includes large pledged/received totals, a progress bar,
new-pledge animation, spoken and Paystack-paid times when a verified payment
has a `paid_at`, the correction marker, a sample-recording button, an
add-yourself form that inserts the name into the MC script, a QR usher link,
walk-in and anonymous actions, private event URLs, a session summary, and
reset. The public page serves the new controls over HTTPS; a signed-out manual
walk-through remains an owner test rather than a claim.

## Stages 6–8

Status: **not claimed complete.** The deployed benchmark, owner-reviewed
wrong-person number, cover image, video, slides, and submission text still need
real recordings and the owner's final review. README and judge-guide copy now
point to the public URL and state the limits honestly.

## Continuous integration check

CircleCI is now the active repository check. Public CircleCI API output for
pipeline **#7**, commit `edbabc277fea77b7899e8f64e3ae70e897eea4ba`, reports
workflow `checks` **success** (checked 28 September 2026, 15:07 UTC). The old
GitHub Actions workflow is not used.
