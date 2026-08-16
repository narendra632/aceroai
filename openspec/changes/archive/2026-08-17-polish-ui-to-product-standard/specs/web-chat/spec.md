## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Conversations are listed for their owner

Conversation listings SHALL return only the requesting user's conversations that have not
been deleted.

#### Scenario: A listing is requested

- **WHEN** the user's conversations are listed
- **THEN** only their non-deleted conversations are returned

#### Scenario: History is requested for a deleted conversation

- **WHEN** message history is requested for a conversation that has been deleted
- **THEN** it is not returned, exactly as for a conversation that never existed
