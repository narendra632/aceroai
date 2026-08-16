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
