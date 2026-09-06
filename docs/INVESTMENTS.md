# INVESTMENTS.md — the ledger, and why it is shaped this way

> **Phase 1 of the Investments module: the bookkeeper, with no analyst on top of it.**
> No market feed, no scoring, no proposals, not one model call. Scoring and proposals are
> Phase 2; live prices are Phase 1b.

---

## 1. The one idea

**Transactions are facts. Everything else is a function of them.**

A position is not a row that gets updated when you buy more — it is `fold(transactions)`. A
cost basis is not maintained, it is computed. A portfolio value is not stored, it is
positions × latest prices, evaluated when someone looks.

That costs a little arithmetic on every read and buys the one property that matters:
**nothing derived can drift out of step with what actually happened.** Every portfolio
tracker that has ever shown a wrong holding did so because it stored a number and missed an
update.

Measured on the real seed — 27 transactions — the fold is sub-millisecond. At 500
transactions a year it stays sub-millisecond for years, which is why there is no cache.

---

## 2. Why the ledger cannot be edited

`transactions`, `price_observations` and `fx_observations` are **INSERT-only**, enforced by a
Postgres trigger. This is the one place in Acero where convention 6 — soft delete with an
undo toast — is deliberately not followed.

The reason is what the record is *for*. Everywhere else, a deletion is someone changing their
mind about something they wrote. Here the record exists to be judged against months later:

> *"What did I own in March, and what did I believe when I bought it?"*

If a row can be edited afterwards, that question has no stable answer, and every review built
on it is a story rather than a measurement.

So **a sale is an event, and a mistake is a counter-event.** A correction is a new row
carrying `supersedes_id`; readers resolve to the rows nothing supersedes; both stay readable.

**Undo still exists in the interface.** It inserts a zero-quantity `ADJUSTMENT` that
supersedes the original — the user sees the familiar gesture, the ledger sees an event.

> A contra entry (a matching SELL against a mistaken BUY) was the alternative and is wrong:
> it conflates *"I typed this wrongly"* with *"I sold it"*, inventing a disposal that never
> happened and a realised gain to go with it.

The trigger is not decorative. `tests/test_investments_ledger.py` asserts that UPDATE and
DELETE both raise and the row survives — a trigger nobody tests is a comment.

---

## 3. Two books, and why they are not nested

| Book | Holds |
|---|---|
| `REAL` | what you actually own |
| `MIRROR` | what Acero's approved decisions would have produced *(empty until Phase 2)* |

It is tempting to think of one as a subset of the other. It isn't, because three categories
exist:

- Acero proposed → you approved → **you did it** — the intersection
- Acero proposed → you approved → **you didn't** — paper only
- **You bought something Acero never proposed** — real only

That third group is the direct measurement of your unaided judgement against the machine's. A
single combined book would silently discard it.

---

## 4. Prices are observations with an age

A price is a row carrying `source`, `observed_at` and a quality flag. **A price you typed and
a price an adapter fetched are the same kind of fact**, differing only in `source` — which is
what let all of valuation, staleness and returns be built and proven before any market feed
exists. Phase 1b changes one column's value and nothing else.

**Staleness applies regardless of source.** A price typed nine days ago is exactly as stale as
a dead feed's. Exempting typed prices would have shipped the staleness logic untested, to run
first in anger against real market data.

| Asset | Stale after | Why that number |
|---|---|---|
| Indian equity, market open | 30 min | It moves every few seconds |
| Indian equity, after close | **20 h** | ⚠ The closing price **is** the current price until the next open. Flagging it at 30 min overnight would mark the whole portfolio stale every evening — which is how a staleness signal becomes noise and stops being read |
| Mutual fund NAV | 48 h | Publishes once daily; 24 h would cry wolf every weekend |
| Crypto | 4 h | Trades 24/7, so there is no settled price to fall back on |

**An unpriced holding reports `None`, never zero**, and never a last-known value shown
silently as current. A foreign holding with no exchange rate is reported *unpriced* rather
than valued at par — treating a dollar as a rupee produces a plausible number nobody
questions, which is the worst shape an error can take.

