# Phase 11 — tests, CI, and documentation

**Builder status:** Local test and documentation slice ready for review.

## Built

- CircleCI configuration runs the Python tests, Python compilation, and browser
  JavaScript syntax check in separate clean jobs.
- The repository contains the MIT license, API verification record,
  architecture, privacy, evaluation status, judge guide, and limitations.
- The current pure-rule suite has 28 tests covering amounts, currencies,
  in-kind gifts, ambiguous amounts, name matching, anonymous donors, and
  adjacent-turn pairing.
- No test returns a hand-written transcription or payment response. Network
  evidence remains in the committed verification records, while private audio
  and live response payloads stay ignored.

## Commands and actual output

```sh
python3 -m pytest -q
python3 -m compileall -q app scripts
node --check web/app.js
```

```text
28 passed in 0.48s
the compile and JavaScript checks completed successfully
```

The previous GitHub Actions run failed immediately and exposed no job steps in
the public run record. Its workflow file has been removed. CircleCI is now the
only repository CI configuration; it must be enabled for this repository in
Jenny's CircleCI account before its first hosted run.

## Not done

- Recorded-response replay tests for all live API failure cases.
- Independent setup run by someone who did not write the code.
- Public repository and signed-out URL check.
- Benchmark results and submission media.

## Review

Pending independent review and Jenny approval.
