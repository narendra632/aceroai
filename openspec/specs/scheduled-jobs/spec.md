# scheduled-jobs Specification

## Purpose
TBD - created by archiving change add-scheduled-jobs-and-push. Update Purpose after archive.
## Requirements
### Requirement: Recurring work runs on a schedule, independent of user activity

The system SHALL run defined units of recurring work on their own schedule, without requiring
the user to interact with the application.

Schedules SHALL be interpreted in the user's configured timezone, so that a job described as
running at the end of the day runs at the end of the user's day.

#### Scenario: Work runs while the user is absent

- **WHEN** the user has not opened or messaged the application for several days
- **THEN** scheduled work still runs at its appointed times

#### Scenario: Schedules follow the configured timezone

- **WHEN** a job is scheduled for a particular local hour
- **THEN** it runs at that hour in the configured timezone, not in UTC

### Requirement: A scheduled run happens at most once

Each occurrence of a scheduled job SHALL execute at most once, and this SHALL be guaranteed
by durable state rather than by the scheduler's memory.

Repeating a tick, restarting the process, or triggering a job manually for an occurrence that
already succeeded SHALL NOT produce a second execution or a second notification.

#### Scenario: A repeated tick does not repeat the work

- **WHEN** the scheduler evaluates the same job occurrence more than once
- **THEN** the work executes only the first time, and subsequent evaluations do nothing

#### Scenario: A restart does not repeat completed work

- **WHEN** the application restarts after a job occurrence has already succeeded
- **THEN** that occurrence is not executed again

### Requirement: A run missed while the system was down is recovered, within a bound

When the system was unavailable at a job's scheduled time, that job SHALL run on the next
opportunity, provided the delay is within a bound defined for that job.

A job whose most recent occurrence is older than its bound SHALL be recorded as missed and
SHALL NOT be run late, because late delivery of time-sensitive work is worse than silence.

Only the most recent occurrence of a job SHALL be considered. Occurrences skipped while the
system was down SHALL NOT accumulate.

#### Scenario: A short outage is recovered

- **WHEN** the application was restarting at a job's scheduled time and comes back shortly
  afterwards
- **THEN** that job runs, and its occurrence is recorded as satisfied

#### Scenario: A long outage does not deliver stale work

- **WHEN** the application was unavailable for longer than a job's recovery bound
- **THEN** the job does not run for that occurrence, and the occurrence is recorded as missed

#### Scenario: Missed occurrences do not accumulate

- **WHEN** the application has been unavailable across many occurrences of the same job
- **THEN** at most one execution of that job takes place when it returns

### Requirement: A failing job cannot damage the application

A job that fails SHALL have its failure recorded and SHALL NOT propagate the failure outward.

A failure in one job SHALL NOT prevent other jobs from running, SHALL NOT stop the scheduler,
and SHALL NOT affect the application's ability to serve the user.

Jobs SHALL be prevented from waiting indefinitely on database contention, because housekeeping
must never block work the user is waiting for.

#### Scenario: One job fails, others continue

- **WHEN** a job raises an error during its run
- **THEN** the error is recorded against that run, the remaining jobs still run, and the
  application continues serving requests

#### Scenario: A job does not wait on a lock

- **WHEN** a job's database work is blocked by a transaction the application is holding
- **THEN** the job gives up rather than waiting indefinitely, and its next occurrence retries

### Requirement: Every run leaves a record, including runs that did nothing

Each attempted run SHALL be recorded with its outcome, distinguishing at minimum: succeeded,
succeeded with nothing to report, failed, skipped because the job was disabled, skipped
because a spending limit was reached, and missed.

A job that correctly finds nothing to do SHALL be distinguishable from a job that failed and
from a job that never ran.

#### Scenario: Nothing to report is a success

- **WHEN** a job runs and correctly determines there is nothing to tell the user
- **THEN** the run is recorded as successful with nothing to report, not as a failure and not
  as a missing run

#### Scenario: A skipped run says why

- **WHEN** a run does not happen because the job is disabled or a limit was reached
- **THEN** the record states which of those it was

### Requirement: Adding a new job requires no change to the scheduler or the schema

A new unit of recurring work SHALL be definable by declaring it alongside the other jobs,
without modifying the scheduler, the runner, the database schema, or the user interface.

Declaring a job SHALL be sufficient for it to receive run recording, failure isolation,
spending checks, user-facing enablement, and notification policy.

A job's default enabled state SHALL be part of its declaration, and a user preference SHALL
override it without requiring storage to exist in advance.

#### Scenario: A new job is added

- **WHEN** a developer declares a new job
- **THEN** it is scheduled, recorded, controllable by the user, and subject to the same
  policies as every other job, with no other change

#### Scenario: A job with no stored preference

- **WHEN** a job has never had its preference set by the user
- **THEN** its declared default applies

### Requirement: Declarations are validated when the application starts

Job declarations SHALL be checked at startup: names SHALL be unique, schedules SHALL be
parseable, and every job SHALL carry a description intended for the user.

An invalid declaration SHALL prevent the application from starting rather than failing at the
job's scheduled time.

#### Scenario: A malformed job is caught immediately

- **WHEN** a job is declared with a duplicate name, an unparseable schedule, or no description
- **THEN** the application refuses to start and names the offending job

### Requirement: Jobs that use a model are subject to the spending limit and are recorded as cost

A job that calls a language model SHALL check the user's spending limit before making the
call, and SHALL be recorded in the same trace and cost accounting as every other model call,
attributed as scheduled work.

A job prevented from running by the spending limit SHALL record that outcome rather than
failing or silently proceeding.

#### Scenario: A limit stops an automated call

- **WHEN** the spending limit has been reached and a model-using job is due
- **THEN** the model is not called and the run is recorded as skipped for spending

#### Scenario: Automated spend is visible

- **WHEN** a model-using job completes
- **THEN** its cost, tokens and duration appear in the same place as the cost of the user's
  own messages, identified as scheduled work

### Requirement: A model may phrase automated messages, but never determine their facts

When a job uses a language model to compose a message for the user, the job SHALL determine
every fact in that message itself, and the model SHALL receive only those facts plus an
instruction to express them.

The model SHALL NOT have the ability to query the user's data, choose what to include, or
take actions while composing an automated message.

Content generated by the system SHALL NOT be used as a source for learning facts about the
user.

#### Scenario: The message reflects only established facts

- **WHEN** a job composes a summary using a model
- **THEN** every claim in the summary comes from data the job gathered, and the model had no
  means to obtain any other

#### Scenario: Generated content is not learned from

- **WHEN** the system generates a summary about the user
- **THEN** that summary is not used to derive stored facts about the user

### Requirement: The user can see and control what runs automatically

The user SHALL be able to see which jobs exist, what each one does, and when it runs, and
SHALL be able to enable or disable each one individually.

#### Scenario: Reviewing automated work

- **WHEN** the user opens the settings for automated work
- **THEN** every job is listed with a plain-language description and its schedule

#### Scenario: Turning one off

- **WHEN** the user disables a job
- **THEN** that job stops running and no others are affected

### Requirement: Trace retention runs as scheduled work

The pruning and rollup of recorded traces SHALL run as a scheduled job rather than being
triggered by user activity, so that it happens during a period of low use and happens whether
or not the application was used that day.

Records of what the user has been told SHALL also be subject to a retention policy, so that
the notification history cannot grow without bound.

#### Scenario: Retention happens on a quiet day

- **WHEN** the user has not used the application at all that day
- **THEN** trace rollup and pruning still take place

#### Scenario: Notification history is bounded

- **WHEN** stored notifications pass the retention window
- **THEN** they are removed

