# investments Specification

## Purpose

Keep an auditable record of what was held, what it cost, what it was worth, and — the
part every other tool throws away — **why each decision was made**, frozen before the
outcome is known so it can be graded later.

The module is built in layers, and which layer a thing lives in decides how far it can be
trusted: the ledger is the user's word, the market record is observation, the fold is
arithmetic, the framework is the user's own theory, judgement is the one place a model
belongs, the gates are code that can overrule it, and the record of judgement is
append-only so that the grading on top of it measures something real.
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

### Requirement: The investment framework is stored data, not logic in the code

The system SHALL hold the framework — the imperatives, the bottlenecks, what each bottleneck
blocks, and the fair multiple for each sector — as versioned records. A change to any of it
SHALL create a new version rather than altering the existing one, and every score and every
proposal SHALL record the version that produced it.

⚠ This is what makes improving the framework safe. A score made in one month must remain
explainable in another, which is impossible if the rules it used were re-derived each time
from whatever the code says today.

#### Scenario: The framework is changed

- **WHEN** the framework's contents are edited
- **THEN** a new version is created, the previous one remains readable, and anything already
  scored still points at the version that produced it

#### Scenario: The framework has not been installed

- **WHEN** something asks for a score and no approved framework exists
- **THEN** the request is refused with that reason, and no score is estimated

### Requirement: A claim that a company serves a national bottleneck scores nothing until a person agrees

The system MAY propose that a company clears a particular bottleneck, and SHALL record the
reasoning for that proposal. The proposal SHALL contribute **zero** to any structural score
until a human approves it.

Replacing a company's mapping SHALL create a new proposal that supersedes the old one and is
itself unapproved.

⚠ Without this, a system that reads enough news will eventually narrate an unrelated company
into national importance, and nothing in the score can tell that apart from the real thing.
A re-mapping does not inherit the agreement given to the mapping it replaced, because it is a
different claim.

#### Scenario: The system proposes a mapping

- **WHEN** a company is proposed as clearing a bottleneck
- **THEN** its structural score is zero, the interface says the mapping is awaiting agreement,
  and approving it is what allows the company to score

#### Scenario: A company is moved to a different bottleneck

- **WHEN** an approved mapping is replaced
- **THEN** the replacement is unapproved, the company scores zero until it is confirmed, and
  the superseded mapping can no longer be approved

### Requirement: A framework judgement expires rather than standing for ever

An approved mapping SHALL carry a date after which it is raised for re-confirmation.

⚠ A mapping states what a company does *today*. A business that changes what it does — a
contract manufacturer moving into semiconductor packaging — would otherwise continue to be
scored against the business it used to be, with nothing anywhere reporting it.

#### Scenario: A mapping passes its review date

- **WHEN** an approved mapping is older than its review period
- **THEN** it appears in the list of things needing a person, asking whether the company still
  does what it did when the mapping was agreed

### Requirement: A gap in the framework is reported as a gap, never scored as a finding

Where the framework does not establish how many imperatives a bottleneck blocks, the system
SHALL record what is known as a **floor** and SHALL mark it as such. It SHALL NOT substitute a
default value that would be indistinguishable from an established one.

Where a company's sector has no fair multiple, the system SHALL say so wherever a figure
derived from that multiple is shown, rather than silently applying a default.

⚠ Both are the same failure: a value that is missing, replaced by one that looks measured. A
company would score narrow because a section of the source material is brief, or appear to
have a computed margin of safety that was in fact guessed — and nothing would prompt anyone to
correct either.

#### Scenario: A bottleneck whose breadth was never established

- **WHEN** a company is scored against such a bottleneck
- **THEN** the score uses the known floor, and the interface states that the figure is a
  floor and may be understated

#### Scenario: A company in a sector with no fair multiple

- **WHEN** that company is valued
- **THEN** the default multiple is used and the interface says it was the default, so any
  margin of safety derived from it is visibly a guess

### Requirement: A company outside the framework is distinguished from one that scores badly

Where the framework does not apply to a company, the system SHALL report the structural score
as **unavailable with a reason**, and SHALL NOT report it as zero.

⚠ These are different answers. Zero means "measured against this framework and found
wanting". Unavailable means "this framework does not ask a question about this company" — the
honest verdict on a foreign holding, since the framework asks what India must build.

#### Scenario: A foreign holding

- **WHEN** a company in another country's market is scored
- **THEN** no structural score is produced, the reason is stated, and the holding is still
  tracked, valued and reported

