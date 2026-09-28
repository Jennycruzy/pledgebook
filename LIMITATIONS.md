# Current limits

This is an honest build status, not a list of claims.

- Paystack Test Mode is configured on the deployed server and checkout
  initialization plus pre-payment verification have been measured. A successful
  test-card payment, signed webhook delivery, and redeemed-state evidence are
  still outstanding.
- The optional AssemblyAI LLM Gateway is disabled because the tested account
  models did not provide the required structured response.
- The active Realtime session now receives an `UpdateConfiguration` message when
  a guest is added or an usher resolves a flag. A dedicated recording with an
  unlisted name said twice is still needed before claiming that recognition
  improved on the second mention.
- The supplied 70.4-second recording was a diagnostic run. It exposed merged
  turns and flags; it is not the Phase 9 benchmark and supplies no public
  accuracy number.
- The walk-in test and matching cut-off decision are still pending a real
  recording containing an unlisted name.
- The browser follow-up assistant has a real Voice Agent route and verified
  server tool behavior. A full browser conversation still needs a manual run.
- Nigerian Pidgin, Igbo, and Yoruba are not claimed as supported languages.
  Pledgebook extracts names and amounts when they survive mixed English speech.
- The public HTTPS deployment is live. The owner still must set the Paystack
  webhook, complete a browser test-card payment, run the signed-out payment
  check, record the benchmark, and make the submission media.
