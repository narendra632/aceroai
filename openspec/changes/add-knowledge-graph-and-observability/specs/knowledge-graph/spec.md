# knowledge-graph Specification

## Purpose
Make the assistant's memory visible and correctable by the person it is about. Facts the
system has inferred are exposed as a browsable, searchable semantic graph, with provenance,
and with the ability to confirm, correct, or forget any of them.

## Requirements

### Requirement: Stored facts are visible to the user

Every fact the system holds about the user SHALL be readable by that user through the
interface. No fact that influences a conversation may be unreachable.

#### Scenario: The user opens the knowledge view

- **WHEN** the user opens the knowledge view
- **THEN** every active fact the system holds about them is listed, with its category,
  confidence, and whether it was stated or inferred

#### Scenario: A fact influences a reply

- **WHEN** a fact is recalled into a conversation's context
- **THEN** that same fact is visible in the knowledge view — nothing informs a reply while
  remaining hidden from the user

### Requirement: Facts are presented as a semantic graph

Facts SHALL be presentable as a graph whose edges express semantic similarity, so the user
can see relationships between things they never stated together.

#### Scenario: Related facts are connected

- **WHEN** the graph is displayed
- **THEN** each fact is connected to its nearest neighbours by meaning, and the connection
  exists regardless of whether the two facts share any words

#### Scenario: Vectors stay on the server

- **WHEN** the client requests the graph
- **THEN** it receives facts and the relationships between them, and never the underlying
  embedding vectors

#### Scenario: The view is usable on a small screen

- **WHEN** the knowledge view is opened on a narrow screen
- **THEN** a list presentation is shown by default, offering the same data and the same
  actions as the graph

### Requirement: Every fact can be traced to its origin

A fact created from a conversation SHALL record which conversation turn produced it, and
the user SHALL be able to reach that turn.

#### Scenario: The user questions a fact

- **WHEN** the user selects a fact that was inferred from a conversation
- **THEN** they are shown when it was learned and can open the conversation it came from

#### Scenario: A fact has no conversational origin

- **WHEN** a fact was not produced by a conversation
- **THEN** it is shown without an origin rather than with a misleading one

### Requirement: The user can confirm a fact

The user SHALL be able to confirm an inferred fact, marking it as stated by the user rather
than guessed by the assistant.

#### Scenario: An inferred fact is confirmed

- **WHEN** the user confirms a fact
- **THEN** it is recorded as stated at full confidence, and is treated as more
  authoritative than a conflicting inference

### Requirement: Correcting a fact preserves what it replaced

Editing a fact SHALL create a replacement and mark the original as superseded by it. The
original MUST NOT be destroyed, and MUST stop influencing conversations.

#### Scenario: The user corrects a fact

- **WHEN** the user edits a fact's text
- **THEN** a replacement fact becomes active, the original is marked superseded and linked
  to its replacement, and only the replacement is recalled into future conversations

#### Scenario: The user reviews how a fact changed

- **WHEN** the user views a fact that replaced an earlier one
- **THEN** the earlier version is reachable from it

#### Scenario: A corrected fact is searchable by meaning

- **WHEN** a replacement fact is created
- **THEN** it is embedded, so it participates in semantic recall exactly as any other fact

### Requirement: Forgetting a fact is reversible

The user SHALL be able to forget a fact. A forgotten fact MUST immediately stop being
visible and stop influencing conversations, and MUST remain restorable for a period.

#### Scenario: A fact is forgotten

- **WHEN** the user forgets a fact
- **THEN** it disappears from the knowledge view and stops being recalled into any
  conversation on any channel

#### Scenario: A forgotten fact is restored

- **WHEN** a restore is requested for a recently forgotten fact
- **THEN** it returns with the same identity and all its values intact

#### Scenario: Forgetting another user's fact

- **WHEN** a forget or restore is requested for a fact belonging to another user
- **THEN** it is refused, exactly as reading that fact would be

### Requirement: Facts can be searched and filtered

The knowledge view SHALL support finding a fact without scrolling the whole collection.

#### Scenario: The user searches for a fact

- **WHEN** the user enters search text
- **THEN** only facts matching that text are shown

#### Scenario: The user narrows by attribute

- **WHEN** the user filters by category, source, or status
- **THEN** only facts matching the selected attributes are shown

### Requirement: The knowledge view distinguishes empty from broken

#### Scenario: Nothing has been learned yet

- **WHEN** the user has no stored facts
- **THEN** the view states that nothing has been learned yet

#### Scenario: The facts cannot be loaded

- **WHEN** loading facts fails
- **THEN** the failure is reported as a failure, with a way to retry — never rendered as an
  empty memory
