## Context

Two defects, one shared root: **the same fact is declared in two places and the copies
disagree.**

`_DIGEST_KINDS` in `services/notifications.py` is a hand-maintained set of kind strings that
decides both the `Urgency` header and the `TTL` header. Every job already declares
`catch_up` — how stale its output may be before delivering it is worse than not delivering
it — and the two contradict each other today:

| Job | `catch_up` says | Headers say |
|---|---|---|
| `morning_brief` | *"by 11:30 or not at all"* (4h) | `TTL: 86400`, `Urgency: low` |
| `day_end_summary` | *"by midnight, so it lands on the day it describes"* (3h) | `TTL: 86400`, `Urgency: low` |
| `task_nudge` | superseded next hour (45m) | `TTL: 14400`, `Urgency: normal` |

The runner refuses to *run* a day-end summary three hours late because that would be wrong,
then instructs the push service to hold the result for twenty-four hours.

The overdue nudge has the same shape of problem in a different place. Its suppression tag is
`sha256(",".join(task ids))[:16]`, searched by `already_said` with **no time bound**. The tag
is a sample of the state, so it cannot represent a transition: a task that goes overdue, is
rescheduled, and goes overdue again produces the identical tag, and the second episode is
suppressed by a notification from the first — indefinitely, up to the 90-day notification
retention. Production confirms this precisely; see `proposal.md`.

The user's decision is that the repeat-suppression policy itself was wrong for this job. An
overdue task should keep asking until it is dealt with or its due date is moved out. That is
the behaviour being trained, and it is deliberately not stated in the notification text.

## Goals / Non-Goals

**Goals:**

- A notification the system decided to raise interrupts the user at the time it was raised,
  subject only to quiet hours.
- One staleness declaration per job, governing both execution and delivery.
- An overdue task is found within the hour and nudged at most every two hours until
  addressed.
- A reminder reads as a description of the situation now, not a transcript of what was said
  when it began.
- Repeated reminders about one condition produce one panel record, without making the count
  of interruptions dishonest.
- A rescheduled task that goes overdue again is recognised as a new situation.

**Non-Goals:**

- Changing quiet hours, the nudge window, the delivery ceiling, or the band-crossing
  behaviour of `disk_watch` / `budget_watch`. See `proposal.md`.
- Any retry mechanism. The next nudge is the retry.
- A per-kind urgency setting.

## Decisions

### 1. `Urgency: high` for everything, as a constant rather than a setting

`Urgency` is defined by RFC 8030 as the minimum device state at which a message is worth
delivering: `very-low` for advertisements, `low` for topic updates, `normal` for chat or
calendar messages, `high` for time-sensitive alerts. **This application has no advertisement
tier.** Every notification it sends is one the user scheduled and is waiting for; a day-end
summary's entire value is that it arrives at the end of the day.

*Alternative considered — derive urgency from `catch_up` alongside TTL.* Rejected as
false sophistication: with every current job inside a twelve-hour bound, the derivation
would compute `high` in every case while adding a rule to reason about, and would silently
demote a future job that happened to declare a loose bound. A constant with a comment
explaining why is more honest than a formula with one outcome.

*Alternative considered — a user-facing setting.* Rejected. It is a control the user has
said they do not want, and a second way to reintroduce exactly this bug.

**Verification note.** Only the `low` case is confirmed late by production data. Whether
`normal` is also deferred on Android could not be established from the evidence and is not
worth guessing at, because the fix is the same either way. The `push_count` column added
here is what will settle it: after deployment, the gap between a nudge's raise time and the
user's observation of it becomes measurable rather than anecdotal.

### 2. TTL is derived from the job's `catch_up`

`_deliver` in `jobs/runner.py` already holds the `Job`. It passes the job's staleness bound
down to `raise_notification`, which passes it to `deliver`, which sets `TTL`. One source of
truth; `_DIGEST_KINDS` is deleted.

A job declaring `catch_up=None` ("however late", used by retention) means the delivery does
not expire either. Notifications raised outside a job — the manual test push — use one
default constant.

*Trade-off:* total staleness composes to `catch_up + TTL`, so a day-end summary could in
principle arrive three hours after a run that was itself three hours late. This is accepted
rather than halved: the composed worst case requires both an outage and an offline phone,
and dividing the bound would make the number arbitrary and the comment unwritable.

### 3. The overdue tag encodes each task's due time, not only its identity

`sha256("id@due_at,id@due_at,...")`. Rescheduling changes the tag, which is correct — a
rescheduled task going overdue again *is* new information, and it is the exact case that
failed in production.

This alone does not fix the underlying blindness (a task completed and reopened at the same
due time still produces the old tag), which is why it is paired with decision 4 rather than
relied upon.

### 4. Repeat delivery against one record, bounded to one record per day

`task_nudge` stops calling `already_said`. Instead:

1. Compute the overdue set; if empty, silent.
2. Compute the tag.
3. Look for a **live** (`deleted_at IS NULL`) notification of kind `task_overdue` with this
   tag, **created since local midnight**.
4. Found → deliver it again and increment its counter. Not found → create a record and
   deliver it.

**Why bounded to a day, rather than to the episode.** The panel is ordered
`created_at DESC`. A task overdue for three weeks would hold a three-week-old record at the
bottom of a fifty-row list while the phone buzzed about it every couple of hours — invisible
in the very application doing the nudging. A daily bound keeps the record at the top, keeps
"reminded 5 times" a number with a meaning, and makes the delivery count exact for free:
every delivery of a record created inside the 09:00–19:00 window falls on that record's own
calendar day, so `pushed_today` can sum the counter without attributing deliveries across
dates.

