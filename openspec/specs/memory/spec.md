# memory Specification

## Purpose
Cross-session, cross-channel memory. Durable facts about the user are extracted
from conversations, embedded, stored in `profile_facts` (pgvector), and recalled by
semantic similarity into every session's context — so the assistant knows the user
across chats and channels instead of starting each session blank.

## Requirements
### Requirement: Durable facts are extracted from conversations

After a chat exchange completes, the system SHALL attempt to extract durable
facts about the user from that exchange and persist them. Extraction MUST run off
the reply path (it MUST NOT delay or block the assistant's reply) and MUST be
resilient (a failure to extract, embed, or store MUST NOT surface as an error to
the user).

#### Scenario: A stated preference is captured

- **WHEN** the user tells the assistant a durable fact about themselves (e.g. a
  preference or goal) and the reply has been delivered
- **THEN** the system extracts that fact and stores it without affecting the
  reply the user already received

#### Scenario: Nothing durable is said

- **WHEN** an exchange contains no durable, personal facts
- **THEN** no new fact is stored

#### Scenario: Extraction failure is invisible

- **WHEN** fact extraction, embedding, or storage raises an error
- **THEN** the user still receives their reply normally and no error is shown for
  the memory step

### Requirement: Facts are stored with an embedding, provenance, and status

Each stored fact SHALL be persisted with a vector embedding and with its
provenance and lifecycle status, so it can be searched semantically, trusted,
filtered, and later revised. A fact inferred by the assistant MUST be marked as
inferred and active on creation. The system SHOULD avoid storing a fact that is
semantically equivalent to an existing active fact.

#### Scenario: Inferred fact recorded with an embedding

- **WHEN** the system stores a fact it inferred from a conversation
- **THEN** the fact is persisted with a vector embedding, an inferred source, and
  an active status

#### Scenario: Semantic duplicate not re-stored

- **WHEN** extraction proposes a fact whose meaning matches one already active for
  the user
- **THEN** the system does not create a duplicate active fact

### Requirement: Relevant facts are recalled by semantic search

For each incoming message, the system SHALL retrieve the user's most relevant
active facts by vector similarity to the message and make them available to the
model. Only active facts SHALL be eligible; superseded or rejected facts MUST NOT
be recalled. The number of recalled facts SHALL be bounded by a configurable
limit.

#### Scenario: The most relevant facts are retrieved

- **WHEN** a user sends a message and has several active facts
- **THEN** the facts most semantically relevant to that message are retrieved,
  up to the configured limit, ordered by relevance

#### Scenario: A fact learned earlier informs a new session

- **WHEN** a fact was learned in one session and the user starts a different,
  later session with a related message
- **THEN** the assistant's context for the new session includes that fact

#### Scenario: Inactive facts are excluded

- **WHEN** a user has facts whose status is superseded or rejected
- **THEN** those facts are never recalled into context
