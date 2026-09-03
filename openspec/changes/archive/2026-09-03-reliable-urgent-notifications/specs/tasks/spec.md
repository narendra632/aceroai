# tasks Specification

## REMOVED Requirements

### Requirement: Tasks that need attention can prompt the system to speak first

**Reason**: This requirement said a task must be raised **once**: *"A task SHALL NOT be raised
repeatedly for the same condition."* It was written to prevent notification fatigue and it
produced the opposite failure — a task raised once and then silent is a task the system has
stopped helping with.

In production it did worse than that. The overdue nudge raised exactly one notification in the
lifetime of the application, on 2026-08-24. It was never delivered, because no browser had
subscribed yet, and it was then removed from the panel. The suppression tag hashed task ids
with no time bound, so when the task was rescheduled and fell due again the tag matched that
undelivered notification and every run afterwards reported "already told". The feature was
silent from its first firing, and nothing anywhere reported an error.

Removed rather than modified because its meaning **inverts** rather than shifts, and its
scenario "Not told twice" asserts precisely what must no longer be true. Keeping the name over
opposite content would have been the more confusing record.

**Migration**: Replaced in full by *"Tasks that need attention keep asking until they are
addressed"*, below. Every guarantee worth keeping is carried over: coalescing several overdue
tasks into one notification, silence for snoozed and finished tasks, and raising a task whose
due time has passed. What changes is that the reminder now repeats until the user acts, and
ends the moment they do.

## ADDED Requirements

### Requirement: Tasks that need attention keep asking until they are addressed

The system SHALL be able to notice, without being asked, that the user's tasks require
attention — at minimum that a task's due time has passed — and raise a notification.

Multiple tasks requiring attention at the same time SHALL produce a single notification
describing them collectively, not one per task.

A task whose due time has passed SHALL continue to be reported until it is addressed.
Addressing it means completing it, dropping it, deleting it, snoozing it, or moving its due
time into the future. No other action SHALL stop the reminder — in particular, reading or
removing the notification SHALL NOT.

**How soon the user learns a task has fallen due and how often they are reminded afterwards
SHALL be separate.** Checking and interrupting on the same interval makes the repetition
interval the detection delay as well, so a task falling due just after a check goes
unmentioned for the whole interval. The system SHALL check more often than it interrupts.

Reporting SHALL be confined to daytime hours, and SHALL NOT coincide with a scheduled summary
that already describes what is overdue.

The system SHALL NOT explain this rule in the notification text. Stating "deal with this or
move its due date" in every reminder would make each one longer without making it more
effective; the behaviour is learned from the reminders themselves.

Repeated reminders about the same unchanged situation SHALL share a single record per day
rather than accumulating one record per check, and that record SHALL carry how many times it
has been delivered.

A repeated reminder SHALL describe the situation **as it reads at the time of the reminder**,
not as it read when the record was first written. Renaming a task therefore changes what the
reminder says. The record's identity and the time the situation began SHALL NOT change.

A situation that has genuinely changed SHALL be treated as new rather than as a continuation.
A different set of tasks is a change; so is the same task with a different due time.

A task the user has snoozed SHALL NOT be raised before the time it was snoozed until, and a
task that is completed, dropped or deleted SHALL NOT be raised at all.

#### Scenario: An overdue task is raised

- **WHEN** a task's due time passes and the user has not been told
- **THEN** the system raises a notification identifying that task

#### Scenario: Several at once become one

- **WHEN** more than one task requires attention at the same time
- **THEN** a single notification describes them together

#### Scenario: Still overdue at the next reminder

- **WHEN** a task is still overdue when the next reminder is due, and nothing about it has
  changed
- **THEN** the user is reminded again

#### Scenario: A check between reminders

- **WHEN** a check runs while a task is still overdue but the reminder interval has not
  elapsed
- **THEN** the user is not interrupted, and the check is recorded as having correctly said
  nothing

#### Scenario: A task falls due just after a check

- **WHEN** a task's due time passes shortly after a check has run
- **THEN** the user learns of it at the next check, which is sooner than the interval between
  reminders

#### Scenario: A task is renamed while overdue

- **WHEN** a task is renamed while it is still overdue
- **THEN** the next reminder describes it by its new name, against the same record and
  without changing when the situation began

#### Scenario: The last reminder does not collide with the day's summary

- **WHEN** a scheduled summary that already lists overdue tasks is delivered
- **THEN** no overdue reminder is delivered at the same time

#### Scenario: Removing the reminder does not stop it

- **WHEN** the user removes an overdue notification while the task is still overdue
- **THEN** the next check reminds them again

#### Scenario: The due time is moved out

- **WHEN** the user moves an overdue task's due time into the future
- **THEN** it stops being raised, until that new due time passes

#### Scenario: A rescheduled task becomes overdue again

- **WHEN** a task was raised as overdue, was rescheduled, and its new due time later passes
- **THEN** the user is notified, rather than silenced by the reminder raised before the
  reschedule

#### Scenario: A day's reminders share one record

- **WHEN** the same unchanged situation is reminded about several times in one day
- **THEN** the application shows one record for it, timestamped when the situation began,
  reporting how many times it was delivered

#### Scenario: Snoozed and finished tasks are silent

- **WHEN** a task is snoozed to a future time, or is completed, dropped or deleted
- **THEN** it does not produce a notification
