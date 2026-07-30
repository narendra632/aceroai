# telegram Specification

## Purpose
TBD - created by archiving change add-telegram-channel. Update Purpose after archive.
## Requirements
### Requirement: Telegram messages route through the one brain

The Telegram channel SHALL process each incoming text message by calling
`core/handler.handle_message(user, text, channel="telegram", session_id=...)` and
MUST NOT contain any context-building or LLM-calling logic of its own.

#### Scenario: Authorized message answered

- **WHEN** an authorized user sends a text message to the bot
- **THEN** the channel routes it through `handle_message` and sends the resulting
  reply back to that Telegram chat

#### Scenario: Reply persisted like any channel

- **WHEN** a Telegram exchange completes
- **THEN** the user and assistant turns are persisted to a `chat_sessions` row
  with channel `telegram`, exactly as the handler does for web

### Requirement: Only allowlisted chats are served

The channel SHALL serve only the single user's linked Telegram chat id. Messages
from any other chat MUST NOT reach the handler.

#### Scenario: Linking on first /start

- **WHEN** the bot receives `/start` and no chat id is yet linked to the user
- **THEN** the channel links that sender's chat id to the user and confirms

#### Scenario: Stranger rejected

- **WHEN** a message arrives from a chat id other than the linked one
- **THEN** the channel does not invoke the handler and replies that the chat is
  not authorized

### Requirement: Session continuity per user

Telegram conversations SHALL continue in one ongoing session rather than starting
a new session per message.

#### Scenario: Follow-up keeps context

- **WHEN** an authorized user sends a second message later
- **THEN** it continues the user's existing Telegram session so prior context is
  available to the handler

### Requirement: Poller runs only when configured

The long-poller SHALL start with the app only when a Telegram bot token is
configured, and MUST NOT prevent the app from starting when it is absent.

#### Scenario: No token configured

- **WHEN** the app starts without `TELEGRAM_BOT_TOKEN` set
- **THEN** the poller does not start and the rest of the app runs normally

#### Scenario: Token configured

- **WHEN** the app starts with a valid `TELEGRAM_BOT_TOKEN`
- **THEN** the poller begins long-polling for updates in the background

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