**Why `live` and not any record.** If the user deletes today's overdue notification while the
task is still overdue, the next check creates a fresh record rather than re-delivering a row
that is not in the panel. Deleting therefore does not silence the nudge — consistent with
the existing invariant that removing a record does not make it unsaid — but it also does not
resurrect what was removed.

*Alternative considered — a new record on every check.* Rejected by the user. A column of
near-identical rows a day would bury the three notifications that are not about tasks, in a
panel that only just gained deletion because it was getting long. The device collapses them
either way (shared `tag` + `renotify`), so the cost was entirely in-app.

### 5. The schedule and the reminder interval are separate numbers

`task_nudge` runs `0 9-19 * * *` and paces interruptions with `REMIND_EVERY = 2h`.

**Written as one number first, and that was wrong.** A single two-hourly schedule reads like
"remind me every two hours" and quietly also means "wait up to two hours to be told at all":
a task falling due at 11:05 is not overdue at the 11:00 check, so nothing is said until
13:03. The repetition interval had become the detection delay, and only one of those was ever
chosen deliberately.

Hourly checks cost one indexed query each and answer "how soon do I find out?" in under an
hour. `REMIND_EVERY` answers "how often am I nagged?" without touching it.

*Alternative considered — check every five minutes, with the tick.* Rejected: it would make
`job_runs` a log of nothing happening, twelve times an hour, and buy at most 55 minutes on a
reminder that then waits two hours anyway.

Pacing measures time since the last **delivery**, not since the record was written. A record
held back by quiet hours has interrupted nobody, so it is always due — which is what lets a
reminder suppressed at night reach the user once the window ends.

### 6. The window ends at 19:00

`day_end_summary` fires at 21:00 and already lists what is overdue. A 21:00 nudge would land
in the same second saying a subset of the same thing. Ending at 19:00 costs the user nothing
— the 21:00 summary is a better last word than a duplicate — and removes the one moment in
the day when two notifications arrive together.

### 7. A reminder is re-worded, not re-said

`deliver_again` takes an optional title and body and updates the record before sending.

Rewriting a stored notification looks like it violates this module's rule that removing the
record of something said does not make it unsaid. It does not, and the distinction is worth
stating: **the tag pins which situation the record is about; the wording is a description of
that situation, not a transcript of an utterance.** The set of tasks is identical — that is
what the tag being unchanged means — and only their names have changed. Leaving the old
wording would have the reminder repeating a name the task no longer has, for the rest of the
day.

`created_at` and the tag are never touched, so "overdue since 10:03" survives.

### 8. `pushed_at` becomes "last delivered at"

Rather than a separate `last_pushed_at` column. There is no reader that wants "first
delivered", and inventing one would create a second timestamp to keep consistent. The
column comment, the model docstring and the spec all state the changed meaning.

`pushed_today` changes from `COUNT(*)` to `SUM(push_count)` over records delivered today,
which keeps it a count of *interruptions*. This matters because it is what a deliberately-set
ceiling is measured against: counting records rather than deliveries would let seven
buzzes register as one.

## Risks / Trade-offs

- **All notifications become device-waking.** → At four to six per day plus at most six
  nudges, this is well inside what push services tolerate; abuse thresholds concern
  applications sending continuously. The nudges also collapse to one device entry, so the
  visible cost is buzzes, not clutter.

- **An unresolved task interrupts up to six times a day** (09:00–19:00, paced two hours
  apart). → A decided trade-off, not a risk to mitigate. The user's position is that a
  reminder they can act on immediately is not fatigue, and that the reminder ending the moment
  they act is what separates the two. Both exits are one interaction away.

- **`pushed_at` changing meaning is a silent semantic change.** → Only `pushed_today` and
  the panel read it; both are updated here and pinned by tests. The migration comments the
  column.

- **Deleting a record mid-day produces a second record for the same condition.** → Accepted
  and specified. The alternative — remembering deleted records — is the exact mistake that
  caused the original bug.

- **A task rescheduled to later the same day creates a second record that day.** → Correct,
  not a violation of the daily bound: the bound is one record per *tag* per day, and the
  reschedule produced a new tag because the situation genuinely changed.

## Migration Plan

Migration 013 adds `notifications.push_count` as `INTEGER NOT NULL DEFAULT 0`, then backfills
`push_count = 1 WHERE pushed_at IS NOT NULL`.

**Corrected during implementation.** This was first specified as `DEFAULT 1` with no
backfill, on the grounds that every existing delivered row was delivered exactly once. That
is true of the existing rows and wrong for the column: a DDL default applies to future
inserts, and a notification is INSERTed *before* delivery is attempted — deliberately, so
the record survives a failed send. A row written and then never delivered would carry a
count of 1 while having interrupted the user zero times, and such rows are common (quiet
hours, no subscription, an uninstalled browser).

The counter therefore starts at zero and is incremented by the code that delivers, so every
value in the column is true rather than true only where delivery happened to succeed. The
one-time backfill states the historical fact separately.

Verified up → down → up with rows intact, as with 012. Down drops the column; nothing else
depends on it, so rollback is clean and loses only the repeat counts.

Deployment is the ordinary path: CI builds the image, the `migrate` service applies 013
before `api` starts.

## Open Questions

None blocking. One to answer with production data after deployment: whether `Urgency: normal`
was also being deferred, which determines whether the digests were the only affected kind or
merely the worst affected. The `push_count` column makes this measurable.
