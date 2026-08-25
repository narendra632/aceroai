# notifications Specification

## Purpose
TBD - created by archiving change add-scheduled-jobs-and-push. Update Purpose after archive.
## Requirements
### Requirement: A notification is stored before it is delivered

Every notification the system raises SHALL be persisted as a durable record before any attempt
is made to deliver it to a device.

The record SHALL survive a delivery that fails, a device that is unreachable, a permission the
user has refused, and a notification the user dismissed without reading.

#### Scenario: Delivery fails, the record remains

- **WHEN** the system raises a notification and delivery to the device fails
- **THEN** the notification is still present in the application for the user to read

#### Scenario: Permission was never granted

- **WHEN** the user has not permitted device notifications
- **THEN** notifications are still recorded and readable inside the application

#### Scenario: Dismissed on the device

- **WHEN** the user dismisses a delivered notification without opening it
- **THEN** the notification remains unread inside the application

### Requirement: Failed delivery is not failed work

A failure to deliver a notification to a device SHALL NOT be reported as a failure of the work
that raised it, and SHALL be recorded against the delivery target instead.

#### Scenario: An unreachable device

- **WHEN** work completes successfully and its notification cannot be delivered
- **THEN** the work is recorded as successful, and the delivery failure is recorded against
  the device

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

### Requirement: Devices are registered by the user and removed when they stop working

The user SHALL be able to permit device notifications, and the system SHALL register that
device against their account.

When a delivery target reports that it no longer exists, the system SHALL remove it rather
than retrying it.

When a device reports that its registration has changed, the system SHALL re-register it
without user action.

#### Scenario: Permitting notifications

- **WHEN** the user permits device notifications
- **THEN** the device is registered and can receive them

#### Scenario: A device that no longer exists

- **WHEN** delivery reports that the target is permanently gone
- **THEN** that target is removed and is not used again

#### Scenario: A registration that changes on its own

- **WHEN** the device's registration is replaced by the browser
- **THEN** the new registration replaces the old one without the user being asked again

### Requirement: The permission state is reported honestly, including when it is refused

The application SHALL show the current state of device-notification permission, and SHALL
distinguish not yet asked, granted, and refused.

Where the application cannot request permission again, it SHALL say so and explain what the
user would have to do instead.

Where a platform requires the application to be installed before it can deliver notifications,
the application SHALL state that requirement before the user attempts to enable them.

#### Scenario: Permission has been refused

- **WHEN** the user has previously refused device notifications
- **THEN** the application states that it cannot ask again and explains where the user can
  change it

#### Scenario: Installation is a precondition

- **WHEN** the platform requires installation before notifications can be delivered
- **THEN** the application says so rather than offering an option that will not work

### Requirement: The user can verify delivery works, at any time

The application SHALL provide a way for the user to send themselves a notification on demand,
so that the delivery path can be confirmed without waiting for the system to have something
to say.

#### Scenario: Confirming the setup

- **WHEN** the user asks the application to send a test notification
- **THEN** a notification is delivered to the registered device, or the reason it was not is
  reported

### Requirement: Delivered content is a pointer, not the substance

A notification delivered to a device SHALL carry only enough to identify what happened and
where to go. The substance SHALL remain inside the application.

Notification content SHALL be protected in transit such that the delivery infrastructure
cannot read it.

#### Scenario: The device shows a summary

- **WHEN** a notification is delivered
- **THEN** it presents a short line and a destination, and the full content is read in the
  application

#### Scenario: Intermediaries cannot read it

- **WHEN** a notification passes through third-party delivery infrastructure
- **THEN** its content is not readable by that infrastructure

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

### Requirement: Credentials for delivery never enter the interface

Keys used to authorize notification delivery SHALL come from server configuration only.

The application SHALL NOT provide any means of entering, editing or viewing a delivery secret,
and the secret portion SHALL never be sent to the browser.

#### Scenario: No credential entry exists

- **WHEN** the user configures notifications
- **THEN** no field accepts a delivery credential, and no delivery secret is transmitted to
  the browser

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

