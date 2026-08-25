# notifications Specification

## MODIFIED Requirements

### Requirement: The user can review what they have been told

The application SHALL present the user's notifications in one place, indicate how many are
unread, and allow the user to reach whatever each notification is about.

The user SHALL be able to mark notifications as read, individually and collectively.

The user SHALL be able to remove notifications, individually and — for those already read —
collectively. A removed notification SHALL be recoverable for a short period after the fact,
and SHALL afterwards be invisible to every reader.

While the list is being retrieved, the application SHALL show that it is waiting; it SHALL NOT
present an unretrieved list as an empty one. If retrieval fails, the application SHALL say so
rather than reporting that the user has nothing.

#### Scenario: Seeing that something happened

- **WHEN** the system has raised notifications the user has not read
- **THEN** the application shows that unread notifications exist and how many

#### Scenario: Following a notification to its subject

- **WHEN** the user selects a notification
- **THEN** the application takes them to what the notification is about

#### Scenario: Clearing the unread state

- **WHEN** the user marks notifications as read
- **THEN** the unread indication updates accordingly

#### Scenario: Removing one notification

- **WHEN** the user removes a single notification
- **THEN** it disappears from the list immediately, an undo action is offered for a short
  window, and it no longer counts toward the unread indication

#### Scenario: Clearing what has already been read

- **WHEN** the user clears the notifications they have already read
- **THEN** those notifications are removed together, unread ones are left untouched, and a
  single undo action restores exactly the set that was removed

#### Scenario: The list has not arrived yet

- **WHEN** the user opens the notification list and its contents have not been retrieved
- **THEN** the application indicates that it is waiting, and never states that there are no
  notifications

#### Scenario: The list cannot be retrieved

- **WHEN** retrieving the notification list fails
- **THEN** the failure is reported as a failure, distinctly from the case where the user
  genuinely has no notifications

#### Scenario: Re-opening a list already held

- **WHEN** the user re-opens the notification list while previously retrieved notifications
  are still held
- **THEN** those notifications remain visible while a fresh copy is retrieved, rather than the
  list emptying and refilling

### Requirement: Generated summaries are kept and readable by date

Summaries the system composes about the user's day or period SHALL be stored, associated with
the period they describe, and readable in the application afterwards.

They SHALL be presented distinctly from content the user wrote themselves.

The user SHALL be able to remove a stored summary, recoverable for a short period in the same
way as any other deletion. Removing a summary SHALL NOT cause the work that produced it to run
again, and SHALL NOT cause the system to spend anything composing a replacement.

#### Scenario: Reading a past summary

- **WHEN** the user looks for a summary the system generated on an earlier date
- **THEN** it is available and identified with the period it covers

#### Scenario: Not confused with the user's own writing

- **WHEN** generated summaries and the user's own entries are shown in the same area
- **THEN** it is clear which is which

#### Scenario: Removing a summary

- **WHEN** the user removes a generated summary
- **THEN** it stops appearing, an undo action is offered for a short window, and after that
  window it is gone permanently

#### Scenario: A removed summary is not rewritten

- **WHEN** a generated summary has been removed and the system next considers its scheduled
  work
- **THEN** the occurrence that produced it is still recorded as having run, so no replacement
  is composed and nothing is spent

### Requirement: The user controls when and how often they are interrupted

The system SHALL support a period during which notifications are recorded but not delivered to
devices.

Repeated notifications about the same subject SHALL replace one another on the device rather
than accumulating.

Notification volume SHALL be governed by whether a notification is **news** — that is, by
suppressing repetition of a situation already reported — and SHALL NOT be governed by a ceiling
on the number delivered in a day. A ceiling SHALL remain available to be set deliberately, and
SHALL be absent by default.

A ceiling reached during ordinary use is not a safety limit; it silently discards notifications
the user wanted, beginning with the most frequent ones, which are typically the ones they
asked for.

Suppressed notifications SHALL still be recorded and SHALL remain visible in the application.

#### Scenario: Quiet hours

- **WHEN** the system raises a notification during the user's quiet period
- **THEN** it is not delivered to the device, and it is waiting in the application afterwards

#### Scenario: No ceiling by default

- **WHEN** the user has not deliberately set a ceiling
- **THEN** no notification is withheld from delivery on the grounds of how many were already
  delivered that day

#### Scenario: A daily ceiling

- **WHEN** a ceiling has been deliberately set and that many notifications have been
  delivered that day
- **THEN** further notifications are recorded but not delivered

The invariant is unchanged from when a ceiling was the default; what changed is that one
now applies only if the user asks for it.

#### Scenario: Repeated subject

- **WHEN** a second notification concerns the same subject as one already showing
- **THEN** it replaces the existing one rather than appearing alongside it

## ADDED Requirements

### Requirement: Removing a notification does not make it unsaid

Removing a notification SHALL affect what the user sees, and SHALL NOT affect the system's
record of what it has already done.

Where the system consults past notifications to decide whether something has already been
reported, or to count what has already been delivered, that consultation SHALL include
notifications the user has removed.

#### Scenario: A dismissed nudge does not repeat

- **WHEN** the user removes a notification about an ongoing situation, and the work that
  raised it runs again while that situation is unchanged
- **THEN** it stays silent, exactly as if the notification were still present — removal is not
  a request to be told again

#### Scenario: The delivered count survives removal

- **WHEN** the user removes notifications that were delivered today
- **THEN** the count of what was delivered today is unchanged

#### Scenario: Undelivered notifications never counted

- **WHEN** a notification was recorded but never delivered, and is then removed
- **THEN** the delivered count is unchanged, because that notification never contributed to it
