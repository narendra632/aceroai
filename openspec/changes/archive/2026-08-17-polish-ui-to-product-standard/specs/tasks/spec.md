## ADDED Requirements

### Requirement: A task is editable after it is created

Every field a task stores SHALL be editable by its owner, so that correcting a task never
requires destroying and re-creating it — which would change its identity and break
anything referring to it.

#### Scenario: The user corrects a task

- **WHEN** the user edits a task's title, notes, due date, priority, status, or snooze time
- **THEN** the change is saved and the task keeps the same identity

#### Scenario: The assistant wrote a field the interface never showed

- **WHEN** the assistant has set notes or a snooze time on a task through its tools
- **THEN** the user can read and edit those values in the interface — no field the API
  already accepts is left without a way to see it

### Requirement: Deleting a task is reversible

A deleted task SHALL remain restorable for a period after deletion, so an accidental
deletion can be undone.

#### Scenario: A task is deleted

- **WHEN** the user deletes a task
- **THEN** it immediately stops appearing in any listing, and stops being visible to the
  assistant

#### Scenario: A deleted task is restored

- **WHEN** a restore is requested for a recently deleted task
- **THEN** the task returns with the same identity and all its field values intact

#### Scenario: Restoring someone else's task

- **WHEN** a restore is requested for a task belonging to another user
- **THEN** it is refused, exactly as reading that task would be

## MODIFIED Requirements

### Requirement: Tasks are listed for their owner

Task listings SHALL return only the requesting user's tasks that have not been deleted, so
that no reader — the API, the assistant's context, or the assistant's tools — can observe
a deleted task.

#### Scenario: A listing is requested

- **WHEN** any caller lists tasks
- **THEN** only that user's non-deleted tasks are returned

#### Scenario: The assistant is given the user's open tasks

- **WHEN** the open-task list is assembled for the assistant's context
- **THEN** deleted tasks are excluded, so the assistant cannot describe or act on a task
  the user has removed

#### Scenario: A duplicate check runs against existing tasks

- **WHEN** a new task is checked against existing open tasks
- **THEN** deleted tasks are not considered — a deleted task never blocks creating a new
  one with the same title