#### Scenario: A holding the user has declared off-thesis

- **WHEN** the user marks a company as outside the framework
- **THEN** it is scored the same way as a foreign holding, and limits on off-framework
  exposure govern what may be added rather than retrospectively blocking what is held

### Requirement: Companies that are watched but not held are scored

The system SHALL score any tracked company against the framework, whether or not it is held,
and SHALL distinguish the two in the interface.

⚠ Without this the system can only ever say "hold" or "sell". Identifying what deserves
attention is the framework's purpose, and it has nothing to identify if it can only see what
has already been bought.

#### Scenario: A watchlist company

- **WHEN** a company with no transactions is tracked
- **THEN** it is scored, shown as watched rather than held, and never appears as a holding or
  affects any return

### Requirement: Company figures come from filings, stored with the text they were filed as

The system SHALL obtain a company's reported figures from its own regulatory filings, and
SHALL store, alongside each figure, the literal text it was extracted from.

The system SHALL NOT store the filing document itself.

⚠ The text is what makes the rule that a model never produces a number enforceable: a figure in
a thesis can be checked back, character by character, against what the company submitted. A
validator given only the parsed number would be comparing a number with itself.

#### Scenario: A figure is used in an argument

- **WHEN** any figure about a company is presented
- **THEN** it can be traced to the filing it came from and to the words in that filing

#### Scenario: A company restates a year

- **WHEN** the same period is reported again in a later filing
- **THEN** the later statement is the one readers receive, and the earlier one remains recorded

### Requirement: A figure that describes one period is never read as another

The system SHALL resolve each reported figure to the period it describes, using that period's
dates, and SHALL NOT rely on labels or on ordering within the document.

Figures qualified by a business segment or other breakdown SHALL NOT be read as the company's.

⚠ An annual filing reports the same measure for the final quarter and for the whole year under
an identical tag. Reading the wrong one is wrong by roughly four, silently, on every ratio
derived from it — and nothing downstream could detect it.

#### Scenario: An annual filing carrying both a quarter and a year

- **WHEN** figures are extracted from it
- **THEN** the yearly figure and the quarterly figure are stored as distinct periods

#### Scenario: A filing reporting revenue by segment

- **WHEN** figures are extracted
- **THEN** no segment's figure is recorded as the company's own

### Requirement: A company that reports on one basis only is still read

Where a company reports both a consolidated and a standalone statement, the system SHALL use
the consolidated one. Where only one basis exists, the system SHALL use it, and SHALL record
which basis every figure came from. The system SHALL NOT mix bases within a series.

⚠ A company with no subsidiaries files no consolidated statement. Requiring one leaves such a
company with no financial history at all, and the failure reads as though the company does not
report.

#### Scenario: A company with no subsidiaries

- **WHEN** its filings are read
- **THEN** its standalone statements are used, and each figure records that basis

### Requirement: Business quality is scored from filed figures alone, and says what it could not measure

The system SHALL score a company's business quality and the reasonableness of its price using
only figures from filings and observed prices, computing every ratio in ordinary code.

A component whose inputs are absent SHALL be reported as **unmeasured**, never as zero. The
score SHALL be reported as points earned against points **available**, and the unmeasured
components SHALL be named.

A component requiring several years SHALL decline to answer where too few years have been read.

#### Scenario: A company whose filings have not been read

- **WHEN** it is scored
- **THEN** every component reports unmeasured, nothing is scored zero, and the interface can
  name what is missing

#### Scenario: A single year against a multi-year test

- **WHEN** a test asks about several years and one has been read
- **THEN** the component reports unmeasured and states how many years it had

### Requirement: A company is not judged on arithmetic that does not describe it

Where a measure does not apply to a company's kind of business, the system SHALL report that
measure as unmeasured rather than scoring it.

⚠ Borrowings are a lender's raw material rather than its leverage, and its cash flows follow
deposits rather than trading. Scoring those as though they described an industrial classifies
a sound lender as a failing business — and that classification blocks any further purchase.

#### Scenario: A lender scored on leverage

- **WHEN** a company whose business is lending is scored
- **THEN** leverage, cash conversion and return on capital report unmeasured, and the measures
  that do describe it are scored normally

### Requirement: A verdict that blocks a purchase is refused on a partial reading

Where the system classifies a company into a category that forbids buying it, it SHALL first
require that enough of the score was measurable, including the company's price.

