# investments — a page someone learning can read

## ADDED Requirements

### Requirement: The page states what is waiting on the user

The system SHALL expose, in one request, every item on the Investments page that is waiting
for a decision from the user, each with the part of the page it belongs to and a severity.
The page SHALL mark each part of the page that has such an item, with a count, and SHALL list
the items in words, each with a way to go to it. When nothing is waiting, nothing SHALL be
shown.

Severity SHALL order the items: a condition that disproved a thesis and an unapplied change to
a share count come before a suggestion, a company awaiting agreement or a source awaiting
approval, which come before a lead in the research queue.

⚠ A count that is always lit is a count nobody reads. Leads are counted, but at the lowest
severity, so their presence does not look like an emergency.

#### Scenario: A company is waiting for agreement

- **WHEN** a followed company's placement in the framework has not been agreed
- **THEN** the page's companies section carries a count, and the waiting list names the
  company with a control that opens it

#### Scenario: Nothing is waiting

- **WHEN** no item needs the user
- **THEN** no count and no list are shown, rather than an empty list

#### Scenario: The count changes

- **WHEN** the user acts on an item from anywhere on the page
- **THEN** the counts and the list reflect it without reloading the page

### Requirement: A followed company with no place in the framework can be placed from the page

Where a followed company has no mapping, the page SHALL offer two ways to give it one: the
user chooses a bottleneck (or places it outside the framework), or the system proposes one
from what sources said about it, choosing only from the framework's own bottlenecks.

Either way the mapping SHALL be recorded **unapproved**, and SHALL score nothing until the user
agrees with it. A proposal the system cannot make with enough confidence SHALL leave the
company unmapped and say why. A model call made to propose a placement SHALL be recorded and
budgeted like every other model call in the module.

#### Scenario: The user places it by hand

- **WHEN** the user chooses a bottleneck for an unmapped company
- **THEN** an unapproved mapping to that bottleneck is recorded, proposed by the user, and the
  company appears among those waiting for agreement

#### Scenario: The system is asked to suggest a place

- **WHEN** the user asks for a suggestion and the model names a framework bottleneck with
  enough confidence
- **THEN** an unapproved mapping is recorded, proposed by the agent, with the model's reason

#### Scenario: The system cannot place it

- **WHEN** the model names nothing, names something outside the framework, or is unsure
- **THEN** no mapping is recorded and the reason is returned

#### Scenario: The company already has a place

- **WHEN** placement is requested for a company that already has a live mapping
- **THEN** the request is refused, and the existing mapping is corrected through moving it
  instead

### Requirement: The margin of safety and a measure's required sample are reported as values

The system SHALL report the margin of safety as a number alongside its sentence, and SHALL
report for each measure the sample size it waits for, where it waits for one. The page SHALL
NOT derive either by parsing text.

#### Scenario: A company is priced below its worth

- **WHEN** the margin of safety is computed
- **THEN** its value is returned as a fraction, positive below worth and negative above

#### Scenario: A measure is waiting for its sample

- **WHEN** a measure has fewer observations than it needs
- **THEN** the number it needs is returned, so progress towards it can be drawn

### Requirement: Reversing a transaction is confirmed before it is written

Because a reversal is itself a permanent entry in an append-only ledger, the page SHALL ask
for confirmation, naming the entry being reversed, before recording it.

#### Scenario: The user presses Reverse

- **WHEN** the user presses Reverse on a transaction
- **THEN** nothing is written until they confirm, and cancelling leaves the ledger untouched
