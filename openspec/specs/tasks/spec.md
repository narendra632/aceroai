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