⚠ A company blocked because its accounts have not been read is indistinguishable from one
blocked because it deserves to be, and only one of those is a judgement.

#### Scenario: Few components could be measured

- **WHEN** a company is classified
- **THEN** no category that blocks a purchase is assigned, and the classification states that
  the reading was too thin to judge

#### Scenario: The company's price is unknown

- **WHEN** a company has no observed price
- **THEN** no blocking category is assigned, because price is half of the question

### Requirement: A checklist question with no evidence is answered unknown

Where a checklist question can be computed from filings or prices, the system SHALL compute it
and SHALL record that it was computed. Where the inputs are absent, the answer SHALL be
**unknown** rather than a default. A computed answer SHALL NOT be overridden by a judgement.

⚠ A checklist that answers "no" by default reports a clean bill of health it never checked.

#### Scenario: No price history exists

- **WHEN** a question about the price range is asked
- **THEN** the answer is unknown, with the reason, rather than "no"

### Requirement: The system proposes and never acts

The system SHALL NOT place an order, connect to any brokerage, or alter the user's real
holdings. An approved suggestion SHALL update only the system's own paper book.

What the user does in the real world SHALL be recorded the same way every other transaction
is — by the user — and the two books SHALL remain separate.

⚠ This is not a limitation to engineer away later. It is what keeps the system outside the
regulatory category governing automated trading, and the difference between the two books is
one of the most interesting measurements the module produces.

#### Scenario: A suggestion is approved

- **WHEN** the user approves a suggestion
- **THEN** the system's own paper book records it, the real book is untouched, and no order
  exists anywhere

### Requirement: A suggestion is recorded with everything that produced it, frozen

Every suggestion SHALL record, at the moment it is made: the price the system saw, the scores
it rested on, which rules were checked and what each decided, the version of the framework in
force, and references to the records its figures came from.

None of these SHALL be recomputed when the suggestion is later read.

⚠ What the system SAW is a different fact from what the market DID. A review that recomputes
the inputs is reconstructing a decision rather than examining one, and the difference is
invisible from the outside.

#### Scenario: A suggestion is reviewed months later

- **WHEN** an old suggestion is read
- **THEN** the price, the scores and the rule results are those recorded at the time, not
  today's

### Requirement: A suggestion cannot be made without stating what would prove it wrong

Every suggestion to buy SHALL carry at least two invalidation conditions, each expressed as a
metric, a comparison, a threshold and a deadline. Conditions expressed only in prose SHALL be
refused.

⚠ "If the story changes" cannot be checked, so a position carrying it can never be shown to
have been wrong — which is the same as carrying no condition at all, dressed as caution.

#### Scenario: A suggestion with only narrative conditions

- **WHEN** its invalidation conditions cannot be evaluated mechanically
- **THEN** the suggestion is refused and the refusal names that rule

### Requirement: The rules that refuse a suggestion are applied by code, not by instruction

The conditions under which a suggestion may not be made SHALL be evaluated in program code
against stored records. The system SHALL NOT rely on a language model being instructed to
respect them.

The result of every rule SHALL be recorded, distinguishing a rule that passed from one that
did not apply.

⚠ A rule that a sufficiently persuasive argument can talk its way past is a preference. The
reason for writing rules down before anything is at stake is that they bind on the day you
would rather they did not — and "not asked" counted as "satisfied" would overstate how much
was ever checked.

#### Scenario: A company whose business is poor and whose story is loud

- **WHEN** it is considered for purchase
- **THEN** it is refused regardless of how strong the argument for it reads

#### Scenario: A sale considered against rules about buying

- **WHEN** the rules are applied
- **THEN** the buying rules are recorded as not applicable rather than as passed

### Requirement: A refused suggestion is recorded as carefully as an accepted one

Where a rule refuses a suggestion, the system SHALL still record the suggestion, the rule that
refused it, and an entry in a separate book tracking what did not happen.

⚠ A rule whose cost is invisible is a rule nobody can evaluate. Only the record of what the
rules refused can ever answer whether they are protecting or merely obstructing.

#### Scenario: A rule blocks a purchase

- **THEN** the suggestion is stored with the blocking rule named, it is never offered for a
  decision, and it appears in the book of what the rules refused

### Requirement: Every decision carries a reason in the user's own words

The system SHALL require a reason with every approval, rejection or modification, and SHALL
refuse a decision without one.

⚠ The reason is the data that eventually reveals what kinds of suggestion keep being turned
down. It is the only route by which the system learns anything about its own judgement; a
decision without one records that something happened and nothing about why.

