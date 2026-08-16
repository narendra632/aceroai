## ADDED Requirements

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
