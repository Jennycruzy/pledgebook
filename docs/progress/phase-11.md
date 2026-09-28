# Phase 11 — tests, CI, and documentation

**Builder status:** Local test and documentation slice ready for review.

## Built

- GitHub Actions workflow runs the Python tests, Python compilation, and
  browser JavaScript syntax check.
- The repository contains the MIT license, API verification record,
  architecture, privacy, evaluation status, judge guide, and limitations.
- The current pure-rule suite has 28 tests covering amounts, currencies,
  in-kind gifts, ambiguous amounts, name matching, anonymous donors, and
  adjacent-turn pairing.
- No test returns a hand-written transcription or payment response. Network
  evidence remains in the committed verification records, while private audio
  and live response payloads stay ignored.

## Not done

- Recorded-response replay tests for all live API failure cases.
- Independent setup run by someone who did not write the code.
- Public repository and signed-out URL check.
- Benchmark results and submission media.

## Review

Pending independent review and Jenny approval.
