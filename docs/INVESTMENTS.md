# INVESTMENTS.md — the ledger, and why it is shaped this way

> **Phases 1 and 1b of the Investments module: the bookkeeper, fed real prices, with no
> analyst on top of it.** No scoring, no proposals, not one model call — those are Phase 2.
> Where prices come from is §14.

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
exists. Phase 1b did change one column's value and nothing else — and then found the
staleness rule below had been wrong all along, which no typed price could have shown.

**Staleness applies regardless of source.** A price typed nine days ago is exactly as stale as
a dead feed's. Exempting typed prices would have shipped the staleness logic untested, to run
first in anger against real market data.

| Asset | Stale after | Why that number |
|---|---|---|
| Indian equity, market open | 30 min | It moves every few seconds |
| Indian equity, after close | **until the next open** (never under 20 h) | ⚠ The closing price **is** the current price until the next open — overnight, and over a weekend. Flagging it at 30 min overnight would mark the whole portfolio stale every evening, which is how a staleness signal becomes noise and stops being read |
| US equity | the same two rules, in **New York** hours | |
| Mutual fund NAV | **until the next business day's NAV** (never under 48 h) | Publishes once daily; Friday's NAV is the latest that exists until Monday evening |
| Crypto | 4 h | Trades 24/7, so there is no settled price to fall back on |

⚠ **Each market's hours are read in its own timezone.** Until the first real feed, this rule
compared the UTC clock against Indian hours (5½ hours out), applied Indian hours to Nasdaq,
and let Friday's close go stale at Saturday lunchtime. Every price was typed, so nothing
showed it. `pricing.staleness_limit`; tests in `test_investments_entry.py`.

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

**TWR is chained daily**, because the value series has every day: each day's return is
`value today ÷ (value yesterday + money added today)`, the purchase counted from the start of
its day, and the first purchase day chained from nothing (`worth that evening ÷ paid`). ⚠ It
was once cut at each purchase with Modified Dietz's default 0.5 weight — which treated every
purchase as made halfway through its period when every one fell at the end — and it skipped
the first purchase day. On the real book those turned **-74.37%** into **-18.85%**.

**TWR is reported over a rolling year**, not since the first purchase. ⚠ Chained returns
never forget: this book fell 73% in its first fifteen months, when it held ₹990 of crypto, so
the since-start figure is **-74%** and needs a **290% gain** to reach zero. It would stay
deeply negative through years of good decisions, and a number that cannot respond to what the
user does next is one they stop reading. A factsheet reports a rolling year for the same
reason. The since-start figure is still computed and stated in the explanation, because
hiding it would be the opposite mistake.

**Each figure carries a sentence in rupees** (`Return.explanation`), because a percentage
labelled "XIRR" means nothing to someone meeting the term. XIRR is *per year*: "you have put
in ₹X and it is worth ₹Y; that is a savings account that shrinks by 1.79% a year". TWR is a
*total since a date*: "₹100 → ₹40 over 12 months". The page says which is which — "per year", "12 months to
<date>" — before it shows either number, and only the elaboration sits behind an "i".

Checked on the real book (2026-09-19): each rupee grown at the reported XIRR from its own
purchase date sums to today's value to the paisa; the TWR equals an independent hand chain
(first day -10.5%, crypto-only stretch to Feb 2026 -73.1%, everything since -4.6%).

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

⚠ **The seed carries the identifiers the price feeds need** — NSE's real symbol (`GVT&D`, not
`GVTD`), the AMFI scheme codes, the CoinGecko ids. They were first written only as data fixes
in migration 016, which mends rows a database already has. On the production server the
migration ran against an empty schema and the seed then re-created the instruments without
them, so GE Vernova and both funds went silently unpriced while everything else worked. **A
migration mends the past; the seed defines the present, and an identifier has to be in both.**

Re-running the seed also CORRECTS what it finds: an instrument stored under an old name is
renamed in place, never joined by a second row — two rows would split one holding's
transactions across two instruments.

---

## 10. What is deliberately absent

- **No scoring, proposals or gates.** Phase 2, and it needs the framework documents.
- **No automatic corporate-action transactions.** A split or bonus on a held NSE stock is
  *announced* (§14) and then entered by hand as a `SPLIT`/`BONUS` transaction, which
  conserves total cost basis. Writing it automatically would mean parsing a ratio out of
  NSE's free text into an append-only ledger with nobody reading it. An unrecorded action
  still shows as a phantom loss, and the page still flags any 25% move — see §12.
- **No valuation cache.** The fold is fast; a cache that is never wrong is also never tested.
- **No tax computation.** Holding periods, lots and flags — yes. A liability figure — never.
- **No screen for typing a price.** Cut once the feed was a week away; prices now arrive
  by themselves (§14). The assistant's `record_price` tool still records one by hand.

