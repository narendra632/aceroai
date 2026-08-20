# memory Specification

## Purpose
Cross-session, cross-channel memory. Durable facts about the user are extracted
from conversations, embedded, stored in `profile_facts` (pgvector), and recalled by
semantic similarity into every session's context — so the assistant knows the user
across chats and channels instead of starting each session blank.

## Requirements
### Requirement: Durable facts are extracted from conversations

After a chat exchange completes, the system SHALL attempt to extract durable facts about
the user from that exchange and persist them. Extraction MUST run off the reply path (it
MUST NOT delay or block the assistant's reply) and MUST be resilient (a failure to extract,
embed, or store MUST NOT surface as an error to the user).

The context supplied to extraction SHALL be **bounded** and MUST NOT grow with the total
number of facts held. Preventing duplicates MUST NOT depend on showing the extractor every
known fact; the guarantee lives in the semantic duplicate check applied to the result.

#### Scenario: A stated preference is captured

- **WHEN** the user tells the assistant a durable fact about themselves (e.g. a preference
  or goal) and the reply has been delivered
- **THEN** the system extracts that fact and stores it without affecting the reply the user
  already received

#### Scenario: Nothing durable is said

- **WHEN** an exchange contains no durable, personal facts
- **THEN** no new fact is stored

#### Scenario: Extraction failure is invisible

- **WHEN** fact extraction, embedding, or storage raises an error
- **THEN** the user still receives their reply normally and no error is shown for the
  memory step

#### Scenario: The stored memory is large

- **WHEN** extraction runs for a user holding a large number of facts
- **THEN** the work done per exchange does not grow in proportion to how many facts are
  held

#### Scenario: Duplicates are still prevented under a bounded context

- **WHEN** extraction produces a fact that duplicates one the extractor was not shown
- **THEN** that fact is still not stored a second time

### Requirement: Facts are stored with an embedding, provenance, and status

Each stored fact SHALL be persisted with a vector embedding and with its provenance and
lifecycle status, so it can be searched semantically, trusted, filtered, and later revised.
A fact inferred by the assistant MUST be marked as inferred and active on creation. The
system SHOULD avoid storing a fact that is semantically equivalent to an existing active
fact.

A fact extracted from a conversation SHALL additionally record **which conversation turn
produced it**, so its origin can be inspected. A fact the user has explicitly confirmed
SHALL be recorded as stated rather than inferred.

When a newly extracted fact is semantically close to an existing active fact, the system
SHALL distinguish a **repetition** from a **change**. A repetition is not stored again. A
change SHALL supersede the existing fact rather than being discarded, so that newer truth
replaces older belief instead of being lost to the duplicate check.

#### Scenario: Inferred fact recorded with an embedding

- **WHEN** the system stores a fact it inferred from a conversation
- **THEN** the fact is persisted with a vector embedding, an inferred source, and an active
  status

#### Scenario: The originating turn is recorded

- **WHEN** a fact is extracted from a conversation turn
- **THEN** the identity of that turn is stored with the fact

#### Scenario: Semantic duplicate not re-stored

- **WHEN** an extracted fact restates something already held as active
- **THEN** it is not stored a second time

#### Scenario: A fact about the user has changed

- **WHEN** an extracted fact is close in meaning to an existing active fact but asserts
  something different
- **THEN** the new fact becomes active and the existing fact is marked superseded by it —
  the new fact is **not** discarded as a duplicate

#### Scenario: A fact is confirmed by the user

- **WHEN** the user confirms an inferred fact
- **THEN** it is recorded as stated at full confidence

### Requirement: Relevant facts are recalled by semantic search

Before generating a reply, the system SHALL retrieve the facts most semantically relevant
to the user's message and include them in the model's context. Recall MUST be best-effort:
if embedding or search fails or exceeds its time budget, the reply proceeds without facts.
The number of recalled facts SHALL be bounded by a configurable limit.

Facts that are superseded, rejected, or that the user has forgotten MUST NOT be recalled.

#### Scenario: Relevant facts inform the reply

- **WHEN** the user sends a message related to something previously learned
- **THEN** the most relevant facts are included in the context used to generate the reply,
  up to the configured limit, ordered by relevance

#### Scenario: A fact learned earlier informs a new session

- **WHEN** a fact was learned in one session and the user starts a different, later session
  with a related message
- **THEN** the assistant's context for the new session includes that fact

#### Scenario: Recall fails or is slow

- **WHEN** embedding or the similarity search fails or exceeds its time budget
- **THEN** the reply is produced without recalled facts and no error is shown

#### Scenario: A superseded fact is not recalled

- **WHEN** a fact has been superseded by a newer one
- **THEN** only the newer fact can be recalled

#### Scenario: Inactive facts are excluded

- **WHEN** a user has facts whose status is superseded or rejected
- **THEN** those facts are never recalled into context

#### Scenario: A forgotten fact is not recalled

- **WHEN** the user has forgotten a fact
- **THEN** it is excluded from recall on every channel

### Requirement: Recall serves extraction as well as replies

The facts retrieved for a reply SHALL be reusable as the extractor's view of what is
already known, so that bounding the extraction context costs no additional provider calls.

#### Scenario: An exchange completes

- **WHEN** facts have been recalled to answer a message and extraction subsequently runs
  for that exchange
- **THEN** extraction reuses those already-retrieved facts rather than performing another
  retrieval
