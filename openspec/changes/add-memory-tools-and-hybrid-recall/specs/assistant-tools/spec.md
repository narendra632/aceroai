## ADDED Requirements

### Requirement: A tool result never misreports what happened

Every tool SHALL return a result that distinguishes success from failure, and the assistant
SHALL describe to the user only what the result reports.

This exists because it was violated: asked to store a fact, the assistant answered
*"Recorded that you completed the AI-901 certification"* when no mechanism to store a fact
existed at all. A tool that cannot fail visibly is worse than a missing tool, because it
teaches the user to trust a report that is not checkable.

#### Scenario: A tool call fails

- **WHEN** a tool cannot complete the action it was asked to perform
- **THEN** it returns an explicit failure
- **AND** the assistant tells the user the action did not happen

#### Scenario: The assistant has no tool for what was asked

- **WHEN** the user asks for something no tool can do
- **THEN** the assistant says it cannot do it, rather than describing it as done

### Requirement: Tool definitions are organised by domain

Each tool's schema SHALL live beside the handler that implements it, grouped by the domain
it acts on, and the full tool set SHALL be assembled from those groups rather than
maintained as one shared list.

Adding a capability is then adding a module, not editing a list that every capability
shares — and a schema cannot be added without its handler.

#### Scenario: A new domain of tools is added

- **WHEN** a new group of assistant tools is introduced
- **THEN** it is added as its own module and picked up by the assembled tool set

#### Scenario: A schema has no handler

- **WHEN** a tool schema exists with no implementation behind it
- **THEN** this is detectable rather than surfacing as a runtime failure mid-conversation