#### Scenario: A decision is submitted with no reason

- **THEN** it is refused, and nothing is recorded

### Requirement: A suggestion lapses rather than standing indefinitely

A suggestion not acted on within a defined period SHALL be treated as lapsed and SHALL NOT be
actionable.

⚠ A suggestion was made at a price. Weeks later that price is history, and acting on it is
acting on a judgement about a world that has moved.

#### Scenario: An old suggestion

- **WHEN** the user tries to act on a suggestion past its validity
- **THEN** the attempt is refused with that reason

### Requirement: Every thinking run is recorded, including the ones that suggest nothing

The system SHALL record each run of the deciding job with what it considered and what it
produced, whether or not it produced anything.

⚠ Suggesting nothing is a normal and frequently correct outcome. A system that only leaves a
trace on the days it acted can never be measured against the days it should have acted and did
not — the record becomes a highlight reel.

#### Scenario: An evening with nothing worth suggesting

- **THEN** a run is recorded showing what was considered and that nothing was produced, and
  the user is not notified

#### Scenario: The same run happens twice

- **WHEN** a scheduled run repeats for an occurrence already recorded
- **THEN** no second set of suggestions is written

### Requirement: New companies arrive from what the system reads, not only from the user

The system SHALL poll registered sources, record everything each published, and recognise the
listed companies each item names. A company the user does not follow SHALL open a line in a
research queue rather than being discarded.

Recognition SHALL be deterministic, against the exchange's own list of listed companies. No
model SHALL introduce a company name into the record.

⚠ Without this the system can only ever say hold, trim or sell. A research assistant that can
comment only on what is already owned is a bookkeeper with opinions.

#### Scenario: A source names a company nobody follows

- **WHEN** an item names a listed company that is neither held nor watched
- **THEN** a research-queue line is opened recording which source named it and what was said,
  and nothing is bought, scored or recommended by that fact alone

#### Scenario: A model proposes a name that is not listed

- **WHEN** a model returns a company name that no listed company matches
- **THEN** nothing is recorded for it, exactly as if the name had been misheard

### Requirement: Every company a source names is recorded, whether or not it was acted on

The system SHALL record a mention for every instrument every claim-making source names,
including companies never looked at, dismissed, or already held.

⚠ Judging a source on the ideas that were acted on measures the reader's filter rather than
the source: forty companies named, three looked at and one that worked reads as 33% instead of
2.5%. The skipped ideas are the denominator and cannot be reconstructed afterwards.

#### Scenario: A source's record is read

- **WHEN** a source's performance is reported
- **THEN** the count of everything it named is the denominator, and how many became
  suggestions is reported separately

### Requirement: What a video said is read, not what its title advertised

Where a source publishes video, the system SHALL read the spoken words where they can be
obtained, and SHALL record for every item whether they could be.

An item whose words could not be read SHALL be distinguishable from an item that named no
company.

⚠ A title is advertising copy. A video titled for a theme routinely names a dozen companies in
its first two minutes and none in its title.

#### Scenario: The words are in a script the matcher cannot read

- **WHEN** a transcript is not in the script the deterministic matcher recognises
- **THEN** it is recorded as read-but-not-matchable, and reporting it as naming no company is
  a claim about the reader rather than about the video

### Requirement: Where the system reads from is the user's decision, changeable by the user

A source SHALL be registered inactive and unapproved, and SHALL be read only after the user
approves it. The user SHALL be able to add, approve and switch off a source from the
interface.

A source SHALL be switched off rather than deleted.

⚠ Adding a commentator changes what the system can be talked into. Deleting one would orphan
every mention that cited it and silently rewrite the record of where ideas came from.

#### Scenario: A channel is added from a link

- **WHEN** the user supplies a channel in any form the address bar produces
- **THEN** it is registered, inactive and unapproved, and nothing is read from it until the
  user approves it

### Requirement: A rule is never written so that no company could satisfy it

A rule that depends on history SHALL scale to the history that could exist for the subject it
is applied to, and SHALL state which limit is binding when the available history is short.

⚠ A five-year test applied to a company listed eighteen months ago is not strict, it is
unsatisfiable — and from the outside a company that cannot be judged is indistinguishable from
one that was judged badly. The same shape appears wherever a threshold is absolute.

#### Scenario: A company is younger than the window a rule assumes

- **WHEN** a rule spans more years than the company could have filed
- **THEN** the rule is applied over what exists, at reduced weight, and the result states both
  how much was read and how much could have been read

