# Pledgebook architecture

```text
 MC microphone (staff browser)        WAV upload / sample recording
        │ 16 kHz PCM over WebSocket            │ normalised to 16 kHz mono
        ▼                                      ▼
 ┌──────────────────────────── FastAPI server ────────────────────────────┐
 │ accounts · roles · rate limits · same-origin write check               │
 │                                                                        │
 │ ListeningSession ──► AssemblyAI Realtime (key terms, live updates)     │
 │   │ audio appended to disk          │ final turns                      │
 │   ▼                                 ▼                                  │
 │ evidence clip per pledge ◄── pairing + extraction ──► SQLite ledger    │
 │   │                                                   │  audit log     │
 │   └──► AssemblyAI Sync (clip, names, timings) ──► reconcile ──► review │
 │                                                                        │
 │ Server-sent events → every open screen rebuilds its own role's view    │
 └────────────────────────────────────────────────────────────────────────┘
        │ private pledge page link (WhatsApp / SMS / email / copy)
        ▼
 Guest's own phone ──► Paystack checkout ──► signed webhook / return check
        │
        └──► AssemblyAI Voice Agent (short-lived token issued per page)
```

## Modules

| File | Responsibility |
|---|---|
| `app/auth.py` | Password hashing (scrypt), cookie sessions, invites, role permissions, rate limiter |
| `app/core.py` | Shared services, usage limits, the per-role event view, retention |
| `app/capture.py` | Listening sessions, disk-backed audio, pledge creation, repeat handling, Sync reconciliation |
| `app/extractor.py`, `amounts.py`, `names.py` | Rules that find names and amounts and match guests conservatively |
| `app/followup.py` | Pledge pages, deliveries, call logs, payments, webhook, guest-side assistant tools |
| `app/delivery.py` | Message text, SMS/WhatsApp links, SMTP email |
| `app/sample.py` | Sample events with invented guests, kept apart from real events |
| `app/main.py` | Accounts, organisation, staff, events, lifecycle, guests, review, capture socket, reports |
| `web/app.js` | Staff app (hash routes: `#/events`, `#/events/<id>/<tab>`, `#/settings`, `#/invite/<token>`) |
| `web/pay.js` | The guest's private pledge page and voice assistant |

## Roles

| Permission | Owner | Admin | Usher |
|---|:-:|:-:|:-:|
| See the live screen and register | ✓ | ✓ | ✓ |
| Resolve lines that need checking | ✓ | ✓ | ✓ |
| Change an accepted pledge, run the event, listen | ✓ | ✓ | |
| Manage guests and see contact details | ✓ | ✓ | |
| Follow-up, payments, settlement, exports, activity | ✓ | ✓ | |
| Organisation settings and staff | ✓ | | |

Admins may invite ushers; only owners invite admins. An event outside a
member's organisations answers 404.

## Pledge states

`provisional` (heard live) → `confirmed` or `corrected` (Sync agreed, or changed
the amount) or `flagged` (a person must decide) → `redeemed` once payments
received reach the pledged amount. `rejected` lines stay in the register with a
reason. After a review action the line stays flagged if anything else is still
unclear.

## Rules that protect the ledger

- Timestamps restart with each listening session, so repeats are only compared
  within the same session. An identical announcement repeated within a minute is
  logged and not counted twice; a different amount from the same guest becomes
  its own flagged line (*keep both* or *replace the earlier one*).
- When the live reading and the recheck disagree about the person or currency,
  the guest is cleared and a person decides.
- The guest page plays audio only when the clip contains exactly one guest name
  and one clear amount.
- A payment is marked successful with a conditional update, so the webhook and
  the return check cannot both credit it. It is verified against its own amount
  and currency; the pledge is paid in full only when received reaches the
  current pledged amount.
- Rejecting a pledge, moving it to another guest, withdrawing consent, a guest
  dispute or opt-out all close its pledge page.
