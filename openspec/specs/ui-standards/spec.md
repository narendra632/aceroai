# ui-standards Specification

## Purpose
The rules every screen obeys: how controls behave, how state is shown, and
what the interface owes a person using it on a phone at arm's length.
## Requirements
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

### Requirement: Stored data is visible and editable by its owner

Anything the data model records about the user SHALL be viewable and correctable through
the interface, so that no information exists in the system that its owner cannot see or
change.

Where a record is deliberately append-only, correction SHALL still be offered from the
interface, expressed as a superseding entry rather than a modification. Both the original and
the entry that supersedes it SHALL remain visible, and the interface SHALL describe the action
truthfully rather than borrowing the wording of an edit or a deletion.

This is an exception to *how* a correction is made, never to *whether* one is available. A
record the user cannot correct is the defect this requirement exists to prevent; a record that
keeps its own history of corrections is not that. The exception has to be earned by the
record's purpose — the investments ledger exists to be judged against months later, and a row
that can be quietly rewritten cannot judge anyone.

#### Scenario: A record is created with a mistake

- **WHEN** the user has created a record and needs to correct it
- **THEN** every field the record stores can be edited — correcting a mistake never
  requires deleting and re-creating

#### Scenario: A mistake in an append-only record

- **WHEN** the user needs to correct a record the system does not permit editing
- **THEN** the interface offers the correction, records it as a superseding entry, keeps both
  entries visible, and says that the original remains in the record

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

### Requirement: A collapsed region says what it holds

Any region of the interface that can be collapsed SHALL show, while collapsed, the headline of
what it contains — a count, a figure or a state — so that closing it hides the detail and not
the fact. The control SHALL expose whether it is open to assistive technology, and the whole
header SHALL be the control.

Content that is the reason a screen or tab exists SHALL be visible when that screen or tab is
opened. Collapsing it by default makes the reader choose twice to see anything.

#### Scenario: A section is closed

- **WHEN** a section is collapsed
- **THEN** its header still shows its headline, and a screen reader announces it as collapsed

#### Scenario: A tab is opened

- **WHEN** the user opens a tab
- **THEN** the content that tab exists to show is visible without a further click

#### Scenario: The user closes a section and returns

- **WHEN** the user collapses or expands a section and comes back later
- **THEN** it is as they left it, on that device

### Requirement: Visual weight follows importance

The interface SHALL give more visual weight to what needs the user than to what is reference,
using a single shared set of status tones. Every tone SHALL be paired with an icon or a word,
never colour alone, and each tone SHALL have a step chosen for the dark theme rather than an
automatic inversion.

A score out of a maximum SHALL be drawn as a proportion as well as written as numbers, and the
drawing SHALL carry its value for assistive technology.

#### Scenario: Something needs the user

- **WHEN** an item is waiting on the user
- **THEN** it is set apart from reference material by tone, icon and position, not by colour
  alone

#### Scenario: A score is shown

- **WHEN** a component scores 7 of 9
- **THEN** it appears as a bar seven-ninths full with "7/9" beside it, and the bar reports its
  value to a screen reader

