# Current limits

This is the build status as it stands, not a list of claims.

## Measured and working

- Microphone capture through the browser, Realtime transcription, Sync
  rechecks and evidence clips were run end to end on the current build with a
  real human recording: both listed guests were confirmed with the right
  amounts, and every unknown name or ambiguous amount was flagged for review.
- A real Paystack test-mode checkout was created from a guest pledge page for a
  part payment and opened on `checkout.paystack.com`.
- The automated test suite covers access control, roles, lifecycle, guest
  administration, review rules, repeat detection, payment crediting (including
  duplicates and partial payments), webhooks and retention.

## Not yet demonstrated

- **A completed test-card payment on the public deployment** with a signed
  webhook turning a pledge to *Paid in full*. The code path is tested with a
  stand-in Paystack; the live run needs the owner's browser.
- **A full spoken conversation with the guest-side voice assistant** in a
  browser. The Voice Agent session, generated speech and tool call were verified
  with a script; the in-page conversation still needs a manual run.
- **Recognition after a correction.** The listening list is updated during the
  session, but no recording has yet shown an unlisted name recognised on its
  second mention.
- **Accuracy.** No benchmark has been recorded. See `docs/evaluation.md`.

## By design or by configuration

- **Payments are in Paystack test mode** on the public deployment. Real money
  needs a verified Paystack business and a live key (`docs/operations.md`).
- **Email** needs SMTP settings; without them staff send pages by WhatsApp,
  SMS or a copied link from their own phones.
- **No automated phone calls.** Staff call from their own phones and log the
  outcome. The voice assistant runs only on the guest's own device, from their
  private pledge page.
- **Languages.** Nigerian Pidgin, Igbo and Yoruba are not claimed as supported.
- **Hard sentences** go to a person. The optional AssemblyAI language-model
  service did not return the required structured output for the tested
  account models, so it is not used.
- **Single server.** SQLite and in-process live updates suit one server per
  deployment. Running several servers would need a shared database and message
  bus.
- **Naira only** for online payment. Pledges heard in other currencies are
  recorded and totalled separately and settled offline.
