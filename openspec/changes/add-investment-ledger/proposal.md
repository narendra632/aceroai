# The investment ledger

## Why

Narendra holds ₹89,015 across four asset classes on three apps that do not talk to each
other — Groww for Indian equity and mutual funds, CoinSwitch for crypto, INDmoney for a US
share. Each shows a number. None of them knows what the others hold, none records **why**
anything was bought, and none will still be able to answer that question in a year.

The Investments module answers it. But it is a research analyst sitting on top of a
bookkeeper, and **the bookkeeper has to be provably right before the analyst is allowed to
speak.** A system that reasons beautifully about a portfolio it has mis-counted is worse than
no system, because it is wrong with citations.

So this change builds the ledger and nothing else. **No scoring, no proposals, no AI
anywhere in it.** Its entire success condition is arithmetic: given fifteen real
transactions, does it reproduce the numbers Groww itself prints, to within modelled costs?

That question is answerable now, offline, with no market data feed and no model call — which
is exactly why it goes first. Every later phase rests on it, and a fold that is wrong in
month one is wrong in every review for a year.

**The seed data is already reconciled by hand.** Fifteen Groww transactions sum to
₹62,527.85 against Groww's stated ₹62,527.96 — eleven paise, pure rounding. Mutual fund units
sum exactly to redeemable units on both funds. Three SPCX buys sum to $155.31 and 0.862429
units, both exact. That reconciliation already caught something: a Kaynes order for 1 share
at ₹3,080 that appears in the order list and did **not** execute — including it gives 6
shares and ₹19,974, excluding it gives exactly the 5 shares and ₹16,894.00 Groww reports.
The check works. This change encodes it.

## What Changes

- **A ledger where transactions are the truth.** Every position, cost basis, weight and
  return is a fold over transactions, computed on read. Nothing derived is stored, so nothing
  derived can drift.
- **Transactions are append-only.** No edit, no soft delete. A mistake is corrected by a
  reversing entry carrying `supersedes_id`, exactly as a ledger works — because the record of
  what you believed at the time is the product, and a record that can be quietly rewritten is
  worthless for judging yourself later.
- **Two books from the start, not one.** `REAL` is what Narendra actually holds. `MIRROR`
  will hold what the AI's approved decisions produce, and stays empty until proposals exist.
  They are **not** subsets of one another — he will do things the AI never proposed, and the
  AI will propose things he does not do. The gap between them is the measurement, and a
  single-book design would discard it.
- **Prices are entered by hand in this change, through the same table a feed will write to
  later.** A price is an observation with a source; `USER` is a source. This is what lets the
  whole valuation, staleness and return machinery be built and proven before any network code
  exists — and it means Phase 1b swaps the source and changes nothing else.
- **Both returns, always shown together.** XIRR judges the investor's timing; TWR judges the
  ideas. Showing one alone invites crediting the wrong thing.
- **Costs and tax positions are modelled, not ignored.** STT, exchange and SEBI charges,
  stamp duty, GST and DP charges, from a versioned schedule frozen onto each transaction. The
  holding-period clock runs per lot: 12 months for Indian equity and equity funds, **24 for a
  US share**, and none at all for crypto.
- **Anything entered joins what the system watches.** Recording a holding is also how an
  instrument enters the tracked universe — there is no second place to "add to watchlist".
- **The assistant can do all of it in chat.** "bought 4 HDFC Bank at 722.65 today" is a
  complete instruction, because `core/tools/investments.py` and the REST API call the same
  service functions.

## Capabilities

### New Capabilities

- **`investments`** — that the book is a faithful, append-only record of what is held; that
  every derived figure is computed from it; and that costs, lots and holding periods are
  modelled rather than assumed away.

### Modified Capabilities

**None.** Two capabilities were considered and deliberately left alone:

- **`assistant-tools`** gains a module, not a rule. It already states *"Tool definitions are
  organised by domain"* and *"the assistant acts on clear requests and confirms risky ones"* —
  `core/tools/investments.py` is those requirements being used, not changed. Restating the
  confirmation rule here would create a second place it could drift.
