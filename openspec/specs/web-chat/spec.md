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
the system message followed by the session's recent messages in chronological
order.

#### Scenario: Persona leads the context

- **WHEN** context is built for a session
- **THEN** the first message is the SOUL.md persona as a system message, followed
  by the most recent prior messages of that session in order

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

