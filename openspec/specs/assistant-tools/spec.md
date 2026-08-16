# assistant-tools Specification

## Purpose
TBD - created by archiving change add-journal-tasks. Update Purpose after archive.
## Requirements
### Requirement: The assistant can take actions within a chat turn via tools

Within a single conversation turn, the assistant SHALL be able to call one or more
tools, have the backend execute them against the user's data, and use the results to
form its reply — without the user leaving the chat. This behavior SHALL be identical
across channels (web and Telegram), because it lives in the shared message handler.

#### Scenario: A tool call is executed and answered

- **WHEN** the model responds to a message with a tool call rather than text
- **THEN** the backend executes the tool, feeds the result back to the model, and the
  model's final text reply reflects that result

#### Scenario: Same behavior on every channel

- **WHEN** the same actionable request is sent from web or from Telegram
- **THEN** the assistant performs the same action through the same service layer

### Requirement: Tools operate only on the current user's data

Every tool SHALL act solely on the authenticated user's records. The model MUST NOT be
able to select another user; any record id it supplies MUST be verified to belong to
the current user or the call fails without effect.

#### Scenario: Foreign id is refused

- **WHEN** the model calls a tool with a record id that is not the current user's
- **THEN** the tool call fails safely and nothing is read or changed

### Requirement: The assistant acts on clear requests and confirms risky ones

The assistant SHALL perform single create/update actions when the user's intent is
clear, and SHALL offer rather than silently act when intent is vague. Destructive or
bulk actions (deletions, clearing many items) SHALL require the user's confirmation
before they are carried out.

#### Scenario: Clear request acts immediately

- **WHEN** the user clearly asks to add or update one item
- **THEN** the assistant performs it and reports what it did

#### Scenario: Destructive action confirms first

- **WHEN** the user asks to delete an item or clear many at once
- **THEN** the assistant asks for confirmation before carrying it out

#### Scenario: Vague mention is offered, not forced

- **WHEN** the user only implies a possible task ("I keep forgetting X")
- **THEN** the assistant offers to add it rather than creating it silently

### Requirement: The tool loop is bounded and fault-tolerant

The action loop SHALL be bounded to a maximum number of tool rounds per turn. A
malformed tool call, an unknown id, or a service error SHALL be returned to the model
as a structured result so it can self-correct or explain, and SHALL NOT crash the
chat turn.

#### Scenario: Bounded iterations

- **WHEN** a turn would exceed the maximum number of tool rounds
- **THEN** the loop stops and the assistant responds with what it has

#### Scenario: A failed tool call is recovered

- **WHEN** a tool call is malformed or errors
- **THEN** the failure is reported back to the model and the turn still completes with
  a coherent reply

### Requirement: The assistant is aware of the user's open tasks

The user's open tasks SHALL be part of the assistant's context on every conversational
turn, so it can act on what already exists rather than working blind. This awareness
MUST be scoped to the requesting user and MUST NOT depend on the assistant choosing to
look them up first.

#### Scenario: A task that already exists is not created again

- **WHEN** the user asks for a task that is already open
- **THEN** the assistant says it already exists and offers to change it, instead of
  creating a second copy

#### Scenario: Acting on a known task takes one step

- **WHEN** the user refers to an existing task (e.g. "mark the rent one done")
- **THEN** the assistant acts on that task directly, without first having to look up
  the list

#### Scenario: Due and overdue work is surfaced

- **WHEN** the user starts a conversation and has tasks due or overdue
- **THEN** the assistant can mention them without being asked

#### Scenario: Awareness never crosses users

- **WHEN** context is built for a user
- **THEN** only that user's tasks are included

#### Scenario: An empty list is stated, not guessed

- **WHEN** the user has no open tasks
- **THEN** the assistant is told so explicitly, rather than being left to infer a list

<!-- folded in from polish-ui-to-product-standard (2026-08-17) -->

## MODIFIED Requirements

### Requirement: The assistant only ever sees the user's live data

Every record the assistant can read or act on SHALL exclude anything the user has deleted,
so the assistant cannot describe, reference, or modify something the user believes is
gone.

#### Scenario: The assistant lists the user's tasks

- **WHEN** the assistant reads tasks through its tools
- **THEN** deleted tasks are absent from the result

#### Scenario: The assistant is given context for a turn

- **WHEN** the user's open tasks are injected into the assistant's context
- **THEN** deleted tasks are absent — otherwise the assistant would confidently act on a
  task the user removed, which is worse than not knowing about it

#### Scenario: The assistant acts on a deleted record by id

- **WHEN** the assistant refers to a record that has since been deleted
- **THEN** the tool reports that it does not exist, in the same structured way it reports
  any unknown id, and the assistant recovers rather than failing the turn

#### Scenario: The exclusion is applied in one place

- **WHEN** a new tool or a new read path is added
- **THEN** it inherits the exclusion from the shared service layer rather than restating
  it, so a new caller cannot forget it
