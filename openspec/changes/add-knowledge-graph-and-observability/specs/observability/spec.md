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

#### Scenario: Traces age out

- **WHEN** detailed per-stage records pass the retention window
- **THEN** they are removed, while aggregate totals for those periods are preserved

### Requirement: Secrets never reach the logs

Diagnostic output SHALL NOT contain credentials.

#### Scenario: An outbound request carries a token in its URL

- **WHEN** the system makes a request whose URL embeds a secret
- **THEN** that URL is not written to the logs
