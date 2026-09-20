# investments — closing Phase 1

## ADDED Requirements

### Requirement: An announced change to a share count is recorded before it is applied

The system SHALL record every announced corporate action that changes the number of units of
a held instrument, as a durable row, at the moment it is first read from the exchange feed.
The row SHALL survive re-reading the same announcement on later days without duplicating.

The system SHALL derive the size of the change only from an announcement whose wording admits
a single reading. Where the wording is ambiguous, the system SHALL record the action as
needing review, SHALL store the reason, and SHALL NOT infer a size.

⚠ A confidently wrong multiplier is a larger error than the one it corrects: reading a share
split in the wrong direction changes a holding by a factor of a hundred, where leaving it
unapplied changes the *presentation* of that holding by a factor of two.

#### Scenario: The same announcement is read on several evenings

- **WHEN** the feed carries an announcement already recorded
- **THEN** no second row is created, and nothing is announced again

#### Scenario: An announcement that could mean two things

- **WHEN** an announcement states a ratio without saying which side it applies to
- **THEN** the action is recorded as needing review with the reason stored, the holding is
  flagged, and no quantity is changed

#### Scenario: The feed cannot be reached

- **WHEN** the exchange feed is unavailable
- **THEN** actions already recorded are still applied on their date, and the failure is
  recorded rather than raised

### Requirement: Applying an action conserves what was paid, per lot

When an action is applied, the system SHALL change only the number of units held. The total
cost basis of the holding SHALL be unchanged, and each acquisition lot SHALL retain its own
per-unit cost scaled by the same factor as its quantity.

The change SHALL be recorded on the date the action took effect, not the date it was read,
and SHALL be an ordinary entry in the append-only ledger that the existing correction path
can retire.

#### Scenario: A bonus on a holding bought in two lots at different prices

- **WHEN** a 1:1 bonus is applied to lots acquired at two different prices
- **THEN** the quantity doubles, the total cost basis is unchanged, and each lot's per-unit
  cost is exactly half of what it was — not the average of the two

#### Scenario: The action did not apply to this book

- **WHEN** an action falls due for an instrument the book holds none of
- **THEN** it is closed with that reason, and the holding is not left flagged

### Requirement: An outstanding action makes the holding's profit and loss unreliable, and it says so

While an action on an instrument is outstanding, the system SHALL state that the profit and
loss for that holding is not reliable, wherever that figure is presented.

⚠ This is why the action is a stored row rather than a message. A message can be dismissed
while the number it was warning about stays on the screen.

#### Scenario: A split is announced and not yet applied

- **WHEN** an action on a holding is outstanding
- **THEN** the holding is flagged in the interface, and what the change would do to its
  quantity is shown before it is applied

### Requirement: Foreign holdings can be read as the calendar-year disclosure requires

For each instrument held in a currency other than the book's own, the system SHALL report,
for a chosen calendar year: the acquisition date, what was paid, the highest value reached on
any day of that year with the day it occurred, the value at the end of the period with its
day, income received and disposal proceeds.

The system SHALL report how many days of the period could be valued, and SHALL NOT present a
peak taken over a subset of days as a peak over the period.

The system SHALL state that the conversion rate used is the one recorded with each
observation and not the rate the tax return requires, and SHALL name the day each figure
comes from so the required rate can be obtained for it.

#### Scenario: A year priced only in part

- **WHEN** fewer days of the period carry a price than the period contains
- **THEN** the report states the two counts, and the interface says the peak is the highest
  of the observed days

#### Scenario: A year in which nothing was bought or sold

- **WHEN** a foreign holding was held through a year with no transaction in it
- **THEN** that year is still offered and still reported, because the holding is declarable
  in every year it is held

### Requirement: The module reports what it is costing in storage

The system SHALL measure the disk occupied by the investment record, including indexes, and
SHALL report when it approaches its budget.

#### Scenario: The record grows past its warning threshold

- **WHEN** the module's tables exceed the warning threshold
- **THEN** the user is told once per band, repeated daily while unresolved

#### Scenario: The measurement cannot be taken

- **WHEN** a table cannot be measured
- **THEN** nothing is reported, because an unmeasurable table is not an empty one
