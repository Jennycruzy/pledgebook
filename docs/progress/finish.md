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
| 1. Deploy and finish payment | Not started | — |
| 2. Learn names during the event | Not started | — |
| 3. Show the exact pledge moment | Not started | — |
| 4. Big screen polish | Not started | — |
| 5. Complete the judge path | Not started | — |
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
