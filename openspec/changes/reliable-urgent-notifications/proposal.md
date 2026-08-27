# Reliable, urgent notifications

## Why

Notifications reach the phone late, and the overdue-task nudge has never worked once in
production. Neither is an infrastructure fault — both are policy decisions in this
repository, and production data identifies each one exactly.

**Delivery is late because we ask for it to be late.** Every push carries an `Urgency`
header, and digests are sent as `Urgency: low` — which tells the device's push service not
to wake the phone. Measured on 2026-08-26: the day-end summary was handed to the push
service at 21:03:12, **zero seconds** after the row was written, and appeared on the phone
at roughly 21:40 when it was next picked up. Every one of the last 25 notifications was
dispatched within 0–9 seconds, and no delivery error has ever been recorded. The server is
not slow; it is politely asking to be ignored.

**The same header contradicts the job that produced it.** `day_end_summary` declares
`catch_up=3h` — *"by midnight, so it still lands on the day it describes"* — and is then
handed to the push service with `TTL: 86400`, an instruction to hold it for a full day.
`morning_brief` says *"delivered by 11:30 or not at all"* and also sends `TTL: 86400`. There
are two sources of truth about staleness in one feature and they disagree.

**The overdue nudge silenced itself permanently on its first firing.** It has raised exactly
one notification in the lifetime of the application, on 2026-08-24 at 19:04:53. That
notification was never delivered — the browser did not subscribe until 20:17:55, 73 minutes
later — and was then deleted from the panel. Since 2026-08-26 10:00 every hourly run has
returned `{"overdue": 1, "already_told": true}`.

The mechanism: the suppression tag is a hash of *which task ids are overdue*, searched with
no time bound. It samples the state and cannot see transitions, so `{gifts}` → `{}` →
`{gifts}` is indistinguishable from `{gifts}` never having changed. The user rescheduled the
task; it went overdue again; the tag matched a notification from two days earlier and the
job has been silent ever since. Deleting the notification did not help, because
`already_said` deliberately ignores `deleted_at` — correct in general, fatal here.

The user has decided the underlying policy was wrong, not just its implementation: an
overdue task SHOULD keep asking every two hours until it is dealt with or its due date is moved.
The nudge is the pressure.

## What Changes

- **Every notification is delivered as time-critical.** The `Urgency` header becomes `high`
  for all kinds; the `_DIGEST_KINDS` set stops governing it. Quiet hours are unaffected — a
  notification raised between 22:00 and 07:00 is still recorded and still not delivered.
- **Delivery lifetime is derived from the job's own staleness bound** rather than a second,
  hand-maintained list. A job already declares `catch_up`; that single declaration now
  governs both whether a missed run executes late and how long its delivery stays valid.
  `push_ttl_digest_s` and `push_ttl_nudge_s` are replaced by one default for notifications
  that no job produced.
- **BREAKING (behaviour):** An overdue task is nudged **every two hours** it remains overdue,
  instead of once. It stops when the task is completed, dropped, deleted, snoozed, or its due
  date is moved into the future. This reverses the `tasks` requirement *"A task SHALL NOT be
  raised repeatedly for the same condition"*.
- **Repeated reminders about one condition share one record.** At most one overdue
  notification exists per day, timestamped when the task actually went overdue and
  re-delivered on each reminder, rather than a column of near-identical rows burying the
  three notifications that are not about tasks. This requires a delivery counter so that the count
  of interruptions stays truthful (migration 013).
- **How soon the user finds out and how often they are reminded become two numbers.** The
  check runs **hourly**, so a task that has just fallen due is picked up within the hour; the
  interruption is paced separately to **at most every two hours**. Collapsing them into one
  two-hourly schedule — which is how this was first written — silently made the repetition
  interval the detection delay as well: a task due at 11:05 would go unmentioned until 13:03.
- **The nudge window ends at 19:00 rather than 21:00**, because `day_end_summary` fires at
  21:00 and already lists what is overdue. Two notifications arriving together saying
  overlapping things is how a reminder starts reading as noise.
- **A reminder describes the situation as it reads now.** Renaming an overdue task updates
  what the reminder says instead of repeating the name it had when the record was written.
  The record's identity and start time are untouched.
- **The suppression tag encodes the due time, not only the task identity**, so rescheduling
  a task and letting it go overdue again is recognised as a new situation rather than an old
  one.
- The notification panel shows how many times a record has been delivered, when more than
  once.

## Capabilities

### New Capabilities

None. This changes how existing capabilities behave.

### Modified Capabilities

- **`tasks`** — the requirement *"Tasks that need attention can prompt the system to speak
  first"* currently forbids repeating. It becomes: repeat until addressed, where the ways to
  address it are enumerated.
- **`notifications`** — delivery urgency becomes a stated guarantee rather than an unstated
  default; delivery lifetime is tied to content staleness; one record may be delivered more
  than once, and the count of interruptions must remain accurate when it is.

**`scheduled-jobs` is deliberately not modified.** The rule that a job's staleness bound also
governs delivery lifetime belongs in `notifications`, where delivery lives, and it refers to
the existing job declaration rather than restating it. Writing it in both places would create
a second source of truth about staleness — which is the precise defect this change exists to
remove.

## Impact

**Schema.** Migration 013 adds a delivery counter to `notifications`. `pushed_at` changes
meaning from *"when it was delivered"* to *"when it was last delivered"*; nothing reads it in
a way that breaks, but the column comment and the model docstring must say so.

**Backend.** `services/notifications.py` (urgency, repeat delivery, the per-day record
lookup, `pushed_today` summing the counter), `core/push.py` (unchanged interface, new
default), `jobs/nudges.py` (`task_nudge` repeat behaviour and the fingerprint),
`jobs/runner.py` (passing the job's staleness bound into delivery), `config.py` (TTL
settings replaced).

**Frontend.** `NotificationBell.tsx` renders the delivery count when greater than one.

**Documentation.** `ARCHITECTURE.md` and the Learn page describe notification delivery and
the overdue nudge; both currently state the "told once" behaviour and must be corrected.

**Dependencies.** None added.

## Non-goals (this change)

- **Quiet hours are not touched.** `high` urgency is a request to the push service, not a
  bypass of the user's own policy. Nothing here makes the phone buzz at night.
- **No per-kind urgency setting.** The user has asked for all notifications to be urgent;
  a setting would be an unused control surface and a second way to reintroduce this bug.
- **The daily delivery ceiling is not reinstated.** It remains available and absent by
  default, per the requirement archived in the previous change. Repeating nudges are only
  possible because it was removed.
- **The band-crossing behaviour of `disk_watch` and `budget_watch` is unchanged.** Those
  report a continuous measurement, where reporting on crossing rather than on every check is
  correct. Only the overdue nudge changes.
- **No nudging outside daytime hours.** The window is 09:00–19:00; nothing here nudges
  around the clock, and quiet hours remain a separate and untouched control.
- **No retry of a failed delivery.** A push that the push service rejects is still recorded
  against the subscription and not retried; the next check's nudge is the retry.
