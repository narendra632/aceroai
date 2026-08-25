# scheduled-jobs Specification

## ADDED Requirements

### Requirement: Storage exhaustion is reported before it happens

The system SHALL check its remaining storage on a schedule and notify the user when it falls
below a safe margin.

Storage is the one resource whose exhaustion stops the system rather than degrading it: the
database refuses writes, and nothing warns first. A reading available only on a screen helps
only on the days the user thinks to look at it.

A reading the system cannot take SHALL be treated as no reading. An unmeasurable disk SHALL
NOT be reported as a full one.

#### Scenario: Storage is comfortable

- **WHEN** the check runs and remaining storage is above the margin
- **THEN** it completes without notifying the user, and is recorded as having found nothing

#### Scenario: Storage falls below the margin

- **WHEN** the check runs and remaining storage has fallen below the margin
- **THEN** the user is notified, and told how much remains

#### Scenario: Storage cannot be measured

- **WHEN** the check runs and the reading cannot be taken
- **THEN** no notification is raised, and the absence is not treated as exhaustion

### Requirement: A persisting condition is reported on crossing, not on every check

Where scheduled work reports a continuous measurement, it SHALL notify when the measurement
crosses into a worse band, and SHALL NOT notify again while it remains within the same band.

Bands rather than exact values, so that a measurement oscillating around a single point does
not produce repeated notifications.

The system SHALL bound how long a past notification suppresses a repeat, so that a condition
which recurs after being resolved is reported again rather than silenced permanently.

#### Scenario: The condition persists

- **WHEN** the check runs repeatedly while the measurement stays within the band already
  reported
- **THEN** no further notification is raised on those runs

#### Scenario: The condition worsens

- **WHEN** the measurement crosses into a worse band than the one already reported
- **THEN** the user is notified again, because that is new information

#### Scenario: The condition returns after being resolved

- **WHEN** the measurement improves out of a band and later returns to it, beyond the
  suppression window
- **THEN** the user is notified again, rather than silenced by a report made long ago

#### Scenario: The condition is still unresolved much later

- **WHEN** the measurement remains within a reported band beyond the suppression window
- **THEN** the user is reminded, so an unresolved condition is not forgotten
