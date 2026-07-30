## ADDED Requirements

### Requirement: `/think` routes a Telegram message to deeper reasoning

The Telegram channel SHALL treat a message prefixed with `/think` as an explicit
request for deeper reasoning: it strips the prefix and routes the remaining text
through the one-brain handler with the deeper reasoning effort. A `/think` with no
message SHALL prompt for one and MUST NOT call the handler.

#### Scenario: Think-harder message

- **WHEN** an authorized user sends `/think <message>`
- **THEN** the channel routes `<message>` (without the prefix) through the handler
  with the deeper reasoning effort and replies as usual

#### Scenario: Bare /think

- **WHEN** an authorized user sends just `/think` with no message
- **THEN** the channel asks them to add a message and does not call the handler
