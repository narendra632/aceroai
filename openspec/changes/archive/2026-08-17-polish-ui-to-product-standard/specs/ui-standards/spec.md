## ADDED Requirements

### Requirement: Interactive controls are part of the application's design

The interface SHALL present controls that follow the application's own visual language,
so that the app looks and behaves as one designed product rather than a form assembled
from browser defaults.

#### Scenario: A control needs a set of choices

- **WHEN** the user picks from a fixed set of options
- **THEN** the control is rendered and themed by the application, honoring the active
  light or dark theme — not delegated to the operating system's own widget

#### Scenario: A control needs a date

- **WHEN** the user chooses a date or time
- **THEN** the picker follows the application's theme, and its trigger is legible against
  the surface it sits on in both light and dark mode

#### Scenario: The same interaction appears in two places

- **WHEN** an interaction pattern is used on more than one screen
- **THEN** both screens use the same shared implementation, so the behavior cannot
  diverge between them

### Requirement: Every action is acknowledged

The interface SHALL make the outcome of an action visible, so that success and failure are
never indistinguishable from nothing having happened.

#### Scenario: An action succeeds

- **WHEN** the user completes an action that changes stored data
- **THEN** the interface reflects the change immediately and confirms it

#### Scenario: An action fails

- **WHEN** the request behind an action does not succeed
- **THEN** any optimistically applied change is reverted, and the failure is reported —
  the interface never continues to display state the server did not accept

#### Scenario: Data cannot be loaded

- **WHEN** a screen's data fails to load
- **THEN** the failure is stated and a retry is offered — an error is never rendered as
  an empty result, which would misreport a fault as "you have nothing"

#### Scenario: Data is being loaded

- **WHEN** a screen is waiting on data
- **THEN** the wait is shown, rather than an empty screen that later changes without warning

### Requirement: Destructive actions are reversible

Destroying user data SHALL be recoverable for a short period after the fact, so that an
accidental deletion is a moment of inconvenience rather than permanent loss.

#### Scenario: The user deletes a record

- **WHEN** the user deletes a task, journal entry, or conversation
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

### Requirement: Stored data is visible and editable by its owner

Anything the data model records about the user SHALL be viewable and correctable through
the interface, so that no information exists in the system that its owner cannot see or
change.

#### Scenario: A record is created with a mistake

- **WHEN** the user has created a record and needs to correct it
- **THEN** every field the record stores can be edited — correcting a mistake never
  requires deleting and re-creating

#### Scenario: The assistant writes a field

- **WHEN** the assistant sets a value on the user's data through its tools
- **THEN** that value is visible in the interface and editable there — the assistant
  cannot write data the user has no way to see

### Requirement: The interface is usable by touch and by keyboard

The interface SHALL be operable without a mouse and on a touch screen, so it remains
usable on the phone it is intended to be installed on.

#### Scenario: An action is offered on a touch device

- **WHEN** an action is available on a row or message
- **THEN** it is reachable by touch — it never depends solely on hover — and its target is
  large enough to hit reliably

#### Scenario: The user navigates by keyboard

- **WHEN** the user moves through the interface using the keyboard
- **THEN** focus is always visible, order follows the visual layout, and dialogs and
  pickers trap and restore focus correctly

#### Scenario: Status is conveyed visually

- **WHEN** the interface signals a state such as overdue or error
- **THEN** it is conveyed by more than color alone

### Requirement: The interface does not fight the user

The interface SHALL yield to a user's deliberate action, so that automatic behavior never
overrides an explicit one.

#### Scenario: Content streams while the user is reading

- **WHEN** new content arrives while the user has scrolled away from the latest
- **THEN** the view stays where the user put it, and a way to return to the latest is
  offered

#### Scenario: The user navigates mid-composition

- **WHEN** the user has entered text and moves to another view and back
- **THEN** the text is still there
