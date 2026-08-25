# observability Specification

## Purpose
Make the system's behaviour and cost measurable rather than guessed. Every model call —
including the background ones the user never sees — is recorded as a trace with its
durations, token usage, and estimated cost, and is presented so that spend, latency and
failures can be understood without reading logs.
## Requirements
### Requirement: Every model call is recorded

The system SHALL record every call it makes to a model provider, including calls made
outside a user-visible reply.

#### Scenario: A chat turn is recorded

- **WHEN** a user turn completes
- **THEN** a trace is recorded with its provider, model, duration, time to first token,
  token usage, and estimated cost

#### Scenario: Background work is recorded

- **WHEN** the system makes a model call that is not part of a reply — such as extracting
  facts from a finished turn, or embedding text for recall
- **THEN** that call is recorded as its own trace, identified by what it was for, so its
  cost is attributed rather than invisible

#### Scenario: A failed turn is recorded

- **WHEN** a turn fails
- **THEN** it is recorded as failed with the kind of failure, so failures are visible
  alongside successes

### Requirement: Recorded token usage reflects everything that was billed

Token counts SHALL account for the whole turn, not a portion of it.

#### Scenario: A turn uses tools across several rounds

- **WHEN** a turn makes more than one model round because the assistant used tools
- **THEN** the recorded token usage is the total across all rounds, not the last round

#### Scenario: The model spends tokens on reasoning

- **WHEN** a provider reports tokens spent on internal reasoning separately from visible
  output
- **THEN** those tokens are recorded and counted toward cost, and are distinguishable from
  visible output tokens

### Requirement: Recording never degrades the thing it observes

Trace recording SHALL happen off the path that produces a reply, and MUST NOT be able to
delay or break one.

#### Scenario: Recording fails

- **WHEN** writing a trace fails for any reason
- **THEN** the user's reply is unaffected and no error is surfaced to them

#### Scenario: A reply is being streamed

- **WHEN** a reply is streaming
- **THEN** no trace write occurs until after the reply has completed

### Requirement: Traces record shape, never content

Traces SHALL record the size and structure of what was sent and received, and MUST NOT
store the text of prompts or replies.

#### Scenario: A trace is written

- **WHEN** a trace is recorded
- **THEN** it contains counts, durations and identifiers, and contains no message text

### Requirement: Cost is an estimate, frozen at the time of the call

Estimated cost SHALL be computed when the call is recorded and stored with the identity of
the price list used. A later change to prices MUST NOT alter an already-recorded cost.

#### Scenario: Prices change

- **WHEN** a model's price is updated
- **THEN** previously recorded costs are unchanged, and the price list that produced each
  recorded cost remains identifiable

#### Scenario: A model has no known price

- **WHEN** a call uses a model absent from the price list
- **THEN** its cost is recorded as unknown rather than as zero

#### Scenario: Cost is displayed

- **WHEN** any cost figure is shown
- **THEN** it is identified as an estimate, because the system does not have access to the
  provider's actual invoice

### Requirement: The user can see spend, latency and failures

The system SHALL present recorded traces so that cost, performance and reliability can be
understood without reading logs.

#### Scenario: The user reviews spend

- **WHEN** the user opens the insights view
- **THEN** they see spend over time, broken down by model and by what the call was for

#### Scenario: The user reviews latency

- **WHEN** latency is presented
- **THEN** it is expressed as percentiles rather than an average, so a single slow turn
  does not disguise typical behaviour

#### Scenario: The user investigates one turn

- **WHEN** the user selects a recorded turn
- **THEN** they see how its duration was distributed across its stages, so a slow stage is
  identifiable without instrumentation work

#### Scenario: The record does not cover the whole history

- **WHEN** the insights view is shown
- **THEN** the date from which traces exist is stated, so the view never implies it covers
  a period it does not

### Requirement: Observation never mutates

The insights view SHALL be read-only.

#### Scenario: The user interacts with insights

- **WHEN** the user uses any control in the insights view
- **THEN** no stored data is created, changed or deleted

### Requirement: Trace data is bounded

Recorded traces SHALL be subject to a retention policy, so that observability cannot
consume the storage the application depends on.

Retention SHALL be applied on a schedule, at a time of low use, and SHALL NOT depend on the
user having interacted with the application. A period in which the application was not used
SHALL still have its retention applied.

The same bound SHALL apply to the record of what the user has been told, so that notification
history cannot become the unbounded table that trace retention exists to prevent.

#### Scenario: Traces age out

- **WHEN** detailed per-stage records pass the retention window
- **THEN** they are removed, while aggregate totals for those periods are preserved

#### Scenario: Retention does not depend on being used

- **WHEN** the user has not interacted with the application for an extended period
- **THEN** retention still runs, and records that have passed the window are removed

#### Scenario: Notification history is bounded too

- **WHEN** stored notifications pass their retention window
- **THEN** they are removed by the same scheduled retention

### Requirement: Secrets never reach the logs

Diagnostic output SHALL NOT contain credentials.

This SHALL hold for credentials embedded in outbound request URLs, whether the URL is written
deliberately, produced by a client library, or rendered as part of an exception or traceback.
Redaction SHALL be applied to the final formatted output, because an exception's text is
rendered after any filter that inspects the log record's fields.

Redaction SHALL NOT remove data that merely resembles a credential. A pattern that also
destroys legitimate diagnostic values is a defect, not a safe default.

#### Scenario: An outbound request carries a token in its URL

- **WHEN** the system makes a request whose URL embeds a secret
- **THEN** that URL is not written to the logs

#### Scenario: A credential appears inside an exception

- **WHEN** an error is raised whose message or traceback contains a credential
- **THEN** the credential is not present in the emitted log line

#### Scenario: Legitimate values survive redaction

- **WHEN** diagnostic output contains a value whose name resembles a credential but is a
  measurement
- **THEN** that value is written intact

### Requirement: Spend can be capped, not only observed

The user SHALL be able to set a monthly ceiling on estimated spend, after which the system
stops making model calls until the ceiling is raised or the month resets. Reporting a cost
that cannot be stopped leaves a runaway loop visible only in hindsight.

The ceiling is optional. With none set, behaviour is unchanged.

#### Scenario: No ceiling is set

- **WHEN** the user has never set a spend limit
- **THEN** no request is ever refused on cost grounds

#### Scenario: The month's spend reaches the ceiling

- **WHEN** a message arrives and the month's estimated spend has reached the limit
- **THEN** the message is refused before any model call is made
- **AND** the user is told the limit, what has been spent, when it resets, and how to raise it

#### Scenario: Everything billable counts toward the ceiling

- **WHEN** spend is measured against the limit
- **THEN** background work is included alongside visible replies, because the provider
  bills for all of it

#### Scenario: The user approaches the ceiling

- **WHEN** spend passes a warning threshold below the limit
- **THEN** the user is told before being stopped, not only afterwards

#### Scenario: The user raises the limit

- **WHEN** the user increases the limit while blocked
- **THEN** messages are answered again immediately, with no restart

#### Scenario: A refusal is not a failed model call

- **WHEN** a message is refused for exceeding the limit
- **THEN** no trace of a model call is recorded, because none was made

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

