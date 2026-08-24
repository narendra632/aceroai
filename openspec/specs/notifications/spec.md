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

#### Scenario: Seeing that something happened

- **WHEN** the system has raised notifications the user has not read
- **THEN** the application shows that unread notifications exist and how many

#### Scenario: Following a notification to its subject

- **WHEN** the user selects a notification
- **THEN** the application takes them to what the notification is about

#### Scenario: Clearing the unread state

- **WHEN** the user marks notifications as read
- **THEN** the unread indication updates accordingly

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
devices, and SHALL limit how many notifications may be delivered to a device in one day.

Suppressed and limited notifications SHALL still be recorded and SHALL remain visible in the
application.

Repeated notifications about the same subject SHALL replace one another on the device rather
than accumulating.

#### Scenario: Quiet hours

- **WHEN** the system raises a notification during the user's quiet period
- **THEN** it is not delivered to the device, and it is waiting in the application afterwards

#### Scenario: A daily ceiling

- **WHEN** the number of notifications delivered in a day reaches the limit
- **THEN** further notifications are recorded but not delivered

#### Scenario: Repeated subject

- **WHEN** a second notification concerns the same subject as one already showing
- **THEN** it replaces the existing one rather than appearing alongside it

### Requirement: Generated summaries are kept and readable by date

Summaries the system composes about the user's day or period SHALL be stored, associated with
the period they describe, and readable in the application afterwards.

They SHALL be presented distinctly from content the user wrote themselves.

#### Scenario: Reading a past summary

- **WHEN** the user looks for a summary the system generated on an earlier date
- **THEN** it is available and identified with the period it covers

#### Scenario: Not confused with the user's own writing

- **WHEN** generated summaries and the user's own entries are shown in the same area
- **THEN** it is clear which is which

### Requirement: Credentials for delivery never enter the interface

Keys used to authorize notification delivery SHALL come from server configuration only.

The application SHALL NOT provide any means of entering, editing or viewing a delivery secret,
and the secret portion SHALL never be sent to the browser.

#### Scenario: No credential entry exists

- **WHEN** the user configures notifications
- **THEN** no field accepts a delivery credential, and no delivery secret is transmitted to
  the browser

