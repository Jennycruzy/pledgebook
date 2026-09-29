# Evaluation status

The fixed-answer-key benchmark was run on the public deployment on 29 September
2026 using ten real recordings from two adult speakers. The complete generated
report is in `eval/results/20260929T230646Z/report.md`; its machine-readable
companion is `results.json` in the same folder.

## Final measured result

- 10 recordings and 70 spoken pledges.
- **0 wrong-person credits.**
- **0 wrong amounts accepted for the right person.**
- **0 unclear lines accepted without a person.**
- **0 missed pledges and 0 repeated announcements counted twice.**
- 48 of 60 clear lines reached the ledger without a person; 12 clear lines
  required an usher.
- All 10 lines designed to require a person were correctly flagged.
- One difficult music recording produced one additional flagged fragment; it
  was not credited.
- Spoken-to-live latency: median 3.2 s, p90 7.8 s (n=70).
- Spoken-to-rechecked latency: median 3.7 s, p90 8.3 s (n=70).
- For both speakers, the unlisted name corrected during script C was recognised
  live and spelled exactly on its second mention in the same session.

This measures the supplied scripts, speakers, room conditions and configured
₦10,000 event minimum. It is not a general speech-recognition accuracy claim.
The principal remaining cost is usher workload: 20% of otherwise-clear lines
required review.

## What has been observed

The owner's real 70.4-second recording has been run through the current build,
both as an uploaded recording and through the browser microphone path. With two
of its guests on the list, both were confirmed with the right amounts; five
other lines were flagged — unknown names, and clips where the MC said two
amounts in one breath. No line was credited to the wrong guest. This is one
recording read by one person, so it is engineering evidence, not an accuracy
result.

A later run of the same recording with a larger guest list exposed a
**wrong amount** credited to the right guest: an amount that closed one
announcement was paired with the next donor's name. That is fixed and kept as
a regression test; the details are in `docs/verification.md`.

## Running the benchmark

The kit is in `eval/benchmark/`: a 20-name guest list with deliberate near
names, three scripts (`scripts.md`), and an answer key written before any
recording. Record each script as described, then:

```sh
python eval/benchmark/run.py --base https://pledgebook.54-154-121-30.sslip.io \
    --email <owner email> recordings/*.wav
```

Each recording gets a fresh event. For script C the runner plays the usher and
adds the unlisted name as soon as it is flagged, while the same listening
session is still open. Add `--no-correction` for a control run without that
step. The report lists wrong-person credits first, then every outcome, what
Realtime and Sync each contributed, timing, the name-learning result, and
every line with its live and rechecked words.

## Reporting rule

Every failure remains in the generated report alongside the aggregate result.
Do not quote the automatic rate without also stating the zero-miscredit safety
result and the 12 clear lines that required a person.
