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
