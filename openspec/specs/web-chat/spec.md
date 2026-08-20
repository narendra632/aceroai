# web-chat Specification

## Purpose
TBD - created by archiving change add-web-chat. Update Purpose after archive.
## Requirements
### Requirement: All chat flows through the one-brain handler

Every conversational message, regardless of channel, SHALL be processed by
`core/handler.handle_message(...)`. HTTP routes and future channel adapters MUST
be pure transport and MUST NOT contain context-building or LLM-calling logic.

#### Scenario: Web message routed through the handler

- **WHEN** an authenticated user sends a message to `/api/chat`
- **THEN** the route delegates to `handle_message` and only forwards the yielded
  output to the client, holding no prompt-assembly or model-call logic itself

### Requirement: Assistant replies stream over SSE

The system SHALL stream the assistant's reply to the browser as it is generated,
using Server-Sent Events. The stream MUST include the session id, incremental
text deltas, and a terminal completion event.

#### Scenario: Streamed reply

- **WHEN** a user posts a message
- **THEN** the response is an SSE stream that emits a `session` event (session
  id), then one or more `delta` events carrying text fragments, then a `done`
  event with the persisted assistant message id

#### Scenario: Upstream LLM error mid-stream

- **WHEN** the LLM call fails after the stream has opened
- **THEN** the system emits an `error` event and does not persist a partial or
  empty assistant message

### Requirement: User and assistant turns are persisted

The system SHALL persist the incoming user message before generation and the
completed assistant message after generation, both linked to a chat session.
The assistant message MUST record the model used; token counts SHALL be recorded
when the provider reports them.

#### Scenario: Both turns saved

- **WHEN** a chat exchange completes successfully
- **THEN** the session's `messages` contain the user message (role `user`) and
  the assistant reply (role `assistant`) in order, and the session's
  `last_active_at` is updated

#### Scenario: New session on first message

- **WHEN** a user sends a message without a session id
- **THEN** the system creates a new `chat_sessions` row for that user on channel
  `web`, titled from the first message, and uses it for the exchange

### Requirement: Sessions and history are retrievable

The system SHALL let an authenticated user list their chat sessions and load the
messages of a session they own. A user MUST NOT be able to read another user's
sessions or messages.

#### Scenario: List sessions

- **WHEN** an authenticated user GETs `/api/chat/sessions`
- **THEN** the system returns that user's sessions, most-recently-active first

#### Scenario: Load history

- **WHEN** an authenticated user GETs `/api/chat/sessions/{id}/messages` for a
  session they own
- **THEN** the system returns that session's messages in chronological order

#### Scenario: Cannot access another user's session

- **WHEN** a user requests a session id that belongs to someone else
- **THEN** the system responds `404` and returns no messages

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

### Requirement: Streaming reply reveals smoothly

The web client SHALL reveal an assistant reply at a steady, readable pace rather
than rendering raw network chunks, so a reply that arrives in a few large chunks
still appears to type out progressively.

#### Scenario: Large chunk revealed gradually

- **WHEN** the server delivers assistant text in one or a few large SSE chunks
- **THEN** the client reveals the text incrementally at a steady character rate
  rather than displaying the whole chunk instantly

#### Scenario: Reveal keeps up and completes

- **WHEN** the stream finishes
- **THEN** the client finishes revealing all received text and stops the reveal
  animation, showing the full reply

### Requirement: First-token wait shows a thinking indicator

While the model is producing the first token, the web client SHALL show an
animated "thinking" indicator in place of the assistant reply, and replace it
with text once the first delta arrives.

#### Scenario: Waiting for first token

- **WHEN** a message has been sent and no assistant text has yet arrived
- **THEN** an animated thinking indicator is shown for that pending assistant
  turn

#### Scenario: First token arrives

- **WHEN** the first assistant delta arrives
- **THEN** the thinking indicator is replaced by the streaming reply text

### Requirement: User can stop a generating reply

The web client SHALL let the user stop an in-progress reply. Stopping aborts the
request; the server stream is cancelled on client disconnect.

#### Scenario: Stop mid-stream

- **WHEN** the user activates "stop" while a reply is streaming
- **THEN** the client stops the request, keeps the partial text already shown,
  and re-enables the composer

### Requirement: Assistant messages render markdown

The web client SHALL render assistant message content as markdown (headings,
bold/italic, lists, links, inline and fenced code). User messages remain plain
text. Rendering MUST NOT execute embedded raw HTML/scripts.

#### Scenario: Markdown reply

- **WHEN** an assistant reply contains markdown such as a bulleted list and a
  fenced code block
- **THEN** the client displays a formatted list and a code block, not the raw
  markdown characters

### Requirement: Assistant messages can be copied

The web client SHALL provide a control to copy an assistant message's text to
the clipboard.

#### Scenario: Copy a reply

- **WHEN** the user activates copy on an assistant message
- **THEN** that message's text is placed on the clipboard and the control
  confirms the copy

### Requirement: User can switch light and dark themes

The web client SHALL provide an explicit light/dark theme toggle whose choice
persists across reloads, in addition to following the OS preference by default.

#### Scenario: Toggle and persist

- **WHEN** the user switches the theme and reloads the page
- **THEN** the chosen theme is reapplied

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
(timeout, connection error, overload, or rate limit) with a short backoff, up to a
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

<!-- folded in from polish-ui-to-product-standard (2026-08-17) -->

### Requirement: A conversation can be renamed

Conversation titles SHALL be editable by their owner, so that the primary navigation
reflects what the user calls things rather than a permanent guess made from the first
message.

#### Scenario: The user renames a conversation

- **WHEN** the user sets a new title on a conversation they own
- **THEN** the title is saved and appears wherever that conversation is listed

#### Scenario: Renaming someone else's conversation

- **WHEN** a rename is requested for a conversation belonging to another user
- **THEN** it is refused, exactly as reading that conversation would be

### Requirement: Deleting a conversation is reversible

A deleted conversation SHALL remain restorable for a period after deletion, so that
losing an entire conversation is not the consequence of one mis-tap.

#### Scenario: A conversation is deleted

- **WHEN** the user deletes a conversation
- **THEN** it immediately stops appearing in the conversation list

#### Scenario: A deleted conversation is restored

- **WHEN** a restore is requested for a recently deleted conversation
- **THEN** the conversation returns with the same identity and its messages intact

### Requirement: Conversations are listed for their owner

Conversation listings SHALL return only the requesting user's conversations that have not
been deleted.

#### Scenario: A listing is requested

- **WHEN** the user's conversations are listed
- **THEN** only their non-deleted conversations are returned

#### Scenario: History is requested for a deleted conversation

- **WHEN** message history is requested for a conversation that has been deleted
- **THEN** it is not returned, exactly as for a conversation that never existed
