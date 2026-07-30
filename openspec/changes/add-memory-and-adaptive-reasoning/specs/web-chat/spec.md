## MODIFIED Requirements

### Requirement: Context is built from persona and recent history

`core/composer` SHALL assemble the model input from the `docs/SOUL.md` persona as
the first system message, followed by the user's **semantically-recalled active
profile facts** (the facts most relevant to the current message) as a system
block, followed by the session's recent messages in chronological order. When no
relevant active facts exist, the facts block SHALL be omitted.

#### Scenario: Persona leads the context

- **WHEN** context is built for a session
- **THEN** the first message is the SOUL.md persona as a system message

#### Scenario: Relevant recalled facts follow the persona

- **WHEN** context is built for a user whose active facts include some relevant to
  the current message
- **THEN** a system block listing those relevant facts appears after the persona
  and before the session's messages

#### Scenario: Recent history in order

- **WHEN** context is built for a session
- **THEN** the session's most recent prior messages follow, in chronological order

## ADDED Requirements

### Requirement: Chat generation uses an adaptive reasoning effort

Chat generation through the one-brain handler SHALL apply a reasoning effort chosen
per request, so ordinary replies are fast while deeper thinking is available on
demand. The handler SHALL accept a caller-supplied effort (the task-routing hook)
and otherwise default to the configured chat effort. The effort SHALL be passed to
the model provider only when set, so providers/models that do not support it are
unaffected.

#### Scenario: Fast default for normal chat

- **WHEN** a user sends an ordinary chat message with no effort override
- **THEN** the handler generates with the default chat reasoning effort (a fast
  setting) so the first token arrives sooner

#### Scenario: Explicit "think harder" routes to deeper reasoning

- **WHEN** a user opts into deeper reasoning for a message (the web "think harder"
  control)
- **THEN** the handler generates that reply with the deeper reasoning effort

#### Scenario: A caller routes a specific effort

- **WHEN** a caller invokes the handler with an explicit reasoning effort
- **THEN** that effort is used instead of the default

#### Scenario: Effort omitted when unset

- **WHEN** the resolved reasoning-effort value is empty
- **THEN** no reasoning-effort parameter is sent to the provider

### Requirement: Transient provider errors are retried

Generation SHALL retry a request that fails with a transient provider error
(timeout, connection error, or rate limit) with a short backoff, up to a
configured number of attempts. A retry MUST NOT occur once any output token has
been produced, so retries never duplicate already-streamed text.

#### Scenario: Transient failure before first token

- **WHEN** the provider call fails transiently before any token is produced
- **THEN** the system retries with backoff and, on success, streams the reply
  normally

#### Scenario: Failure after streaming has begun

- **WHEN** the provider fails after one or more tokens have already been streamed
- **THEN** the system does not retry (to avoid duplicate output) and reports an
  error

### Requirement: Errors are reported without leaking internals

When generation ultimately fails, the system SHALL log the full error server-side
and return a concise, friendly message to the client rather than the raw provider
error text. A rate-limit/quota failure SHALL be reported as such.

#### Scenario: Provider error surfaced safely

- **WHEN** generation fails and cannot be retried
- **THEN** the client receives a short, human-friendly error message and the raw
  provider error is not exposed to the client

#### Scenario: Quota exhausted

- **WHEN** generation fails because the provider rate limit/quota is exhausted
- **THEN** the client is told the request hit a rate limit and to try again later

### Requirement: Over-long messages are rejected before persistence

The system SHALL reject a user message longer than a configured maximum length
with an error, and MUST NOT persist the message or call the model for it.

#### Scenario: Message too long

- **WHEN** a user sends a message exceeding the maximum length
- **THEN** the system responds with an error, stores nothing, and does not call
  the model