---

## 11. The page

Everything above is reachable by asking. The page is what makes it something you *look* at —
and reviewing a portfolio is looking, not querying. A conversation answers the question you
thought to ask; a page raises the one you did not.

Three rules run through every part of it, and they are all about honesty rather than layout.

### Money never becomes a float

Every displayed figure — **including percentages** — is computed in `Decimal` on the server
and crosses the wire as a **quoted JSON string**. The browser converts to a number only for
chart geometry, never for anything a person reads.

Pydantic already does the right thing for a `Decimal` field on a response model. ⚠ But
`jsonable_encoder` — the path a route takes when it returns a bare dict — turns
`Decimal("0.86242900")` into `0.862429`. The value survives; the **scale** does not, and once
it is a JS number the client cannot format or combine it faithfully. Hence the rule with no
exceptions: **every investments route declares a response model.**

The client types every money field as `string`, so a component that tries to add two figures
fails to compile. If something needs summing, it is summed on the server.

### What a figure leaves out is stated beside it

- An unpriced holding shows **no value** and says why — never a zero, never a stale figure
  presented as current.
- A total that excludes holdings **lists them**, at the same size as the figure. A caveat in
  a tooltip is a caveat nobody reads.
- Crypto is reported on its own line. Under s.115BBH its losses offset nothing, so netting it
  in would display a position the tax code does not permit.
- Where only one measure of return can be computed, the page shows it **labelled with what it
  measures** and names the missing one and why. It never labels a lone figure "return".

### Nothing on the chart is invented

Value over time is two folds with opposite characters:

| Line | Source | Density |
|---|---|---:|
| **Invested** | transactions alone | exact, every day, from the first trade |
| **Value** | observed prices, carried forward | only on days where **every** open holding has one |

⚠ The strictness is the point. A line drawn from whatever prices happened to exist steps
every time *coverage* changes, and a reader cannot tell that step apart from a real movement
in the portfolio. Nothing is interpolated across a gap, and the frame states the range the
value line actually covers.

**On a book with no observed prices the value line is simply absent** — which is a correct
answer, not a broken chart. The invested line still draws, and it is the exact record of
money going in.

### Correction, on a record that cannot be edited

The rest of the app deletes with an Undo toast. The ledger has no delete, so the page's
correction action records the reversing `ADJUSTMENT` and says what actually happened:

> **Reversed. The original entry stays in the record.**

Not *"Deleted · Undo"* — that would tell the user something false about the one record in the
system whose worth depends on being unrewritable. Superseded rows stay visible, struck
through, labelled with what replaced them.

### One fold, one endpoint

`GET /api/investments/summary` returns holdings, marks, totals and both returns together,
because they are not four queries — they are one walk over the ledger. Four endpoints would
run that walk four times, and the four answers could disagree if a write landed between them.

⚠ Measured while building it: re-folding the ledger for every day of the chart costs
**6,265 ms** over 659 days, against **3.3 ms** for the incremental walk. 1,887× — the
difference between a chart and a timeout, and the naive version is the one you write without
thinking about it.

---

## 12. The corporate-action warning

Until the exchange feed arrives, a split or bonus nobody recorded appears as a catastrophic
loss in a position that has lost nothing — the one failure mode of this module that produces
a large, alarming, entirely fictional number.

The page flags a holding when two observations **four calendar days or fewer apart** differ by
more than **25%**.

Two restrictions keep it from becoming noise, and both matter:

- **The gap limit.** Observations far apart differ for ordinary reasons. Comparing prices a
  month apart and calling it a single-day move would fire constantly — the same way a
  30-minute staleness limit overnight would mark the whole portfolio stale every evening.
- **A recorded action explains itself.** If a `SPLIT` or `BONUS` sits in the window, the
  corporate action *is* recorded and there is nothing to warn about.

⚠ **Known limitation, stated rather than hidden:** a 1:4 bonus moves the price about 20% and
will not trip this. The threshold sits where false positives are rare, because the real fix is
the feed, not a lower number.

---

## 13. Where the code is

```
backend/app/services/investments/
  portfolio.py   the fold — transactions to positions, FIFO lots
  pricing.py     observations, staleness, valuation, honest totals
  returns.py     XIRR, TWR, currency decomposition, Sharpe error bar
  taxrules.py    holding periods, lot matching, ring-fencing
  costmodel.py   charges from a dated schedule
  entry.py       the one write path, shared by API and tools

  history.py     value over time, and movements too large to be price moves
  overview.py    the one-fold assembly the page and the API read from

backend/app/api/investments.py          summary · holding · transactions · history · entry
backend/app/core/tools/investments.py   six tools, draft-then-confirm
backend/app/scripts/seed_investments.py the real portfolio
backend/alembic/versions/…014_investment_ledger.py
backend/alembic/versions/…015_form_entry_source.py

frontend/src/components/InvestmentsView.tsx   the page
frontend/src/components/PositionSheet.tsx     one holding, in full
frontend/src/components/TransactionEntry.tsx  entry and history
frontend/src/lib/investments.ts               display rules, in one place
```

