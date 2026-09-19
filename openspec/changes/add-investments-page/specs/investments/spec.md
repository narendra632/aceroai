# investments Specification

## ADDED Requirements

### Requirement: The book is visible without having to ask for it

The system SHALL present the portfolio as a screen the user can look at — what is held, what
each holding cost, what it is worth, how it is allocated, and how it has changed — without
the user having to compose a question.

Reviewing a portfolio is an act of scanning, not of querying. A conversational interface can
only answer what it is asked, so it can never surface the thing the user did not know to ask
about: the lot that crosses long-term next month, the holding that has quietly become a third
of the book, the price nobody has updated in a fortnight. The record is only as useful as the
noticing it enables.

Everything shown SHALL be computed by the same functions that answer the same questions in
conversation. Where the two disagree, the interface is wrong by definition.

#### Scenario: The user opens the portfolio

- **WHEN** the user opens the investments screen
- **THEN** current holdings, their cost and value, the allocation between them, and the
  totals are shown without further interaction

#### Scenario: The screen and the assistant are asked the same thing

- **WHEN** a figure appears both on the screen and in an answer from the assistant
- **THEN** they are the same figure, because both are produced by the same computation

### Requirement: A monetary figure is exact from computation to display

Every monetary figure the interface displays — including percentages and rates of return —
SHALL be computed in exact decimal arithmetic and SHALL cross any boundary between processes
in a form that cannot lose precision.

Binary floating point cannot represent most decimal money values, and a portfolio is nothing
but sums of money. A figure that is proven correct by a test and then re-derived in a
different numeric type on the way to a screen is no longer the figure that was proven.

Interface code MAY convert a figure to an approximate numeric type for drawing — positions on
a chart — and SHALL NOT do so for any value that is displayed, compared, or aggregated.

#### Scenario: A value is shown to the user

- **WHEN** any amount of money or percentage is rendered
- **THEN** the value rendered is the value computed, unrounded by any intermediate conversion

#### Scenario: Two figures need to be combined

- **WHEN** a displayed figure is the sum, difference or ratio of others
- **THEN** it is computed where exact arithmetic is available, not assembled by the interface

### Requirement: What a figure leaves out is stated beside it

Where a total, an allocation or a chart cannot include everything it purports to cover, the
system SHALL name what was excluded, in the same place and at the same prominence as the
figure itself.

An incomplete figure presented as complete is worse than no figure, because it is acted on
with unwarranted confidence. Placing the caveat in a footnote, a tooltip, or below the fold is
the same failure with an alibi.

#### Scenario: A holding cannot be valued

- **WHEN** a holding has no usable price
- **THEN** it appears in the interface with no value rather than a zero or a stale figure
  presented as current, and any total that omits it says that it does

#### Scenario: An allocation omits part of the book

- **WHEN** allocation is shown and some holdings cannot be valued
- **THEN** the excluded holdings are listed with the figure, not summarised as a count in a
  secondary surface

#### Scenario: A price shown is older than its limit

- **WHEN** a displayed price is past the staleness limit for its asset
- **THEN** its age is shown wherever the price or anything derived from it appears

### Requirement: Correction is offered where the record is shown

Wherever a recorded transaction is displayed, the system SHALL offer the user a way to correct
it, and SHALL implement that correction as a superseding entry rather than a modification.

The interface SHALL describe the action as what it is. It SHALL NOT present the correction as
a deletion or an undo, because on this record nothing is deleted and nothing is undone — and
the one record in the system whose worth depends on being unrewritable is the last place to
tell the user otherwise.

Superseded entries SHALL remain visible in the history, marked as superseded and identifying
what replaced them.

#### Scenario: The user corrects an entry they got wrong

- **WHEN** the user corrects a transaction from the interface
- **THEN** a superseding entry is recorded, the position reflects the correction immediately,
  and the interface states that the original remains in the record

#### Scenario: Reading the history after a correction

- **WHEN** the user views the transaction history
- **THEN** both the superseded entry and the entry that superseded it are visible, and which
  is which is unambiguous

### Requirement: A movement too large to be a price movement is flagged

Where two observations of the same instrument close together in time differ by more than a
quarter, the system SHALL flag the holding as possibly affected by a corporate action that
has not been recorded.

Until corporate actions are ingested automatically, an unrecorded split or bonus appears as a
catastrophic loss in a position that has not lost anything — the one failure mode of this
module that produces a large, alarming, entirely fictional number.

The comparison SHALL be restricted to observations close enough together for a single-session
movement to be the explanation. Observations far apart differ for ordinary reasons, and a
warning that fires on ordinary movement is a warning that will be ignored when it matters.

#### Scenario: A price halves overnight

- **WHEN** consecutive observations of an instrument a few days or less apart differ by more
  than 25%
- **THEN** the holding is flagged with the size and date of the movement and the suggestion
  that a split or bonus may need recording

#### Scenario: Prices recorded a month apart

- **WHEN** two observations are far enough apart that ordinary movement explains the
  difference
- **THEN** no flag is raised, whatever the size of the difference

### Requirement: Value over time is drawn only where it was observed

Where the system charts the value of the book over time, it SHALL plot a point only for
periods in which every open holding has an observed price, and SHALL state the range actually
covered.

It SHALL NOT interpolate between observations, and SHALL NOT compute a total from partial
coverage. A line assembled from whichever prices happened to exist steps whenever coverage
changes, and a reader cannot distinguish that step from a real movement in the portfolio.

Invested capital SHALL be plotted independently, since it is derived from transactions alone
and is therefore exact for every period from the first transaction onward.

#### Scenario: Prices exist for only part of the period

- **WHEN** value over time is charted and some periods lack a price for a held instrument
- **THEN** those periods carry no value point, the covered range is stated, and the invested
  line is unaffected

#### Scenario: No prices have been recorded at all

- **WHEN** no price observation exists
- **THEN** the invested line is shown alone and the interface states that value history begins
  when prices are recorded, rather than charting zero or an empty frame

## MODIFIED Requirements

### Requirement: Both money-weighted and time-weighted return are reported together

The system SHALL compute return both as a money-weighted rate over actual cash flows and as a
time-weighted rate chained across them, and SHALL present them together wherever return is
shown.

They answer different questions and are routinely confused. The money-weighted figure is
affected by *when* money went in, so it measures the investor's timing. The time-weighted
figure removes that, so it measures the strategy independent of cash-flow luck. Presenting
either alone invites crediting the wrong thing — and the gap between them is itself
informative.

Both SHALL be computed from the recorded cash flows, and the money-weighted calculation SHALL
produce a correct result for flows clustered near the end of the period, which is where naive
implementations fail.

Where one measure cannot be computed from the data on hand, the system SHALL show the measure
it has, labelled with what that measure means, and SHALL name the missing measure and the
reason it is missing alongside it. It SHALL NOT present a single available figure as "the
return".

This is not a relaxation. The requirement exists so that a number is never credited to the
wrong cause, and an unlabelled lone figure is exactly that failure; a labelled figure beside a
stated absence is not. The case is real rather than hypothetical: a time-weighted rate needs
valuations at sub-period boundaries, so a book whose prices have never been observed can
produce a money-weighted return and cannot produce a time-weighted one.

#### Scenario: Return is never a single number

- **WHEN** return is displayed for a portfolio or a holding
- **THEN** both measures appear together, each labelled with what it measures

#### Scenario: One measure cannot be computed

- **WHEN** the data supports one measure of return and not the other
- **THEN** the available measure is shown labelled with what it measures, and the unavailable
  one is named together with what would be needed to produce it
