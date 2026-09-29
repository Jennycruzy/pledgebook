# Evaluation status

No benchmark has been run. There are no accuracy, wrong-person, latency,
time-saving, fulfilment or cost numbers for public use yet.

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

## The benchmark still to record

- At least two different real speakers, with and without background music,
  reading scripts with known answer keys, including unlisted names said twice.
- Report, in this order: **wrong-person count**, names and amounts right, lines
  correctly flagged, time from speech to the live screen, time to a rechecked
  record, and corrected names recognised on their next mention.
- Every failure is reported alongside the result before any figure is used
  publicly.
