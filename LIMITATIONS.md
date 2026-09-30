# Current limits

This is the build status as it stands, not a list of claims.

## Measured and working

- Microphone capture through the browser, Realtime transcription, Sync
  rechecks and evidence clips were run end to end on the current build with a
  real human recording: both listed guests were confirmed with the right
  amounts, and every unknown name or ambiguous amount was flagged for review.
- 21 attempts to break the access, privacy, assistant and payment rules were
  all refused on the public deployment (`eval/try_to_break.py`).
- A real Paystack test-mode checkout was created from a guest pledge page for a
  part payment and opened on `checkout.paystack.com`.
- The automated test suite covers access control, roles, lifecycle, guest
  administration, review rules, repeat detection, payment crediting (including
  duplicates and partial payments), webhooks and retention.
- The fixed-answer-key benchmark used ten real recordings from two adult
  speakers, quiet and with background music. Across 70 spoken pledges it had
  zero wrong-person credits, zero accepted wrong amounts, zero misses and zero
  double-counted repeats. Both corrected names were recognised on their next
  mention. Forty-eight of 60 clear lines were automatic; 12 required an usher.

- **Guest voice assistant and payment, end to end, on the public deployment
  (30 September 2026).** On a real pledge page the owner first told the
  assistant she was someone else: identity was refused and the session ended
  as `wrong_person` without the pledge being discussed. In a second session
  she confirmed her identity, the assistant opened checkout, and she paid
  ₦100,000 with a Paystack test card. Paystack's signed webhook credited it and
  the pledge became *Paid in full* (reference `pb-5a5425bdd3-57-7fd50eb5f2`).

## Not yet demonstrated

- **Usher workload.** The benchmark safely sent 12 of 60 clear lines to a
  person, and one difficult music recording produced one additional flagged
  fragment. This is safe but not hands-off automation. In 7 of the 12 the
  Sync recheck had the right record for the usher to confirm; it corrected no
  line automatically. See `docs/evaluation.md`.
- **Stored pledge-page links.** Invitation tokens are stored hashed, but
  private pledge-page tokens are stored as issued, so a copy of the database
  would expose open pledge pages.

## By design or by configuration

- **Payments are in Paystack test mode** on the public deployment. Real money
  needs a verified Paystack business and a live key (`docs/operations.md`).
- **Email** is sent through SMTP, which is configured on the public
  deployment. A self-hosted copy without SMTP settings falls back to WhatsApp,
  SMS or a copied link sent from staff phones.
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
