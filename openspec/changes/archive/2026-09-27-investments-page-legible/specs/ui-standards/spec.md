# ui-standards — disclosure and emphasis

## ADDED Requirements

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
