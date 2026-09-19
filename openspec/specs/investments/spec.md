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

#### Scenario: Return is never a single number

- **WHEN** return is displayed for a portfolio or a holding
- **THEN** both measures appear together, each labelled with what it measures

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

