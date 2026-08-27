# notifications Specification

## ADDED Requirements

### Requirement: Delivery asks the device to interrupt at the time the notification was raised

Where the delivery mechanism allows the sender to express how time-critical a message is, the
system SHALL always express the most time-critical form available, so that a device
conserving power is woken rather than deferring the message until it is next used.

This applies to every notification the system raises, without exception and without a setting.
Every notification this application sends is one the user scheduled and is waiting for; there
is no promotional or ambient tier for a lower expression to describe. A summary of the user's
day has its entire value in arriving at the end of that day.

This SHALL NOT be understood as overriding the user's own quiet period. Expressing urgency is
a request to the delivery infrastructure about how to reach a device that is asleep; it is not
a decision about whether the user wants to be reached at all. That decision remains the user's
and is made before delivery is attempted.

#### Scenario: A device that is asleep

- **WHEN** a notification is raised while the user's device is idle and conserving power
- **THEN** delivery expresses that the message is time-critical, so the device is woken rather
  than holding it until the user next picks the device up

#### Scenario: Urgency does not defeat quiet hours

- **WHEN** a notification is raised during the user's quiet period
- **THEN** it is recorded and not delivered, exactly as it would have been before urgency was
  expressed at all

### Requirement: A delivery expires when its content expires

Where the delivery mechanism allows the sender to say how long an undelivered message should
be held for an unreachable device, that period SHALL be derived from the same declaration that
governs how late the work producing it may run.

A single declaration of staleness SHALL serve both purposes. The system SHALL NOT maintain a
separate statement of delivery lifetime that can drift from it — it did, and the two
contradicted each other: work that the system refused to *run* three hours late was handed to
the delivery infrastructure with instructions to hold it for twenty-four.

Work that declares no staleness bound SHALL likewise place no bound on delivery. A
notification raised outside any scheduled work SHALL use a single stated default.

#### Scenario: A device offline longer than the content is useful

- **WHEN** a notification is raised for a device that stays unreachable for longer than the
  producing work was permitted to be late
- **THEN** it is not delivered afterwards, and it remains readable in the application

#### Scenario: One declaration, both decisions

- **WHEN** the staleness bound of a piece of scheduled work is changed
- **THEN** both how late it may run and how long its delivery is held change with it, with no
  second value to update

## MODIFIED Requirements

### Requirement: A notification is stored before it is delivered

Every notification the system raises SHALL be persisted as a durable record before any attempt
is made to deliver it to a device.

The record SHALL survive a delivery that fails, a device that is unreachable, a permission the
user has refused, and a notification the user dismissed without reading.

A record MAY be delivered more than once, where the system is deliberately reminding the user
of a situation that persists. When it is, the record SHALL retain how many times it has been
delivered and when it was delivered most recently.

A repeat delivery MAY update the record's wording to describe the situation as it reads at
that moment. This is not a rewriting of what was said: the record's subject is fixed by its
tag, and the wording describes that subject rather than transcribing an utterance. The
record's identity and the time it was first raised SHALL NOT change.

Where the system paces how often it repeats, that pacing SHALL be measured from the last
**delivery**, not from when the record was written. A record that has never reached a device
has interrupted nobody, so nothing is being paced.

A count of how often the user has been interrupted SHALL count deliveries, not records. A
record delivered six times has interrupted the user six times, and any limit measured against
that count SHALL measure it that way.

#### Scenario: Delivery fails, the record remains

- **WHEN** the system raises a notification and delivery to the device fails
- **THEN** the notification is still present in the application for the user to read

#### Scenario: Permission was never granted

- **WHEN** the user has not permitted device notifications
- **THEN** notifications are still recorded and readable inside the application

#### Scenario: Dismissed on the device

- **WHEN** the user dismisses a delivered notification without opening it
- **THEN** the notification remains unread inside the application

#### Scenario: One record delivered repeatedly

- **WHEN** the system reminds the user of a persisting situation several times against one
  record
- **THEN** the record reports how many times it was delivered and when it was delivered last,
  and the count of interruptions reflects every delivery

### Requirement: The user controls when and how often they are interrupted

The system SHALL support a period during which notifications are recorded but not delivered to
devices.

Repeated notifications about the same subject SHALL replace one another on the device rather
than accumulating.

Notification volume SHALL be governed by the nature of each subject, and SHALL NOT be governed
by a ceiling on the number delivered in a day. A ceiling SHALL remain available to be set
deliberately, and SHALL be absent by default.

For most subjects, governing by nature means suppressing repetition of a situation already
reported — a measurement that has not left the band it was reported in is not news. For a
subject that requires the user to act, it means repeating until they do. **Which of the two
applies SHALL be a deliberate property of the subject.** Neither is a safe default: applied
everywhere, the first produces a system that mentions a problem once and then abandons it,
and the second produces one that cannot stop talking.

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
now applies only if the user asks for it. What this change adds is that the deliveries counted
against it include repeat deliveries of one record, so six reminders count as six.

#### Scenario: Repeated subject

- **WHEN** a second notification concerns the same subject as one already showing
- **THEN** it replaces the existing one rather than appearing alongside it

#### Scenario: A subject that requires action

- **WHEN** a subject is one the user must act on, and they have not yet acted
- **THEN** it is raised again at the pace chosen for it, rather than suppressed as already
  reported

#### Scenario: A record held back has nothing to pace

- **WHEN** a repeat is due for a record that has never reached a device
- **THEN** it is delivered, rather than treated as though the user had already been
  interrupted