Tests: `test_investments_ledger.py` (the fold, against Groww),
`test_investments_history.py` (the curve's absences, the corporate-action flag),
`test_investments_overview.py` (the assembly, and which return can be computed),
`test_investments_api.py` (exact money over the wire, ownership, no way to delete),
`test_investments_returns_and_costs.py` (XIRR against Groww, charges against the reference),
`test_investments_entry.py` (validation, correction, staleness),
`test_investments_seed.py` (the script).

---

## 14. Where prices come from (Phase 1b)

Every source was **called live before anything was designed around it** — the results are
§0 of `openspec/changes/add-market-data/tasks.md`. Nothing here rests on documentation alone.

| Holdings | Daily close | Live price | Key |
|---|---|---|---|
| NSE equities | **NSE bhavcopy** — the exchange's own file | **Angel One** quote | Angel One |
| Mutual funds | **AMFI** `NAVAll.txt`; history via mfapi.in | — (one NAV a day) | none |
| US equities + USD/INR | **Twelve Data** daily series | Twelve Data quote | Twelve Data |
| Crypto | **CoinGecko** daily history | CoinGecko price | CoinGecko |

**Why NSE closes do not come from Angel One.** While this was being built, Angel's API host
refused connections for over an hour while its other hosts answered, and its forum shows the
same unexplained outages for years. The bhavcopy needs no login, matched Angel's closes to
the paisa, and its `FinInstrmId` column *is* Angel's instrument token — so Angel's 35 MB
instrument master is never parsed on a 1 GB server. Angel is asked only for what a broker
uniquely has: the price while the market is open. If NSE's file cannot be fetched for a day,
Angel's daily candles fill it.

**Angel One cannot trade from here.** `marketdata/angel_one.py` contains exactly three route
addresses — login, quote, candles — and a test asserts it names no others. SmartAPI's order,
holdings and GTT routes live on the same host; none of their addresses exist in this
codebase. The app's registered static IP (a SEBI rule from April 2026) gates orders only.

**History fills itself.** `feed.fill_closes` fills every missing day from a holding's first
trade to today, and every write is `ON CONFLICT DO NOTHING`, so a re-run writes nothing. The
first run on any database *is* the backfill. A holiday's 404 is not remembered anywhere: once
a later close exists, the gap is behind the starting point.

⚠ **CoinGecko's free plan returns 365 days.** Days older than that come from **Binance's
public market data** (`data-api.binance.vision`, keyless): the USDT close × that day's
USD/INR from Twelve Data, stamped like CoinGecko's. On 17 overlapping days the two agreed to
a median 0.1% (largest 0.7%), so the join is invisible. The value line and the TWR now start
at the first purchase, 17 Nov 2024. Real prices, never a line drawn between the purchase
price and the first known day: that would put an invented history under both figures.

Note what the market price shows for crypto: the INR paid on CoinSwitch was above the global
price (DOGE ~14%, ZIL ~4.5%), so the holding was worth less than it cost on the evening it was
bought. That is real — it is what the premium cost — and it is in both returns.

**Stamps.** A close is stamped when its market closed (15:30 IST, 16:00 New York) and a NAV
at 21:00 IST on its date, so each lands on the right calendar day for the value curve.
Angel's candles say `T00:00+05:30`; only the date is taken.

**Live prices are fetched only when stale.** The page draws from what is recorded, then calls
`POST /api/investments/prices/refresh` in the background and reloads if anything was written.
The assistant's `get_portfolio` calls the same `feed.refresh_stale`. A source that fails is
left alone for 10 minutes, so repeated opens do not each wait out its timeout.

| Job | When (IST) | Does |
|---|---|---|
| `prices_india_close` | 19:00 weekdays | NSE closes |
| `prices_daily` | 07:30 daily | US closes, USD/INR, fund NAVs, crypto |
| `corporate_actions_watch` | 20:00 weekdays | Announces a split, bonus or consolidation on a held stock, once |

⚠ NSE's corporate-action feed names **companies, not symbols**, and only covers ex-dates a
few days ahead. Matching is by normalised name prefix of at least 8 characters, so "HDFC
Bank" never claims "HDFC Life". A server down for several days running could miss an action;
the 25% move warning (§12) is the backstop.

Code: `backend/app/services/marketdata/` — one module per source, plus `feed.py`, the only
writer — and `backend/app/jobs/prices.py`.