- **`scheduled-jobs`** is untouched and no job is added. Nothing here runs on a schedule:
  there is no feed to poll and no valuation to refresh automatically. Jobs arrive with the
  price adapters in Phase 1b, and adding an empty one now would be scaffolding pretending to
  be a feature.

## Impact

**Schema.** Migration 014 adds `instruments`, `portfolios`, `transactions`,
`price_observations`, `fx_observations` and `charge_schedules` — six tables, taking the
database from 14 to 20. `transactions`, `price_observations` and `fx_observations` are
**INSERT-only**, enforced by a trigger that raises on UPDATE and DELETE, with a test asserting
the trigger actually fires. `Numeric` throughout, never float. All timestamps `timestamptz`.

**Backend.** New `app/services/investments/` — `portfolio.py` (the fold), `valuation.py`
(marks and weights), `returns.py` (XIRR, TWR, Modified Dietz), `costmodel.py` (charges),
`taxrules.py` (FIFO lots, holding periods, flags), `entry.py` (parsing and validating a
recorded transaction). New `app/core/tools/investments.py`. New `app/api/investments.py`.

**Frontend.** ⚠ **None — the Investments page was split into its own change during
implementation.** It is the largest remaining piece and the only part not covered by the
"does it reproduce Groww" test that every other section is checked against, and this project's
bar is a finished product rather than "it works". `api/investments.py` moves with it, because
it exists only to serve that page: chat reaches the ledger through `core/tools/investments.py`,
and an HTTP surface with no consumer would be scaffolding.

**The ledger is usable without the page**, through chat — recording a transaction, reading the
portfolio or a position, recording a price, and undo. Entry is better in conversation than in
a form; reading is what the page is for.

**Data.** A seeding script for the reconciled real portfolio — 15 Groww transactions, 3
SPCX buys, 4 crypto positions. ⚠ Two of those are honest aggregates: Dogecoin (₹840 across 4
buys) and Bitcoin (₹150 across 2) are entered as one row each at the average price, dated to
the first buy and marked `IMPORT` with a note saying so. The per-buy amounts are not
recoverable from CoinSwitch's history, and an invented breakdown would be worse than a
labelled aggregate.

**Documentation.** `docs/ARCHITECTURE.md` (six tables, a new service package), a new
`docs/INVESTMENTS.md`, `docs/ROADMAP.md`, and the Learn page.

**Dependencies.** **None.** XIRR, TWR and every charge calculation are pure Python and
`Decimal` — about 150 lines. `quantstats`, `pyfolio` and `empyrical` were considered and
rejected: they pull pandas, numpy, scipy, matplotlib, seaborn and yfinance onto a 1 GB box to
obtain roughly ten formulas, and `pyfolio` is effectively unmaintained.

## Non-goals (this change)

- **No market data feed.** No Angel One, no Twelve Data, no CoinGecko, no AMFI. Prices are
  typed in. The adapters are Phase 1b and this change is deliberately shaped so that they
  change one thing: the `source` on a price row.
- **No scoring, no proposals, no gates, no AI.** Not a single model call. The frameworks,
  `framework_scores`, `proposals` and everything downstream are Phase 2.
- **No automatic corporate actions.** Ingesting them needs the exchange feed. Until then a
  split or bonus is recorded by hand as a `SPLIT` / `BONUS` transaction — the type already
  exists in the ledger and conserves total cost basis. ⚠ This is an accepted risk with a
  named owner: until Phase 1b, an unrecorded corporate action shows as a large phantom loss,
  and the page says so where a holding has moved more than 25% in a day.
- **No `daily_valuations` cache.** An equity curve is a fold, and at this size the fold is
  fast. The cache exists to save ~550 folds on an 18-month chart and is premature until there
  is 18 months of history.
- **No tax computation.** Holding periods, lot matching and flags — yes. A liability figure
  or anything resembling a return — no, ever.
- **No screenshot import.** Typing "bought 1 Apar at 13,422" is faster than photographing a
  screen and fails loudly rather than silently. v1.5, per the spec.
- **No shadow books.** They record proposals that were rejected or blocked, and there are no
  proposals yet.
