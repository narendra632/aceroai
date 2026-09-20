# investments Specification

## Purpose
TBD - created by archiving change add-investment-ledger. Update Purpose after archive.
## Requirements
### Requirement: What is held is recorded by the user and never inferred

The system SHALL treat a recorded transaction as the authoritative statement of what was
bought or sold, in what quantity, at what price, on what date. It SHALL NOT create, infer, or
adjust a transaction on its own initiative, and SHALL NOT derive holdings from any external
account.

This is the load-bearing separation of the whole module. A wrong price is visible and
self-correcting — the next observation replaces it. A wrong transaction is silent: it
propagates into every position, every return and every review, and nothing anywhere reports
it. The system is therefore permitted to be uncertain about what a holding is *worth*, and
never about what is *held*.

Where the user expresses a transaction in their own words, the system MAY interpret it, but
SHALL present the interpretation for confirmation before recording it, and SHALL record only
the confirmed structured result.

#### Scenario: A holding stated in plain language

- **WHEN** the user says they bought a quantity of something at a price on a date
- **THEN** the system shows what it understood — instrument, quantity, price, date — and
  records it only once the user confirms

#### Scenario: Nothing is invented

- **WHEN** the system has no record of a transaction
- **THEN** no holding exists for it, whatever any external source shows, and the system does
  not create one to reconcile a difference

### Requirement: The record of what happened cannot be rewritten

Transactions and observed prices SHALL be append-only. The system SHALL NOT provide any means
to modify or remove a recorded transaction, and the database SHALL reject an attempt at either.

A correction SHALL be expressed as a new entry that reverses or supersedes the earlier one,
carrying a reference to it. Both remain readable, and readers resolve to the entries that have
not been superseded.

This deliberately departs from how the rest of the system treats deletion. Elsewhere a removal
is reversible and hidden; here a sale is an *event* and a mistake is corrected by a
*counter-event*, exactly as a ledger works. The reason is that this record exists to be judged
against later, and a record that can be quietly rewritten cannot judge anyone.

The interface MAY still offer the user a familiar undo gesture. It SHALL be implemented as
recording the reversing entry.

#### Scenario: Correcting a mistaken entry

- **WHEN** the user corrects a transaction they entered wrongly
- **THEN** a reversing entry is recorded referencing the original, both remain in the record,
  and the position reflects only the corrected figures

#### Scenario: The record refuses to be edited

- **WHEN** anything attempts to update or delete a recorded transaction directly
- **THEN** the database rejects it, regardless of which code path attempted it

### Requirement: Every derived figure is computed from the record, never stored

Quantity held, cost basis, current value, allocation, realised and unrealised gain, and every
return measure SHALL be computed from transactions and observed prices at the time they are
read. The system SHALL NOT maintain a stored copy of any of them.

A stored derived value is a value that can disagree with the record it came from, and a
portfolio that disagrees with its own transactions is worse than one that is merely slow. The
guarantee bought here is that there is exactly one answer to "what do I hold", and it is a
function of what was recorded.

#### Scenario: A correction flows through immediately

- **WHEN** a reversing entry changes a past quantity
- **THEN** every figure that depends on it — position, cost basis, allocation, returns —
  reflects the change on the next read, with no rebuild or refresh step

### Requirement: A price is an observation with a source and an age

Prices and exchange rates SHALL be recorded as observations, each carrying when it was
observed and where it came from. A price supplied by the user and a price supplied by an
external feed SHALL be recorded in the same form, differing only in their stated source.

The system SHALL show the age of any price it displays, and SHALL visibly mark a price older
than the limit for that kind of instrument rather than presenting it as current. A stale price
presented as current is the mechanism by which a portfolio quietly reports a value nobody
would defend.

The staleness rule SHALL apply regardless of source. A price the user typed is not exempt from
being old.

#### Scenario: A price that has aged

- **WHEN** the newest observation for a holding is older than the limit for its kind
- **THEN** the value is shown with its age and visibly marked as stale, and is not presented
  as the current price

#### Scenario: Source is recorded, not assumed

- **WHEN** any price is recorded
- **THEN** its source is stored with it, so a later reader can tell a typed price from a
  fetched one

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

### Requirement: Returns on a foreign holding separate the asset from the currency

For any holding not denominated in the base currency, the system SHALL record the exchange
rate **at the moment of each transaction**, and SHALL report the return decomposed into the
asset's own movement, the currency's movement, and the combined result.

The rate at the time of a purchase is a fact about that moment and is not recoverable
afterwards with the same meaning. Without decomposition, a weakening base currency credits the
system with skill it does not have — which is the easiest way for a record like this to
flatter itself.

#### Scenario: A foreign holding that did nothing

- **WHEN** a foreign-currency holding is unchanged in its own currency but the base currency
  has weakened
- **THEN** the reported gain attributes the whole change to currency and none of it to the
  asset

### Requirement: The real cost of transacting is modelled, and the rates that produced it are kept

Every transaction SHALL carry the transaction costs applicable to it — taxes, exchange and
regulator fees, stamp duty, and depository charges — computed from a dated schedule of rates,
and the schedule that was applied SHALL be recorded on the transaction.

A paper portfolio that ignores costs flatters itself by a few tenths of a percent on every
round trip, which compounds into a materially wrong track record. And because these rates
change, recomputing an old transaction at today's rates would silently rewrite the return of a
period that is supposed to be settled. Freezing the schedule is the same discipline already
applied to recorded model costs elsewhere in the system.

#### Scenario: Rates change after a trade

