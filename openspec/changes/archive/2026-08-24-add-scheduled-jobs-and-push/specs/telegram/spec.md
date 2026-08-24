# telegram Specification (retired)

## ADDED Requirements

### Requirement: Conversations held on a retired channel are preserved as they happened

When a conversational channel is withdrawn, conversations that took place on it SHALL be
retained and SHALL remain readable alongside every other conversation.

The record of **which** channel a conversation happened on SHALL NOT be rewritten to name a
different one, and SHALL NOT be removed in order to simplify a constraint. A retired
channel's identifier therefore remains valid for existing records even though nothing can
create new ones.

This is the only requirement that survives the retirement of the Telegram channel, and it
exists because the alternatives — rewriting those conversations as web conversations, or
deleting them — would both make the system misstate its own history.

#### Scenario: Past conversations remain readable

- **WHEN** the user looks back through their conversations after a channel has been retired
- **THEN** conversations held on that channel are present and readable

#### Scenario: The record is not rewritten

- **WHEN** a channel is retired
- **THEN** existing records continue to name that channel, rather than being relabelled as
  having happened somewhere else

#### Scenario: No new conversations on a retired channel

- **WHEN** a channel has been retired
- **THEN** the system provides no way to start a conversation on it

## REMOVED Requirements

### Requirement: Telegram messages route through the one brain

**Reason**: The Telegram channel is retired. Web push, delivered through the browser the user
already has, replaces it as the way Acero reaches the user when the app is not open — without
a third-party bot account, without a long-polling loop that only runs while the backend is up,
and without a credential that can leak. This bot's token did leak into production startup logs
before it was caught and redacted, which is the strongest single argument against keeping it.

**Migration**: Conversations that took place over Telegram are **preserved unchanged**. Their
`chat_sessions` rows keep `channel = 'telegram'`, and the CHECK constraint continues to permit
that value, because rewriting those rows would make the record misstate where the conversations
happened. `users.telegram_chat_id` is dropped, `TELEGRAM_BOT_TOKEN` is removed from
configuration, and `app/channels/` is deleted. The `one brain` rule is unaffected:
`handle_message` remains channel-agnostic and still takes a `channel` argument, so adding a
channel back is a small change rather than a rewrite. **The bot token must be revoked with
@BotFather.**

#### Scenario: Authorized message answered

- **WHEN** an authorized user sends a text message to the bot
- **THEN** the channel routes it through `handle_message` and sends the resulting
  reply back to that Telegram chat

#### Scenario: Reply persisted like any channel

- **WHEN** a Telegram exchange completes
- **THEN** the user and assistant turns are persisted to a `chat_sessions` row
  with channel `telegram`, exactly as the handler does for web

### Requirement: Only allowlisted chats are served

**Reason**: Removed with the channel it protects. Its purpose — ensuring only the owner is
served — is now met by the same bearer-token authentication as every other route, rather than
by a channel-specific allowlist maintained by hand.

**Migration**: None. No replacement is needed; web push subscriptions are registered against
an authenticated account and cannot be claimed by a stranger sending a message.

#### Scenario: Linking on first /start

- **WHEN** the bot receives `/start` and no chat id is yet linked to the user
- **THEN** the channel links that sender's chat id to the user and confirms

#### Scenario: Stranger rejected

- **WHEN** a message arrives from a chat id other than the linked one
- **THEN** the channel does not invoke the handler and replies that the chat is
  not authorized

### Requirement: Session continuity per user

**Reason**: Removed with the channel. Session continuity on the web is provided by the
`web-chat` capability, which the user interacts with directly.

**Migration**: None. Existing Telegram sessions remain readable in the conversation list.

#### Scenario: Follow-up keeps context

- **WHEN** an authorized user sends a second message later
- **THEN** it continues the user's existing Telegram session so prior context is
  available to the handler

### Requirement: Poller runs only when configured

**Reason**: Removed with the channel. The background slot the poller occupied in the
application lifespan is now held by the job scheduler.

**Migration**: An existing `TELEGRAM_BOT_TOKEN` line left in a deployed `.env` is harmless —
configuration ignores unknown keys — so no operator action is required for the application to
start. Revoking the token is a separate and recommended step.

#### Scenario: No token configured

- **WHEN** the app starts without `TELEGRAM_BOT_TOKEN` set
- **THEN** the poller does not start and the rest of the app runs normally

#### Scenario: Token configured

- **WHEN** the app starts with a valid `TELEGRAM_BOT_TOKEN`
- **THEN** the poller begins long-polling for updates in the background

### Requirement: `/think` routes a Telegram message to deeper reasoning

**Reason**: Removed with the channel. Adaptive reasoning itself is unaffected — the
"think harder" control in the web interface remains, and it is the same per-request effort
setting that `/think` invoked.

**Migration**: Use the think-harder control in the web composer, which routes through the same
`reasoning_effort` path.

#### Scenario: Think-harder message

- **WHEN** an authorized user sends `/think <message>`
- **THEN** the channel routes `<message>` (without the prefix) through the handler
  with the deeper reasoning effort and replies as usual

#### Scenario: Bare /think

- **WHEN** an authorized user sends just `/think` with no message
- **THEN** the channel asks them to add a message and does not call the handler
