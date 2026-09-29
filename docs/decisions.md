# Product decisions

**Generated speech only for the disclosed assistant.** All MC, donor and test
recordings are real human voices. The voice assistant uses AssemblyAI generated
speech, introduces itself as automated, and is labelled as such on the page.

**The assistant runs on the guest's device, not as a phone call.** Pledgebook
does not place automated calls. The guest opens their private page and chooses
to talk. Staff who call guests do so from their own phones and log the result.
This keeps the assistant honest about what it is and avoids unsolicited
automated calls.

**When the live reading and the recheck disagree.** A disagreement about the
person, the currency or the number of amounts clears the guest and sends the
line to a person. A clean amount correction by the recheck is shown as
*Rechecked — changed* with both readings visible; whether that should also
require a person is a question for the benchmark.

**Repeated announcements.** MCs repeat pledges for applause. Within one
listening session an identical repeat within a minute is logged, not counted. A
different amount from the same guest is kept as its own flagged line so a
person chooses *keep both* or *replace the earlier one*; nothing is silently
overwritten.

**Too many guest names.** Realtime and Sync accept up to 100 key terms and 8,000
characters. The guest screen shows exactly how many names are included and how
many are beyond the limit; overflow names are still matched after
transcription. Names are never silently truncated.

**Usage limits.** Each organisation has daily limits on listening time, voice
assistant conversations, new events and emails, so one account cannot use up
the service allowance. The owner sees current usage in Settings.

**Sample events are separate.** Invented guests and the owner's sample
recording are only available in events created as samples, which are labelled
everywhere and deleted after 24 hours.

**Hard sentences go to a person.** AssemblyAI's hosted language-model service
did not return the required structured output for the tested account models,
so ambiguous speech is handled by rules and human review rather than another
provider.
