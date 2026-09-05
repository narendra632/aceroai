# Design — the investment ledger

## The one idea

**Transactions are facts. Everything else is a function of them.**

A position is not a row that gets updated when you buy more; it is `fold(transactions)`. A
cost basis is not maintained; it is computed. A portfolio value is not stored; it is
positions × latest prices, evaluated when someone looks.

This costs a little arithmetic on every read and buys the one property that matters: **nothing
derived can drift out of step with what actually happened.** Every portfolio tracker that has
ever shown a wrong holding did so because it stored a number and missed an update.

Measured against the real seed: 22 transactions fold in well under a millisecond. At 500
transactions a year it stays under a millisecond for years. The cache that would save this is
in the non-goals for exactly that reason.

---

## Decision 1 — Prices are typed in first, through the table a feed will later write to

**Chosen:** `price_observations` carries `source`, and in this change the source is `USER`.
A person entering "SPCX is at 147.90" writes the same row shape an adapter will write.

This is the decision that makes Phase 1 shippable. Without it, nothing about valuation,
staleness, currency decomposition or returns could be built or tested until an external feed
existed — and every one of those is pure arithmetic that deserves to be proven on its own,
before a network dependency can be blamed for a wrong number.

It also means **Phase 1b changes one thing**: a different value in `source`. No migration, no
refactor, no second code path.

**Rejected: waiting for the feed.** It would have made the first useful thing months away and
entangled two kinds of failure — "the fold is wrong" and "the feed is wrong" — in one debugging
session. Separating them is worth a week.

**Rejected: a `manual_prices` table.** Two tables meaning the same thing, joined everywhere,
diverging eventually. `source` already exists to answer "where did this come from".

**The staleness rule applies to typed prices too, and this is the point.** A price entered
nine days ago renders greyed with its age, exactly as a dead feed would. If manual prices were
exempt, the staleness logic would ship untested and first run in anger against a real feed.

---

## Decision 2 — Transactions are append-only, and this is the one place the project's
## soft-delete convention does not apply

**Chosen:** `transactions`, `price_observations` and `fx_observations` are INSERT-only.
A Postgres trigger raises on UPDATE and DELETE. Corrections are new rows carrying
`supersedes_id`; readers filter to rows not superseded.

Convention 6 says soft delete with an undo toast, and it is right everywhere else in this
codebase. Here it is wrong, for a reason worth stating rather than assuming:

> **A sale is an event, not a deletion.** A wrong entry is corrected by a reversing entry,
> exactly as a paper ledger works. The alternative — a mutable row — means the answer to
> "what did I own in March?" depends on what has been edited since.

The whole product is a record you can be judged against. A record that can be quietly
rewritten cannot judge anybody.

**The UI still offers undo**, and it is implemented as "insert the reversing row". The user
sees the familiar gesture; the ledger sees an event. That is the correct place for the
difference to live.

**Rejected: an `is_deleted` flag.** Softer than a trigger and therefore weaker — it relies on
every future query remembering the filter. The trigger cannot be forgotten, and the test
asserting the trigger fires is what stops a later migration quietly dropping it.

---

## Decision 3 — Two books from the start

**Chosen:** `portfolios` with `kind`, seeded with `REAL` now and permitting `MIRROR` and the
shadow kinds later. `MIRROR` is created empty in this change.

Narendra's model was *"my real portfolio is a subset of the investments portfolio"*. It is
very nearly right and the difference matters. Three categories exist:

| | |
|---|---|
| AI proposed → approved → **actually done** | the intersection |
| AI proposed → approved → **not done** | paper only |
| **Bought with no AI involvement at all** | real only |

He confirmed the third category exists. So neither book contains the other, and the third
group is the most interesting data in the system — it is the direct measurement of his
unaided judgement against the machine's. A subset model silently discards it.

Creating `MIRROR` empty now rather than in Phase 2 avoids a migration and makes the shape
visible while the reasoning is fresh.

---

## Decision 4 — Positions computed, never stored

**Chosen:** `services/investments/portfolio.positions(db, portfolio_id)` folds transactions
into quantity, cost basis and realised P&L.

**Rejected: a `positions` table maintained on write.** It is the single most common source of
wrong numbers in portfolio software, it violates the project's "derived values are computed"
convention, and it would need reconciliation logic — which is a second fold, written to check
the first, at which point the first is redundant.

**Rejected: caching the fold in `daily_valuations`.** Justified at 18 months of history and
550 folds per chart. At 22 transactions it is an optimisation of something already
immeasurable, and a cache that is never wrong is also never tested.

---

## Decision 5 — FIFO for tax, weighted average for display, labelled

**Chosen:** both, computed separately, each named in the interface.

Indian demat sales are matched **FIFO** — that is what the tax view must use. Weighted average
is what every broker app shows and what a person recognises. They give different realised
P&L on a partial sale, and presenting either as "the" number is misleading.

So both exist, and the UI says which is which. The alternative — picking one — means either
the tax view is wrong or the displayed number disagrees with Groww for no visible reason.

