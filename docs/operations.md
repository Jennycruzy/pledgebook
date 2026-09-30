# Operating Pledgebook

## Configuration (`.env`, never committed)

| Setting | Purpose |
|---|---|
| `ASSEMBLYAI_API_KEY` | Realtime, Sync and Voice Agent. Required for listening. |
| `PAYSTACK_SECRET_KEY` | `sk_test_…` for test mode, `sk_live_…` for real payments. Empty turns online payment off. |
| `PLEDGEBOOK_PUBLIC_URL` | The public HTTPS address. Used in guest links, invitations, the Paystack return address and secure cookies. |
| `PLEDGEBOOK_DATA_DIR` | SQLite database and audio. |
| `PLEDGEBOOK_SAMPLE_AUDIO` | Optional owner-approved real recording for sample events. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Optional email for pledge pages and invitations. Port 465 uses TLS; other ports use STARTTLS. |
| `PLEDGEBOOK_DAILY_AUDIO_MINUTES` | Listening minutes per organisation per day (default 240). |
| `PLEDGEBOOK_DAILY_ASSISTANT_SESSIONS` | Voice assistant conversations per organisation per day (default 30). |
| `PLEDGEBOOK_DAILY_EVENTS` | New events per organisation per day (default 30). |
| `PLEDGEBOOK_DAILY_EMAILS` | Emails per organisation per day (default 200). |

## Paystack

1. In the Paystack dashboard, under Settings → API Keys & Webhooks, set the
   webhook URL to `<PLEDGEBOOK_PUBLIC_URL>/api/paystack/webhook`. The owner's
   *Settings → Usage and services* page shows the exact address.
2. Test mode needs only the `sk_test_` key. Pages then show a test-mode notice
   and the published test card.
3. **Moving to real payments:** complete Paystack business verification, replace
   the key with the `sk_live_` key, set the webhook in live mode too, restart,
   and make one small real payment to yourself. The test notices disappear
   automatically when the key is live.

## Deployment on the current server

The service runs from this working tree as `pledgebook.service` (uvicorn on
`127.0.0.1:8400`) behind nginx with a Let's Encrypt certificate
(`deploy/nginx-pledgebook.conf`). nginx must pass `X-Real-IP`, which the rate
limiter uses. To deploy:

```sh
cd ~/pledgebook
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart pledgebook
curl -fsS https://pledgebook.isobars.xyz/healthz
```

The database schema upgrades itself on start without deleting data.

## Backups

Everything lives in `PLEDGEBOOK_DATA_DIR`. Back up the SQLite file with its
online backup command, for example nightly:

```sh
sqlite3 data/pledgebook.sqlite3 ".backup 'backups/pledgebook-$(date +%F).sqlite3'"
```

Audio folders under `data/audio/` can be copied as files.

## Retention job

Every hour the server deletes expired sample events, removes audio for events
that ended more than the organisation's retention period ago, and clears
expired sign-in sessions.
