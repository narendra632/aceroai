## ADDED Requirements

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
