# Privacy

**What is stored.** Accounts (name, email, scrypt password hash), organisation
settings, event details, the guest list the organiser supplies, pledge text, a
short evidence clip per pledge, follow-up and payment records, and an activity
log naming who made each change. Paystack card details never reach Pledgebook.

**Who sees it.** Only members of the organisation that owns an event. Ushers see
the review queue and register but never guest phone numbers or emails.
Invitations work once and expire after seven days; removing a member ends their
access at once.

**Consent.** A guest is only followed up when consent is recorded. Withdrawing
consent closes any open pledge page. Guests can stop reminders from their own
page, and that choice is honoured by every follow-up action.

**Guest pages.** Each page has an unguessable link, expires (14 days by default,
set per organisation) and closes when the pledge is rejected, reassigned or
disputed. The page shows audio only when it contains no other guest's name.
Pages send no referrer to other sites and are marked not to be indexed.

**Retention.** Audio clips are deleted automatically a set number of days after
an event ends (90 by default, set per organisation). Ledger, payment and
activity records remain until the organiser deletes the event, which removes
everything. Sample events are deleted after 24 hours. Raw microphone audio is
written to disk only while a session is open and deleted when it closes; only the
per-pledge clips are kept.

**Processors.** AssemblyAI transcribes audio and runs the voice assistant.
Paystack processes payments. Email, if configured, is sent through the
organiser's SMTP provider. QR codes are generated on the server, so invitation
links are not sent to any outside service.

**Languages.** Pledgebook does not claim to understand Nigerian Pidgin, Igbo or
Yoruba. It finds names and amounts in mixed English speech and asks a person
when that is not enough.
