# Phase 4 — guest list and walk-in test

**Builder status:** Guest-list groundwork is built. The HARD STOP test is
pending Jenny's real walk-in recording.

## Built

- Demo events load 61 clearly invented guests.
- A CSV import endpoint and browser control accept `title, name, phone, email,
  consent_to_contact, group` columns.
- Guests can be added during an event, including a walk-in and contact consent.
- The setup screen shows how many names fit in the verified Sync key-term
  limits (100 terms / 8,000 characters) and visibly lists the overflow count.
- The confirming pass reads the current guest list when it starts, so a guest
  added during the event is available to that next recheck. The active
  Realtime session keeps its initial terms; this is recorded as a limitation
  until the live update behavior is tested with a walk-in.

## Not done

- Jenny must record a real script containing at least one name not on the list.
- The result must answer whether Realtime turns that walk-in into a listed name
  and set the matching cut-offs from the observed result.
- No matching cut-off has been tuned from the supplied recording. The current
  matcher remains conservative and flags uncertain names.

## HARD STOP 2

Do not use a walk-in recognition result in public claims or tune the matching
rules until the real walk-in recording is run and Jenny decides from the
evidence.

## Review

Pending independent review, the real walk-in recording, and Jenny approval.
