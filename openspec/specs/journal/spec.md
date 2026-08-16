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

<!-- folded in from polish-ui-to-product-standard (2026-08-17) -->

## ADDED Requirements

### Requirement: A journal entry is editable after it is written

Journal entries SHALL be editable by their author, so that a mistake can be corrected
without deleting the record of the day.

#### Scenario: The user corrects an entry

- **WHEN** the user edits an entry's content, mood, or tags
- **THEN** the change is saved and the entry keeps its identity and its original date

### Requirement: Deleting a journal entry is reversible

A deleted entry SHALL remain restorable for a period after deletion.

#### Scenario: An entry is deleted

- **WHEN** the user deletes a journal entry
- **THEN** it immediately stops appearing in any listing, and stops being visible to the
  assistant

#### Scenario: A deleted entry is restored

- **WHEN** a restore is requested for a recently deleted entry
- **THEN** the entry returns with the same identity and all its field values intact

### Requirement: The journal can be searched and read in pages

Journal listings SHALL support text search and paging, so the screen stays usable as
entries accumulate — the journal being the one surface that grows without bound.

#### Scenario: The user searches the journal

- **WHEN** the user supplies search text
- **THEN** only that user's matching, non-deleted entries are returned

#### Scenario: A large journal is listed

- **WHEN** entries are listed without a limit being reached
- **THEN** results are returned in bounded pages rather than the entire history at once

## MODIFIED Requirements

### Requirement: Journal entries are listed for their owner

Journal listings SHALL return only the requesting user's entries that have not been
deleted, for every reader including the assistant's tools.

#### Scenario: A listing is requested

- **WHEN** any caller lists journal entries
- **THEN** only that user's non-deleted entries are returned

#### Scenario: The assistant reads the journal

- **WHEN** the assistant reads journal entries through its tools
- **THEN** deleted entries are excluded, so it cannot quote an entry the user removed