#### Scenario: A target cannot be reached at the current size

- **WHEN** a criterion's threshold cannot be reached at the rate the system can produce
  observations
- **THEN** the interface states that, so a permanently unmet criterion is never mistaken for a
  pending one

### Requirement: A test that does not describe a company is distinguished from one not yet run

Where a component of a score cannot apply to a kind of company, the system SHALL mark it
inapplicable, exclude it from that company's denominator, and render it differently from a
component whose inputs are missing.

The kind of company SHALL be determined from what it filed, not only from a maintained list.

⚠ Treating "does not apply" as a gap in the reading made a completely-read bank carry four
holes and left it permanently unjudgeable — the outcome of failing it, arrived at politely.

#### Scenario: A lender is scored

- **WHEN** a company filed under the banking taxonomy
- **THEN** the components that describe machinery are marked inapplicable, the components that
  describe a lender are computed in their place, and the score is reported against the set
  that applies to it

### Requirement: What was predicted is recorded whether or not the suggestion was offered

Every thesis SHALL record its falsifiable assertions at the moment it is formed, including
where a rule refused the suggestion. Each SHALL carry whether the idea was offered or blocked.

An assertion already outstanding about the same company SHALL NOT be recorded again.

⚠ Calibration is a property of the judgement, not of the purchases. Recording only what
survived the gates produced a system that ran for a month and wrote no predictions at all,
because in an expensive market nothing survives. Recording every night's without
deduplication is the opposite failure: a measure that reads as a large sample while being a
sample of one.

#### Scenario: Every suggestion is blocked

- **WHEN** a thinking run suggests nothing because every candidate was refused by a rule
- **THEN** the predictions each thesis made are still recorded, each carrying the rule that
  refused it

#### Scenario: The same thesis is formed again the next night

- **WHEN** a company is reconsidered and asserts what an outstanding prediction already
  asserts
- **THEN** no second copy is recorded

### Requirement: Conditions to watch belong to suggestions that were offered

Invalidation conditions SHALL be written only for suggestions that survived every rule.

⚠ A condition asks what would make the user sell something. Arming one on an idea that was
never bought would raise exit alerts about holdings that do not exist, and would corrupt the
measure of whether fired conditions were acted on.

#### Scenario: A suggestion is blocked

- **WHEN** a rule refuses a suggestion
- **THEN** no invalidation condition is armed for it

### Requirement: The same figures are reachable in conversation as on the page

Every figure available in the interface SHALL be reachable through the assistant, computed by
the same service code.

The assistant SHALL NOT write to the ledger or record a decision in a single step. Both SHALL
be prepared and then confirmed by the user.

⚠ A rule implemented for only one of the two is a rule the other one skips. And a decision is
the row the system is eventually graded on — a model that could record one unaided would be
writing its own report card.

#### Scenario: The user asks why a company is scored as it is

- **WHEN** the user asks about a company in conversation
- **THEN** the answer comes from the same score the page shows, component by component, with
  what could not be measured named

#### Scenario: The user decides on a suggestion in conversation

- **WHEN** the user asks to approve or reject a suggestion
- **THEN** the assistant states what would be recorded and records nothing until the user
  confirms it

### Requirement: The user's own judgement is measured against alternatives that could have been bought

The system SHALL maintain parallel books recording what would have happened under different
rules, and SHALL compare the real book against index funds over the same window and the same
grid.

Where the two sides do not share a window, or where part of the book has no counterpart in the
comparison, the system SHALL say so rather than report the comparison.

⚠ The alternative is an index *fund*, not an index: an index cannot be bought, and a fund's
value carries the fees a real alternative would have charged.

#### Scenario: Part of the book has no index counterpart

- **WHEN** the portfolio holds assets no benchmark stands in for
- **THEN** the share they represent is stated beside the comparison

### Requirement: Whether the experiment is working is judged against criteria written in advance

The system SHALL record go/no-go criteria before any of them can be measured, and SHALL report
each as met, not met, or not yet testable.

"Not yet testable" SHALL NOT be reported as a failure.

⚠ Criteria chosen after the results are known are criteria chosen to be satisfied. The design
is only meaningful because the answer "no, this does not work" is easy to see.

#### Scenario: A criterion has too small a sample

- **WHEN** a criterion's measure rests on fewer observations than it needs
- **THEN** it reports not-yet-testable with the count, and no figure is shown
