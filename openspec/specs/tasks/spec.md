# tasks Specification

## Purpose
TBD - created by archiving change add-journal-tasks. Update Purpose after archive.
## Requirements
### Requirement: Tasks are managed through a user-scoped API

The backend SHALL expose create, list, update, and complete operations for tasks.
Every operation MUST be scoped to the authenticated user; a user MUST NOT be able to
read or modify another user's tasks.

#### Scenario: Create a task

- **WHEN** an authenticated user creates a task with a title (and optional notes,
  priority, and due date)
- **THEN** the task is stored for that user with status `todo` and is returned

#### Scenario: List only the user's tasks

- **WHEN** an authenticated user lists their tasks
- **THEN** only tasks belonging to that user are returned

#### Scenario: Another user's task is not accessible

- **WHEN** a user requests or updates a task id that belongs to a different user
- **THEN** the operation fails and no data is read or changed

### Requirement: Task status follows a defined lifecycle

A task's status SHALL be one of `todo`, `in_progress`, `done`, or `dropped`.
Completing a task SHALL set its status to `done` and record a completion timestamp.

#### Scenario: Completing a task

- **WHEN** a task is completed
- **THEN** its status becomes `done` and its completion time is recorded

#### Scenario: Invalid status is rejected

- **WHEN** an update sets a status outside the allowed set
- **THEN** the update is rejected and the task is unchanged

### Requirement: Tasks are ordered by derived urgency

Task listings SHALL be ordered by an urgency derived at read time from due date,
priority, and snooze — never stored. Overdue tasks rank above due-soon tasks, then by
priority; a task snoozed to a future time ranks below active tasks until that time.

#### Scenario: Overdue outranks later work

- **WHEN** the user lists tasks and one is overdue while another is due next week
- **THEN** the overdue task appears first

#### Scenario: Snoozed task is deprioritized

- **WHEN** a task is snoozed until a future time
- **THEN** it ranks below non-snoozed active tasks until that time passes

### Requirement: The assistant can manage tasks from chat

The assistant SHALL be able to create, read, update, and complete the user's tasks
during a conversation, through the same service layer that backs the API, on any
channel (web and Telegram).

#### Scenario: Create a task by asking

- **WHEN** the user tells the assistant to add a task (e.g. "remind me to pay rent
  Friday")
- **THEN** a task is created for that user and the assistant confirms what it added

#### Scenario: Answer from the user's real tasks

- **WHEN** the user asks the assistant what is due
- **THEN** the assistant answers from that user's actual stored tasks

### Requirement: Creating a task that duplicates an open one is refused

Creating a task SHALL be refused when an open task with an equivalent title already
exists, and the refusal SHALL identify the existing task so the caller can point at it
or update it. Equivalence ignores differences in case, punctuation and spacing.
Callers that genuinely want a second copy MAY override this explicitly.

#### Scenario: An equivalent open task blocks creation

- **WHEN** a task is created whose title matches an open task apart from case,
  punctuation or spacing
- **THEN** creation is refused, the existing task is identified, and no second task is
  stored

#### Scenario: Differently worded work is still allowed

- **WHEN** a task is created whose title is worded differently from every open task
- **THEN** it is created normally

#### Scenario: Completed work does not block new work

- **WHEN** a task is created with the same title as a task that is already done
- **THEN** it is created normally, so recurring work is possible

#### Scenario: A duplicate can be forced deliberately

- **WHEN** a caller explicitly allows duplicates
- **THEN** the task is created even though an equivalent open task exists

<!-- folded in from polish-ui-to-product-standard (2026-08-17) -->

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
