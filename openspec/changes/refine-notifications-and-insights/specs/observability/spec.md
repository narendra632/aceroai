# observability Specification

## ADDED Requirements

### Requirement: The user can see the condition of the machine the system runs on

The application SHALL report the current condition of its host to the authenticated user,
covering at minimum the storage and memory it has left, the size of its database, and whether
its scheduled work is still being attempted.

These readings are instantaneous and SHALL be presented distinctly from figures that are
scoped to a selected period, so that no reading is mistaken for an average or a total over
time.

#### Scenario: Reading the current condition

- **WHEN** the user opens the screen that reports system condition
- **THEN** current storage, memory, database size and scheduler activity are shown

#### Scenario: Not confused with period figures

- **WHEN** current readings are shown on the same screen as figures scoped to a selected
  period
- **THEN** the two are visually separated, and the period control does not appear to govern
  the current readings

#### Scenario: Pressure is distinguishable from comfort

- **WHEN** a proportional reading approaches the point at which the system would be at risk
- **THEN** that reading is marked as such, while readings in a healthy range remain
  visually quiet

### Requirement: A stalled scheduler is visible

The system SHALL report when its scheduler last attempted work, so that a scheduler which has
stopped is discoverable from within the application.

This is the one failure this system cannot otherwise report: scheduled work that stops
happening produces no error, no failed request and no log line — only an absence.

#### Scenario: The scheduler has stopped

- **WHEN** the scheduler has not attempted work for substantially longer than its interval
- **THEN** the reported time of its last attempt reveals this

#### Scenario: The scheduler has never run

- **WHEN** no scheduled work has ever been attempted
- **THEN** that is reported as such, and not as a recent or unknown time

### Requirement: Condition readings are authenticated and never inferred

Readings about the host SHALL be available only to the authenticated user, and SHALL NOT be
added to any endpoint that is reachable without authentication.

A reading the system cannot actually take SHALL be reported as absent and omitted from the
interface. The system SHALL NOT substitute a default, a zero, or an estimate for a measurement
it did not make.

#### Scenario: The public liveness endpoint is unchanged

- **WHEN** an unauthenticated caller checks whether the service is alive
- **THEN** it learns only that the service is alive, and nothing about storage, memory, or the
  database

#### Scenario: A measurement is unavailable on this platform

- **WHEN** the host does not expose a particular measurement
- **THEN** that reading is reported as absent and omitted from the interface, rather than
  shown as zero

### Requirement: Polling for condition costs nothing when nobody is looking

Where the interface refreshes host readings on a timer, it SHALL stop refreshing while the
screen is not being viewed, and SHALL take a fresh reading immediately upon becoming visible
again.

A monitoring display must not become a load source on the machine it monitors.

#### Scenario: The screen is hidden

- **WHEN** the user switches away from the application or the screen is otherwise not visible
- **THEN** refreshing stops until it is visible again

#### Scenario: Returning to the screen

- **WHEN** the screen becomes visible again
- **THEN** a fresh reading is taken at once, so nothing stale is presented as current

#### Scenario: Leaving the screen

- **WHEN** the user navigates away from the screen that shows these readings
- **THEN** refreshing stops entirely