---

## 5. Quantity or amount — which is the primary fact?

This was learned twice during the build, from real data, and it generalises:

> **Where the *amount* is primary and units follow from it — mutual funds, fractional shares,
> crypto — store units at full precision and let the amount be exact. Where the *quantity* is
> primary — whole shares on an exchange — store the quantity.**

Both times the code caught a hand-computed figure rather than the other way round:

- **SPCX.** Units at the 6dp INDmoney displays made the rupee basis 2 paise wrong. At 8dp,
  `$155.31 × 96.01 = ₹14,911.31` exactly.
- **The HDFC funds.** Units at the 3dp Groww displays made the cost basis ₹0.64 too high.
  Derived at 8dp from the ₹4,999.75 that actually left the bank, it is exact — and the stored
  units sit 0.0003 below Groww's displayed total, worth about ₹0.74.

Cost basis wins that trade every time: returns and XIRR are computed from it, while a 0.0003
unit difference moves a valuation by less than a rupee.

---

## 6. Returns: two numbers, always together

**XIRR** is money-weighted — affected by *when* money went in, so it measures your timing.
**TWR** is time-weighted — it removes cash-flow timing, so it measures the strategy. Showing
either alone invites crediting the wrong thing, and the gap between them is itself
informative.

The XIRR convention was **solved for against Groww's published figures**, and all three parts
matter because all three are invisible:

1. The valuation date
2. Terminal value = **units × NAV**, not the rounded card figure
3. Day count **actual/365**

| | Groww | Acero |
|---|---:|---:|
| HDFC Mid Cap | 12.25% | **12.25%** — exact |
| HDFC Flexi Cap | 6.48% | 6.49% — the 0.01pp is the displayed NAV's own 3dp rounding |

Newton–Raphson with a bisection fallback, pure `Decimal`, no dependencies. `quantstats` and
`pyfolio` were rejected: pandas + numpy + scipy + matplotlib + seaborn + yfinance on a 1 GB
box, for about ten formulas worth 150 lines.

**Currency is decomposed on every non-INR holding** — `r_local`, `r_fx`, `r_total_inr` — using
the rate stored on each transaction. Without it, a weakening rupee silently credits the system
with skill it does not have.

---

## 7. Costs and tax

Rates live in `charge_schedules`, keyed by effective date, and the schedule id is **frozen onto
each transaction** — exactly as `core/pricing.py` freezes model prices. Recomputing March's
charges at October's rates would silently rewrite March's return.

⚠ **Groww is not Zerodha.** The module spec originally modelled Zerodha's charge sheet:
₹0 delivery brokerage and a ₹15.34 DP charge. Groww charges `min(₹20, 0.1%)` floored at ₹5 **on
both legs**, and ₹23.60 for DP. On a ₹13,422 buy that is ₹13.42 the model would have missed on
every trade, forever. See `docs/transactioncostsreference.md`.

**The number to carry into Phase 2:** a ₹13,422 → ₹15,000 round trip costs **₹88.64 — a 0.66%
break-even move, and 5.6% of the gain.** Any thesis targeting less than about 2% is not worth
transacting.

### Prepaid tax is not a cost

Crypto TDS (1%, s.194S) and LRS TCS are **withheld against a future liability and are
creditable or refundable.** Booking them as expense would understate returns *and* double-count
against the flat 30% VDA rate. They are recorded in `prepaid_tax_inr`, visible, and excluded
from `charges_inr`.

### Holding periods are three explicit rules

| Asset | Long-term after | Rates |
|---|---|---|
| Indian equity, equity MF | 12 months | 12.5% vs 20% |
| **US equity** | **24 months** | 12.5%, no indexation |
| Crypto | **never** | flat 30%, **no set-off, no carry-forward** |

Not a default with exceptions — three rules, because the US one is the one that goes silently
wrong when 12 is the number everyone has in mind.

**Crypto losses are ring-fenced in the totals.** Under s.115BBH a crypto loss offsets nothing —
not another crypto gain, not equity, not a future year. A single netted portfolio figure would
show a position the tax code does not permit, and would be planned against.