His Kaynes position makes this concrete: five shares bought at ₹4,133.20, ₹3,388, ₹3,271,
₹3,102 and ₹2,999.80. Sell two, and FIFO realises against ₹4,133.20 and ₹3,388 while weighted
average realises against ₹3,378.80 twice. Different tax, same trade.

---

## Decision 6 — Charges come from a versioned schedule frozen onto the transaction

**Chosen:** `charge_schedules` keyed by effective date; the applicable schedule's id is
written onto each transaction when it is recorded.

Directly parallel to how `core/pricing.py` freezes LLM prices at write time, and for the same
reason: **rates change, and a historical trade must keep the cost it actually bore.**
Recomputing March's charges at October's rates silently rewrites March's return.

Modelled for Indian equity delivery: STT 0.1% both sides, exchange transaction charges, SEBI
turnover fee, stamp duty 0.015% on buys only, GST 18% on the fee components, and DP charges
per scrip on sells. Brokerage 0 for delivery on a discount broker.

⚠ These rates are **broker- and date-dependent and will drift.** They live in a table
precisely so that correcting them is a new row rather than an edit, and so a review can always
ask which schedule was in force.

---

## Decision 7 — XIRR by Newton–Raphson with a bisection fallback

**Chosen:** Newton–Raphson from `r₀ = 0.10`, 100 iterations, tolerance 1e-7; on divergence,
bisection over `[-0.9999, 10.0]`. Pure Python, `Decimal`, ~40 lines.

Newton is fast and usually converges in under ten iterations. It is also capable of shooting
off to nonsense on awkward cash flows — flows clustered near the end, or a portfolio briefly
worth less than nothing. Bisection cannot fail on a bracketed sign change, so the pair is
fast in the common case and correct in the rare one.

**Verification is against an independent source, not against itself.** A spreadsheet's `XIRR`
on the same flows, agreed to six decimals — and a second, deliberately hard case with flows
bunched at the end. A test that only compares the implementation to its own earlier output
proves the code has not changed, not that it is right.

His HDFC Flexi Cap gives a free real-world check: Groww computes **6.48%** on those three
purchases, and the Mid Cap **12.25%**. Reproducing those is a stronger test than any synthetic
case, because it is arithmetic somebody else did.

**Rejected: `quantstats` / `pyfolio` / `empyrical`.** pandas + numpy + scipy + matplotlib +
seaborn + yfinance, on a 1 GB box, for about ten formulas totalling ~150 lines. `pyfolio` is
effectively unmaintained. Read `quantstats`' `stats.py` as a reference implementation and port
what is needed — the metric definitions are the valuable part, not the package.

---

## Decision 8 — Currency is decomposed from the first US transaction

**Chosen:** `fx_rate_inr` is stored **on the transaction**, not looked up later, and returns
on any non-INR holding are always reported as `r_local`, `r_fx` and `r_total_inr` separately.

The rate at the moment of a purchase is a fact about that moment and is not recoverable later
with the same meaning. And without decomposition, a depreciating rupee silently credits the
system with skill it does not have — the single easiest way for this project to flatter itself.

SPCX is the only holding this applies to today, which makes it the right time to build it: one
holding, easy to verify by hand, before there are ten.

---

## Decision 9 — The tax module flags, and never computes a liability

Holding-period clocks per lot, the boundary dates, and the flags. **Never a number that looks
like tax owed.**

| Asset | Long-term after | Why it is separate |
|---|---|---|
| Indian equity, equity MF | 12 months | 20% → 12.5% at the boundary |
| **US share (SPCX)** | **24 months** | A different clock entirely, easy to get wrong |
| Crypto | never | Flat 30%, **no set-off, no carry-forward** |

The crypto row is why the module will never propose crypto, and it is visible in the seed
data: −₹1,076 of realised-if-sold losses across DOGE, ZIL and JASMY that can offset nothing —
while the ₹6.01 Bitcoin gain would still be taxed. The ledger must show that asymmetry rather
than netting it, because netting it is the exact mistake the tax code punishes.

**Schedule FA obligation starts now**, not when it is convenient. It is calendar-year, has no
minimum threshold, and requires the **peak** value of each foreign holding during the year.
SPCX was bought in June and July 2026, so part of that peak window is already history —
capture starts with this change or the figure is unreconstructable.

---

## Decision 10 — One entry path, in the service layer

`services/investments/entry.record()` is called by the REST endpoint **and** by the assistant
tool. Convention 2, and the reason it exists: a validation that lives in only one of them is a
validation the other can skip.

The parsing of "bought 4 HDFC Bank at 722.65 today" into a structured transaction happens in
the **tool**, and the result is shown back for confirmation before it is written. The service
receives structured data and never prose. A model that can write directly to the ledger is a
model that can invent a holding, and D1 of the whole module exists to prevent exactly that.

**Rejected: letting the model call `record` with free text.** It is one line shorter and gives
up the property the entire design is built on.
