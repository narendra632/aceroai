# journal Specification

## Purpose
TBD - created by archiving change add-journal-tasks. Update Purpose after archive.
## Requirements
### Requirement: Journal entries are managed through a user-scoped API

The backend SHALL expose create and list operations for journal entries (and edit/
delete of the user's own entries). Every operation MUST be scoped to the authenticated
user; a user MUST NOT read or modify another user's entries.

#### Scenario: Add a journal entry

- **WHEN** an authenticated user adds an entry with content (and optional mood and
  tags)
- **THEN** the entry is stored for that user with its date and origin channel, and is
  returned

#### Scenario: List only the user's entries

- **WHEN** an authenticated user lists their journal
- **THEN** only that user's entries are returned, most recent first

### Requirement: A journal entry captures date, content, optional mood, and tags

An entry SHALL record an entry date, free-text content, an optional mood on a 1–5
scale, an optional set of tags, and the channel it originated from. Multiple entries
per day SHALL be allowed.

#### Scenario: Mood out of range is rejected

- **WHEN** an entry is submitted with a mood outside 1–5
- **THEN** the entry is rejected

#### Scenario: Two entries on the same day

- **WHEN** the user adds a second entry on a day that already has one
- **THEN** both entries are stored and listed

### Requirement: The assistant can journal from chat

The assistant SHALL be able to add and read the user's journal entries during a
conversation, through the same service layer that backs the API, on any channel. An
entry the assistant creates SHALL record its origin as the assistant.

#### Scenario: Log a moment by asking

- **WHEN** the user asks the assistant to log something (e.g. "journal that today went
  well, mood 4")
- **THEN** a journal entry is created for that user with the given content and mood

#### Scenario: Recall from the journal

- **WHEN** the user asks the assistant what they wrote recently
- **THEN** the assistant answers from that user's actual entries

