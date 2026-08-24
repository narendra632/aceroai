# telegram Specification

## Purpose
TBD - created by archiving change add-telegram-channel. Update Purpose after archive.
## Requirements
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

