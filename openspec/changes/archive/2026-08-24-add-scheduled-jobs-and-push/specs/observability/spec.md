# observability Specification (delta)

## MODIFIED Requirements

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
