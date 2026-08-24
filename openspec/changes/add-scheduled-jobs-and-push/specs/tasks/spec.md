# tasks Specification (delta)

## MODIFIED Requirements

### Requirement: The assistant can manage tasks from chat

The assistant SHALL be able to create, read, update, and complete the user's tasks
during a conversation, through the same service layer that backs the API.

This SHALL hold for every caller of the shared message handler, because the behaviour lives
in that handler and in the service layer beneath it rather than in any interface.

#### Scenario: Create a task by asking

- **WHEN** the user tells the assistant to add a task (e.g. "remind me to pay rent
  Friday")
- **THEN** a task is created for that user and the assistant confirms what it added

#### Scenario: Answer from the user's real tasks

- **WHEN** the user asks the assistant what is due
- **THEN** the assistant answers from that user's actual stored tasks

## ADDED Requirements

### Requirement: Tasks that need attention can prompt the system to speak first

The system SHALL be able to notice, without being asked, that the user's tasks require
attention — at minimum that a task's due time has passed — and raise a notification.

Multiple tasks requiring attention at the same time SHALL produce a single notification
describing them collectively, not one per task.

A task SHALL NOT be raised repeatedly for the same condition. Once the user has been told a
task is overdue, that fact SHALL NOT generate a further notification unless the task changes.

A task the user has snoozed SHALL NOT be raised before the time it was snoozed until, and a
task that is completed, dropped or deleted SHALL NOT be raised at all.

#### Scenario: An overdue task is raised

- **WHEN** a task's due time passes and the user has not been told
- **THEN** the system raises a notification identifying that task

#### Scenario: Several at once become one

- **WHEN** more than one task requires attention at the same time
- **THEN** a single notification describes them together

#### Scenario: Not told twice

- **WHEN** the user has already been notified that a task is overdue and nothing about the
  task has changed
- **THEN** no further notification is raised for it

#### Scenario: Snoozed and finished tasks are silent

- **WHEN** a task is snoozed to a future time, or is completed, dropped or deleted
- **THEN** it does not produce a notification
