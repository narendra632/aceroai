## MODIFIED Requirements

### Requirement: Facts are stored with an embedding, provenance, and status

Each stored fact SHALL be persisted with a vector embedding and with its provenance and
lifecycle status, so it can be searched semantically, trusted, filtered, and later revised.
A fact inferred by the assistant MUST be marked as inferred and active on creation.

A fact extracted from a conversation SHALL additionally record **which conversation turn
produced it**, so its origin can be inspected. A fact the user has explicitly confirmed
SHALL be recorded as stated rather than inferred.

When a newly proposed fact is semantically close to an existing active fact, the system
SHALL distinguish a **repetition** from a **change**. A repetition is not stored again. A
change SHALL supersede the existing fact rather than being discarded.

**A proposed fact SHALL NOT be discarded without a trace.** Semantic similarity measures
subject matter, not identity: two different certifications differing only by their code
measure closer together than two phrasings of the same fact about family. Where the system
cannot tell a repetition from a change, it SHALL store the fact and mark it as a possible
duplicate, so the ambiguity is visible and correctable rather than resolved by deletion.

#### Scenario: Inferred fact recorded with an embedding

- **WHEN** the system stores a fact it inferred from a conversation
- **THEN** the fact is persisted with a vector embedding, an inferred source, and an active
  status

#### Scenario: The originating turn is recorded

- **WHEN** a fact is extracted from a conversation turn
- **THEN** the identity of that turn is stored with the fact

#### Scenario: Semantic duplicate not re-stored

- **WHEN** an extracted fact restates something already held as active, and is identified as
  a restatement
- **THEN** it is not stored a second time

#### Scenario: A fact about the user has changed

- **WHEN** an extracted fact is close in meaning to an existing active fact but asserts
  something different
- **THEN** the new fact becomes active and the existing fact is marked superseded by it —
  the new fact is **not** discarded as a duplicate

#### Scenario: Two similar facts that are genuinely different

- **WHEN** a proposed fact is close in wording to an existing fact but the system cannot
  establish that it restates it
- **THEN** the fact is stored and marked as a possible duplicate of the existing one
- **AND** it is never silently dropped

#### Scenario: A fact is confirmed by the user

- **WHEN** the user confirms an inferred fact
- **THEN** it is recorded as stated at full confidence

### Requirement: Relevant facts are recalled by semantic search

Before generating a reply, the system SHALL retrieve the facts most relevant to the user's
message and include them in the model's context. Recall MUST be best-effort: if retrieval
fails or exceeds its time budget, the reply proceeds without facts. The number of recalled
facts SHALL be bounded by a configurable limit.

Relevance SHALL be determined by **more than vector similarity alone**. Every fact about
one person occupies a narrow band of semantic distance, so distance can establish that a
fact concerns the user but cannot establish that it answers their message. The limit is a
**ceiling, not a quota**: a message that nothing stored is relevant to SHALL recall nothing.

Facts that are superseded, rejected, or that the user has forgotten MUST NOT be recalled by
any retrieval path.

#### Scenario: Relevant facts inform the reply

- **WHEN** the user sends a message related to something previously learned
- **THEN** the facts that address that message rank above facts that merely concern the
  user, up to the configured limit

#### Scenario: A message unrelated to anything stored

- **WHEN** the user's message is not about themselves at all
- **THEN** no facts are recalled, rather than the limit being filled with the least
  irrelevant ones

#### Scenario: A fact learned earlier informs a new session

- **WHEN** a fact was learned in one session and the user starts a different, later session
  with a related message
- **THEN** the assistant's context for the new session includes that fact

#### Scenario: Recall fails or is slow

- **WHEN** retrieval fails or exceeds its time budget
- **THEN** the reply is produced without recalled facts and no error is shown

#### Scenario: A superseded fact is not recalled

- **WHEN** a fact has been superseded by a newer one
- **THEN** only the newer fact can be recalled

#### Scenario: Inactive facts are excluded

- **WHEN** a user has facts whose status is superseded or rejected
- **THEN** those facts are never recalled into context, by any retrieval path

#### Scenario: A forgotten fact is not recalled

- **WHEN** the user has forgotten a fact
- **THEN** it is excluded from recall on every channel and by every retrieval path

## ADDED Requirements

### Requirement: Memory has exactly one writer

Every path that creates, changes or removes a fact — the assistant's tools and the
background extractor alike — SHALL go through one service function, so validation,
duplicate judgement, supersession and provenance are implemented once.

#### Scenario: The same fact arrives by two routes

- **WHEN** an identical fact is written once by an assistant tool and once by background
  extraction
- **THEN** both are validated, deduplicated and recorded by the same rules

### Requirement: The user can ask the assistant to remember, correct or forget

The assistant SHALL be able to write a fact on the user's explicit instruction, within the
conversation, rather than only inferring facts in the background.

The assistant SHALL NOT report a memory change it did not make. A write either succeeds and
is verifiable, or it fails and the failure is reported.

#### Scenario: The user asks for something to be remembered

- **WHEN** the user tells the assistant to remember a fact about them
- **THEN** the fact is stored immediately and is visible to the user
- **AND** it is recalled in later sessions

#### Scenario: The user corrects something the assistant believes

- **WHEN** the user tells the assistant that a stored fact is wrong
- **THEN** the corrected fact becomes active and the previous one is superseded, preserving
  the history

#### Scenario: A memory write fails

- **WHEN** storing, correcting or forgetting a fact fails
- **THEN** the assistant reports that it failed
- **AND** it does not claim the change was made

### Requirement: Changes to memory made during a conversation are announced

When the assistant supersedes or forgets a fact while replying, it SHALL say so in that
reply, so the user can check the claim against what is stored rather than discovering the
change later or not at all.

#### Scenario: The assistant corrects a fact mid-conversation

- **WHEN** the assistant replaces or forgets a stored fact during a reply
- **THEN** the reply states what changed

### Requirement: Unattended extraction cannot delete

Background extraction SHALL be able to add facts and supersede them, but SHALL NOT be able
to delete them. Superseding preserves what it replaced; deletion in a loop with no human
present does not.

#### Scenario: Background extraction contradicts a stored fact

- **WHEN** extraction produces a fact that replaces an existing one
- **THEN** the existing fact is superseded and remains inspectable, and no fact is deleted

### Requirement: The user can see which facts were used

The facts recalled for a reply SHALL be inspectable by the user for that reply. Memory that
cannot be inspected cannot be trusted or corrected: this change exists because a fact was
silently absent and there was no way to notice.

What is shown MUST be exactly what was sent to the model.

#### Scenario: The user asks why the assistant answered as it did

- **WHEN** the user opens the recall detail for a reply
- **THEN** the facts that were injected for that message are listed

#### Scenario: Nothing was recalled

- **WHEN** no facts were relevant to a message
- **THEN** the interface offers nothing to open, rather than showing an empty list