### FIFO and weighted average, both labelled

Indian demat disposals are matched FIFO, so that is the only basis on which a realised figure
means anything for tax. Weighted average is what every broker app shows. **They genuinely
disagree**, and the real Kaynes lots make it concrete:

> Five lots at ₹4,133.20, ₹3,388, ₹3,271, ₹3,102, ₹2,999.80. Sell two at ₹3,598.
> **FIFO** relieves ₹7,521.20 → a **loss** of ₹325.20.
> **Weighted average** relieves ₹6,757.60 → a **gain** of ₹438.40.
> Same trade, opposite sign.

Picking one silently means either the tax view is wrong or the displayed number contradicts
Groww for no visible reason. So both are computed and each is named.

---

## 8. Using it from chat

The assistant tools call the same service functions as the REST API — convention 2, because a
validation that lives in only one of them is a validation the other can skip.

⚠ **The model never writes directly.** `record_transaction` returns a *draft* — what it
understood, costed and validated — and the user confirms with `confirm_transaction`. Two steps
on purpose: a model that can append to the ledger in one call is a model that can invent a
holding.

```
bought 12 Tata Power at 412 today
  → Buy 12 TATAPOWER at ₹412 on 6 Sep. Charges ₹15.42, total ₹4,959.42.
    New holding — recording it also starts tracking it. Confirm?

what do I own?          how close is Sai Life to long-term?
HDFC Bank is at 712     undo that last entry
```

**Recording a holding is also how an instrument enters the tracked set.** There is no separate
"add to watchlist" — a tracked set maintained apart from holdings is one that will disagree
with them, and the disagreement surfaces as a filing nobody was watching.

---

## 9. Seeding

```bash
uv run python -m app.scripts.seed_investments --check   # reconcile, write nothing
uv run python -m app.scripts.seed_investments           # write it
```

Idempotent. It reconciles what it wrote against `seed-reconciliation.md` and exits non-zero on
any disagreement.

⚠ **Two rows are honest aggregates.** Dogecoin (₹840 across 4 buys) and Bitcoin (₹150 across 2)
are one row each at the average price, dated to the first buy, marked `IMPORT` with a note
saying so. The per-buy amounts are not recoverable from CoinSwitch, and a labelled aggregate
is honest where an invented breakdown would not be.

---

## 10. What is deliberately absent

- **No market feed.** Prices are typed. Phase 1b.
- **No scoring, proposals or gates.** Phase 2, and it needs the framework documents.
- **No automatic corporate actions** — they need the exchange feed. Until then a split or
  bonus is entered by hand as a `SPLIT`/`BONUS` transaction, which conserves total cost basis.
  ⚠ **Accepted risk:** an unrecorded corporate action shows as a large phantom loss. The
  mitigation is a page-level warning on any holding that moved more than 25% in a day, which
  arrives with the Investments page.
- **No valuation cache.** The fold is fast; a cache that is never wrong is also never tested.
- **No tax computation.** Holding periods, lots and flags — yes. A liability figure — never.
- **No Investments page yet.** Split into its own change so it gets a proper design pass
  rather than being rushed at the end of a long one.

---

## 11. Where the code is

```
backend/app/services/investments/
  portfolio.py   the fold — transactions to positions, FIFO lots
  pricing.py     observations, staleness, valuation, honest totals
  returns.py     XIRR, TWR, currency decomposition, Sharpe error bar
  taxrules.py    holding periods, lot matching, ring-fencing
  costmodel.py   charges from a dated schedule
  entry.py       the one write path, shared by API and tools

backend/app/core/tools/investments.py   six tools, draft-then-confirm
backend/app/scripts/seed_investments.py the real portfolio
backend/alembic/versions/…014_investment_ledger.py
```

Tests: `test_investments_ledger.py` (the fold, against Groww),
`test_investments_returns_and_costs.py` (XIRR against Groww, charges against the reference),
`test_investments_entry.py` (validation, correction, staleness),
`test_investments_seed.py` (the script).