- **WHEN** a charge rate changes and an old transaction is read afterwards
- **THEN** that transaction still reports the charges computed under the schedule in force
  when it happened

### Requirement: Holding periods are tracked per lot, against the rule for that asset

The system SHALL match disposals against acquisitions on a first-in-first-out basis for the
purpose of holding-period and realised-gain reporting, and SHALL also make a weighted-average
view available, with each labelled so a reader knows which they are looking at.

Each asset class SHALL carry its own holding-period rule rather than a shared default. The
boundary is a cliff, not a slope — the same disposal a day either side of it can be taxed at
substantially different rates — so the system SHALL be able to report how far a holding is
from its boundary at the time a disposal is being considered.

The system SHALL surface holding-period consequences and asset-class treatment. It SHALL NOT
compute, estimate, or display a tax liability.

#### Scenario: A disposal close to a boundary

- **WHEN** a disposal is considered for a holding approaching its long-term boundary
- **THEN** the system reports how many days remain, before the disposal is acted on

#### Scenario: An asset whose losses cannot be offset

- **WHEN** a holding belongs to a class whose losses cannot be set against other gains
- **THEN** its losses are reported separately and are not netted against gains elsewhere in
  the portfolio

#### Scenario: Two lots, two answers

- **WHEN** part of a holding acquired in several lots is disposed of
- **THEN** the first-in-first-out realised gain and the weighted-average realised gain are
  both available, each labelled

### Requirement: What is held is what is watched

Recording a holding SHALL be sufficient to bring that instrument into the set the system
tracks. The system SHALL NOT require a separate action to begin following something the user
has told it they own.

A tracked set maintained separately from holdings is a tracked set that will disagree with
them — and the disagreement will be discovered when something material happens to a holding
nobody was watching.

#### Scenario: A newly recorded holding

- **WHEN** the user records a transaction in an instrument the system has not seen before
- **THEN** that instrument becomes part of what the system tracks, with no further action

### Requirement: Books whose purposes differ are kept separate

The system SHALL support more than one book of holdings and SHALL keep them distinct, so that
what the user actually holds and what the system's own decisions would have produced can be
compared rather than conflated.

Neither book is contained by the other. The user will hold things the system never suggested,
and the system will suggest things the user does not act on. The difference between them is
the measurement the module exists to produce, and a single combined book would destroy it.

#### Scenario: A holding the system never proposed

- **WHEN** the user records a holding that originated with no involvement from the system
- **THEN** it belongs to their own book, is tracked and valued like any other holding, and
  does not appear in the book representing the system's decisions

### Requirement: Prices arrive without being typed

The system SHALL obtain prices for held instruments from external sources on a schedule: a
daily close (or NAV) for every holding, and a live price during market hours for holdings
that trade intraday. Fetched prices SHALL be recorded as observations in the same form as a
typed price, differing only in their source.

A daily close SHALL come from a source that does not depend on a broker login, so that the
close of record survives the broker's API being unavailable.

#### Scenario: The evening after a trading day

- **WHEN** the scheduled close run completes on a trading day
- **THEN** every held NSE equity has a close observation for that day, recorded with the
  exchange's file as its source

#### Scenario: The broker API is down

- **WHEN** the live-price source cannot be reached
- **THEN** no error reaches the user; the last price is shown with its age and marked stale
  once past its limit, and the next day's close still arrives from the exchange's file

### Requirement: History fills itself

Every scheduled price run SHALL fill every missing day between a holding's first trade (or the
earliest day its source provides) and today. There SHALL be no separate backfill step that
must be remembered on a new or restored database.

Filling SHALL be idempotent: running it again over days already filled SHALL write nothing.

#### Scenario: A fresh database

- **WHEN** the first price run executes against a book with months of trades and no prices
- **THEN** it records a close for every trading day the sources provide, and the value line
  appears for every day on which every open holding has one

#### Scenario: A repeated run

- **WHEN** a price run executes twice over the same days
- **THEN** the second writes no new observations

#### Scenario: A source's history is shorter than the holding

- **WHEN** a holding was bought before the earliest day its source provides
- **THEN** history is filled from that earliest day, and the value line is absent before it
  rather than estimated

### Requirement: Live prices are fetched only when stale

When the portfolio is viewed — on the page or through the assistant — the system SHALL fetch a
fresh price only for holdings whose newest price is missing or older than the staleness limit
for their kind. Both callers SHALL use the same service function.

#### Scenario: Opening the page after the close

- **WHEN** the page is opened in the evening and each holding already has today's close
- **THEN** no external price request is made

### Requirement: The market-data connection cannot trade

The broker integration SHALL be capable only of logging in and reading prices. It SHALL NOT
contain the addresses of any order, holdings, positions or trigger endpoint, so no defect or
misuse can place or inspect a trade through it.

#### Scenario: The adapter is inspected

- **WHEN** the broker adapter's source is examined by the test suite
- **THEN** it names exactly the login, quote and candle routes and no others

### Requirement: Corporate actions on held stocks are announced before they distort value

The system SHALL watch the exchange's corporate-action feed and notify the user of any split,
bonus or consolidation announced for a held stock, once per action. It SHALL NOT record the
action in the ledger itself.

#### Scenario: A bonus is announced for a held stock

- **WHEN** the feed lists a bonus issue for a company whose stock is held
- **THEN** the user is notified once, naming the stock, the action and its ex-date

#### Scenario: A dividend is announced

- **WHEN** the feed lists only a dividend for a held stock
- **THEN** no notification is raised

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

