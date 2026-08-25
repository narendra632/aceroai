# ui-standards Specification

## MODIFIED Requirements

### Requirement: Destructive actions are reversible

Destroying user data SHALL be recoverable for a short period after the fact, so that an
accidental deletion is a moment of inconvenience rather than permanent loss.

This SHALL apply to every user-facing record the application allows to be removed, including
records the system itself produced. Content the user did not write is not thereby less
valuable to them, and a record that can be destroyed but not recovered is an exception that
has to be justified rather than a default.

#### Scenario: The user deletes a record

- **WHEN** the user deletes a task, journal entry, conversation, notification, or generated
  summary
- **THEN** the deletion takes effect immediately and an undo action is offered for a short
  window

#### Scenario: The user undoes a deletion

- **WHEN** the user takes the undo action within that window
- **THEN** the record is restored complete, with the same identity it had before — so
  anything that referenced it still refers to the same thing

#### Scenario: The undo window passes

- **WHEN** the window expires without the user acting
- **THEN** the record stays deleted and is invisible to every reader, including the
  assistant

#### Scenario: Several records are removed in one action

- **WHEN** the user removes several records with a single action
- **THEN** one undo restores exactly the set that was removed, and nothing that was already
  deleted beforehand

## ADDED Requirements

### Requirement: Persistent chrome earns the space it occupies

Layout that persists across every screen SHALL carry content proportionate to the space it
takes. A region reserved across the whole application to hold a single control is a defect,
not a neutral choice, because it is subtracted from every screen at once.

Where the application shows the name of the current screen, it SHALL do so in one place.
The same screen SHALL NOT be titled twice.

#### Scenario: A persistent region holds one control

- **WHEN** a region that appears on every screen contains a single small control and is
  otherwise empty
- **THEN** that region carries the screen's identifying content as well, rather than existing
  solely to position the control

#### Scenario: A screen is titled once

- **WHEN** a screen is displayed
- **THEN** its title appears once, in the application's own header region, and the screen's
  content does not repeat it

#### Scenario: A screen's own controls stay with what they govern

- **WHEN** a screen offers a control that changes what its content shows
- **THEN** that control is placed with the content it governs, not in the application header
  which is shared with every other screen
