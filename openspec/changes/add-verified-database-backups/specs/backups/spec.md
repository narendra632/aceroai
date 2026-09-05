# backups Specification

## ADDED Requirements

### Requirement: A copy of everything the system knows exists somewhere else

The system SHALL, on a recurring schedule, write a complete copy of its database to durable
storage outside the machine it runs on. The copy SHALL be self-contained: restorable on its
own, without reference to any other copy.

Completeness is not negotiable down to "the important tables". What is worth keeping cannot be
decided in advance, because the value of a record is frequently discovered later than the
record — a job run that seemed routine becomes the evidence for when a defect began.

Self-containment is the property being bought. A copy that depends on an unbroken series of
other copies fails in a way that is invisible until it is needed, and the schedule is chosen
so that any single copy is sufficient rather than so that the newest one is.

The system SHALL accept that work done since the most recent copy is at risk, and SHALL make
the size of that window a stated property rather than an accident of implementation.

#### Scenario: A recurring copy

- **WHEN** the scheduled time arrives and the database is reachable
- **THEN** a complete, self-contained copy of the database is written to durable storage
  outside the machine, and the run is recorded

#### Scenario: One copy is enough to recover

- **WHEN** a recovery is attempted using any single stored copy
- **THEN** that copy alone is sufficient to reconstruct the database as it stood when the copy
  was taken, without requiring any other copy to be present or intact

### Requirement: A copy carries a description of what it should contain

Every copy SHALL be accompanied by a record, written at the same moment, stating what the copy
is expected to contain — at minimum its size, a checksum over its contents, and the number of
records in each table at the time it was taken.

Without such a record, a copy can only be checked for *restorability*, which is a much weaker
claim than *correctness*: a truncated or partially written copy frequently restores without
reporting an error, producing a database that is smaller than it should be and silent about it.

This record SHALL describe the state at the moment the copy was taken, not the current state.
A copy is verified against what was true when it was made; comparing it to a database that has
since moved on can only produce a difference that means nothing.

#### Scenario: A copy that was truncated in transit

- **WHEN** a stored copy is checked and its contents do not match the checksum recorded with it
- **THEN** the copy is treated as unusable and reported, rather than being counted as a
  successful backup

### Requirement: Copies are proven restorable rather than assumed restorable

The system SHALL, on a recurring schedule, take its most recent copy, restore it into an
isolated location, and compare the result against the record written with that copy. A
mismatch, a failed restore or a failed checksum SHALL be reported.

A copy that has never been restored is a belief, not a backup. The failures this catches are
specifically the ones that produce no error at the time the copy is written: an incomplete
upload, a change to the storage format, a schema feature the restoring tool does not handle,
or an extension the restoring database lacks.

The restoration SHALL be isolated: it SHALL NOT write into, replace, or modify the live
database under any circumstances, including failure. Verifying a backup must never be capable
of causing the loss it exists to prevent.

The isolated location SHALL be removed after each check, whether the check succeeded or
failed, and a check SHALL tolerate finding the remains of a previous interrupted run.

#### Scenario: A copy that restores and matches

- **WHEN** the most recent copy is restored into an isolated location and every table's record
  count matches the record written with that copy
- **THEN** the copy is confirmed usable, nothing is reported to the user, and the isolated
  location is removed

#### Scenario: A copy that restores but is incomplete

- **WHEN** a restore succeeds but a table holds fewer records than the copy's own record states
- **THEN** the discrepancy is reported to the user, naming the table and both counts

#### Scenario: Verification never touches live data

- **WHEN** a verification runs, by any outcome including an unhandled failure part-way through
- **THEN** the live database is unmodified, and no restored data has been written into it

### Requirement: The absence of a recent copy is reported

The system SHALL report when no copy has been successfully made within a stated period, and
that report SHALL be produced by work that is separate from the work that makes copies.

This exists because the characteristic failure of a backup system is not an error but a
silence. Work that has stopped running cannot report that it has stopped running, so a
mechanism that only reports its own failures cannot report its own absence. Only a separate
observer can distinguish "nothing needed to happen" from "nothing happened".

The stated period SHALL be longer than one scheduled interval, so that a single missed
occurrence — a restart, a transient failure of the storage service, a schedule that could not
run in time — does not produce a report, while consecutive failures always do.

An unresolved absence SHALL continue to be reported rather than being announced once, in the
same way that a persisting condition of the machine is reported.

#### Scenario: One missed occurrence

- **WHEN** a single scheduled copy fails but the next one succeeds
- **THEN** the failure of that occurrence is reported, but no absence is reported, because a
  recent copy exists

#### Scenario: Copies have silently stopped

- **WHEN** no copy has succeeded for longer than the stated period, for any reason including
  the work never having run
- **THEN** the user is told that backups have stopped, and continues to be told while it
  remains true

### Requirement: A failure to copy is reported when it happens

When making a copy fails — the database is unreachable, the storage service refuses the write,
or the copy cannot be completed — the system SHALL record the failure and report it to the
user.

A failed backup is not equivalent to a quiet night. The system SHALL NOT treat an error as an
absence of work to do, and SHALL NOT allow a failure to be indistinguishable from a run that
correctly had nothing to report.

#### Scenario: Storage is unreachable

- **WHEN** a copy is made but cannot be written to durable storage
- **THEN** the run is recorded as failed and the user is told, rather than the run being
  recorded as having completed

### Requirement: Copies are kept across a range of ages, and expire without application code

Stored copies SHALL span a range of ages — recent copies at fine granularity and older copies
at coarse granularity — reaching back far enough to predate a defect that took months to
notice.

Recent copies address mistakes discovered quickly. They cannot address the failure where
incorrect data is written and then faithfully copied every night afterwards: at that point
every recent copy contains the fault, and only a copy predating it holds the truth. A series
of older copies additionally allows the onset to be located rather than merely escaped.

Expiry of old copies SHALL be performed by the storage service rather than by application
code. Application code that deletes backups is code capable of deleting the wrong backup, in
the one place where there is no second copy to fall back on, on the least-exercised path in
the system.

#### Scenario: A fault noticed months later

- **WHEN** incorrect data is discovered to have been written some months earlier, and every
  recent copy therefore contains it
- **THEN** a copy predating the fault is still available, and the copies between it and the
  present allow the onset to be narrowed down

#### Scenario: Expiry is not the application's to perform

- **WHEN** stored copies pass the age at which they should no longer be kept
- **THEN** they are removed by the storage service, and no application code issues a deletion

### Requirement: A copy is protected at least as well as the database it copies

A stored copy SHALL be private, encrypted at rest, and reachable only by the identity that
writes it. Its protection SHALL NOT be weaker than that of the live database.

A complete copy of the database contains everything the database contains, including
credentials in whatever form the database holds them. It is a strictly more attractive target
than the running system, because it is a single file that can be taken whole.

Writing copies SHALL NOT require introducing a stored credential. Where the environment can
provide an identity to the running application without one, that mechanism SHALL be used, so
that adding backups does not add the system's first long-lived secret on disk.

#### Scenario: Access to stored copies

- **WHEN** stored copies exist
- **THEN** they are not publicly reachable, are encrypted at rest, and are readable only by
  the identity the system uses to write them

#### Scenario: No new stored credential

- **WHEN** the system authenticates in order to write a copy
- **THEN** it does so using an identity supplied by its environment, and no additional
  credential is stored on disk or in configuration
