# learnings Specification

## Purpose
TBD - created by archiving change add-learnings-section. Update Purpose after archive.
## Requirements
### Requirement: The system explains itself inside the product

The application SHALL provide a section that explains how it works, reachable from the main
navigation like any other part of the product.

It SHALL cover, at minimum: the path a message takes from being sent to being answered; how
cost and activity are recorded; **how the system acts on its own — what runs on a schedule,
what decides whether to tell the user something, and how it reaches them when the application
is closed**; and the general concepts the implementation rests on.

#### Scenario: Reaching the explanation

- **WHEN** the user opens the application
- **THEN** the section explaining the system is reachable from the main navigation

#### Scenario: The message path is explained

- **WHEN** the user opens the section
- **THEN** it presents the stages a message passes through, in the order they happen

#### Scenario: Acting without being asked is explained

- **WHEN** the user opens the section
- **THEN** it presents how scheduled work runs and how a notification reaches the user's
  device, in the order those stages happen

### Requirement: Explanations are entered by choosing, not by reading

Explanation SHALL be structured so the reader chooses what to go deeper into, rather than
being presented with continuous prose. Each part of a diagram SHALL be selectable, and
selecting it SHALL reveal an explanation of that part alone.

Selection MUST work by activation rather than by pointing, so the section is fully usable
on a touch screen and by keyboard.

#### Scenario: Opening one stage

- **WHEN** the user selects a stage of a diagram
- **THEN** an explanation of that stage alone is shown

#### Scenario: Touch and keyboard

- **WHEN** the user has no pointing device, or is using a keyboard
- **THEN** every stage can still be selected and its explanation read

#### Scenario: Nothing selected

- **WHEN** the user has not selected anything
- **THEN** the diagram is legible on its own, and no explanation panel occupies the screen

### Requirement: Explanations are short by construction

Each explanation SHALL be bounded in length: a single summary sentence, a small number of
supporting points, and at most one measured figure. An explanation that outgrows the bound
belongs in the project's reference documentation, and the panel SHALL link there instead of
expanding.

#### Scenario: A long explanation is not accepted

- **WHEN** an explanation exceeds the stated bound
- **THEN** it is rejected before it can ship

#### Scenario: Deeper detail is reachable

- **WHEN** an explanation has more detail available elsewhere
- **THEN** the panel offers a way to reach it rather than including it

### Requirement: Quantities shown are the system's current values

Any limit, threshold or window the section quotes SHALL be read from the running system's
configuration rather than written into the explanation.

A quoted quantity that can drift from the value actually in force is worse than no quantity,
because it teaches something false with the authority of a number.

#### Scenario: A limit changes

- **WHEN** a configured limit is changed
- **THEN** the explanation shows the new value without its text being edited

#### Scenario: Values cannot be reached

- **WHEN** the current values cannot be retrieved
- **THEN** the explanations are still shown, without fabricated numbers in place of real ones

#### Scenario: Only tuning values are exposed

- **WHEN** the system publishes its current values
- **THEN** only limits, thresholds and windows are included, and no credential, key,
  endpoint or other secret is exposed

### Requirement: Explanations cannot reference things that do not exist

Every reference an explanation makes to a part of the system — a file, a configured value,
or another explanation — SHALL be verified to exist. A reference that no longer resolves
SHALL fail the build rather than being shown to the reader.

This is what keeps the section true as the system changes: prose can only be kept honest by
whoever edits it, but a reference can be checked.

#### Scenario: A referenced file is renamed

- **WHEN** an explanation points at a file that no longer exists
- **THEN** the build fails

#### Scenario: A referenced value is removed

- **WHEN** an explanation quotes a configured value the system no longer publishes
- **THEN** the build fails

### Requirement: Planned work is never presented as built

The section SHALL distinguish what exists from what is intended. Anything not yet built
SHALL be marked as planned and presented separately from the explanations of working
behaviour.

The same obligation SHALL apply in the opposite direction. An explanation SHALL NOT continue
to describe an implementation the system has superseded, and SHALL NOT describe as absent or
future anything the system has since gained.

This direction is the one that fails silently. A planned feature described as built is
contradicted the moment someone looks for it; a *replaced* implementation still taught as
current looks entirely plausible, and stays wrong until somebody reads the code.

#### Scenario: Something is planned but not built

- **WHEN** the section describes work that has not been done
- **THEN** it is marked as planned and shown apart from what is built

#### Scenario: An implementation has been replaced

- **WHEN** a change replaces how something described in the section works
- **THEN** the explanation is updated to describe the replacement, and the superseded
  mechanism is not left standing as the current one

#### Scenario: Something described as future has since been built

- **WHEN** the section states that some capability is not yet present, and it has since been
  built
- **THEN** that statement is removed or corrected, rather than left to contradict another part
  of the same section

### Requirement: The section is usable on a phone

The section SHALL be usable at the narrowest supported width, including its diagrams and
explanation panels. A diagram that cannot be read on a phone SHALL adapt its layout rather
than shrink.

#### Scenario: A narrow screen

- **WHEN** the section is opened at the narrowest supported width
- **THEN** the diagrams remain legible, every stage remains selectable, and the page does
  not scroll sideways

