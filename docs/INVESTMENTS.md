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

## 12. Corporate actions

A split or bonus nobody recorded appears as a catastrophic loss in a position that has lost
nothing — the one failure mode of this module that produces a large, alarming, entirely
fictional number, and the one whose obvious reaction is to sell something that did nothing
wrong. A 1:1 bonus reads as −50%.

There are two guards, and they answer different questions.

### The feed, which knows

`corporate_actions_watch` reads NSE's own `Corporate_action.xml` every weekday evening and
records every share-changing announcement on a stock the book holds. Three properties matter:

- **The row is what remembers, not the notification.** A feed repeats itself nightly; a
  notification can be dismissed. A recorded action is announced once and stays outstanding
  until it is dealt with.
- **Nothing is guessed.** A ratio is read only from a form that cannot mean two things.
  `BONUS 1:1` is unambiguous, and so is `FACE VALUE SPLIT FROM RS.10/- TO RE.1/-`. A bare
  `SPLIT 1:10` is **not** — it does not say which side is the old face value, and the two
  readings differ by a factor of a hundred. Anything unreadable is stored as `NEEDS_REVIEW`,
  which flags the holding and waits for a person. ⚠ Refusing to answer is a supported
  outcome, and the larger fiction is always the confident wrong one.
- **On the ex-date it is applied**, as an ordinary append-only ledger entry with
  `entry_source='CORP_ACTION'`. Total cost basis is conserved and every lot keeps its own
  per-unit cost — a 1:1 bonus on lots bought at ₹960 and ₹722 gives ₹480 and ₹361, never
  ₹420 twice. Flattening them to the book average conserves the total and reports the wrong
  realised gain on every FIFO disposal afterwards.

While an action is outstanding the page flags the holding and says its profit and loss is not
yet reliable. That is gate **G7** of the build spec, and it is why the action is a stored row
rather than a message: a message can be closed while the number it was about stays on screen.

Applying is offered as a button and undone by the ordinary correction path. The ledger is the
user's word, so an entry made on their behalf has to be visible in the history and reversible
from it.

### The trip-wire, for what the feed missed

Independently, the page flags a holding when two observations **four calendar days or fewer
apart** differ by more than **25%**. Two restrictions keep it from becoming noise:

- **The gap limit.** Observations far apart differ for ordinary reasons. Comparing prices a
  month apart and calling it a single-day move would fire constantly — the same way a
  30-minute staleness limit overnight would mark the whole portfolio stale every evening.
- **A recorded action explains itself.** If a `SPLIT` or `BONUS` sits in the window, or an
  announcement is outstanding, the action *is* known and there is nothing to guess about.

⚠ **Known limitation, stated rather than hidden:** a 1:4 bonus moves the price about 20% and
will not trip this. The threshold sits where false positives are rare, because this is the
backstop and the feed is the fix.

---

## 12a. Foreign holdings and Schedule FA

Every Indian resident holding a foreign security declares it in Schedule FA, with **no
minimum threshold** — one fractional share of one US company is reportable, and the penalties
under the Black Money Act for omitting it are severe. Per security the return wants the
acquisition date, the initial value, the **peak value during the period**, the closing value,
and anything received.

Two things make that a problem for software rather than a spreadsheet:

- **The period is the calendar year**, 1 January to 31 December — not the financial year every
  other Indian tax figure uses, so these numbers appear nowhere else in this module.
- **The peak cannot be reconstructed afterwards.** It is the highest the holding was worth on
  any day, and knowing it requires having recorded what it was worth on every day.

The second stopped being true when the price feeds landed: a close is recorded for every US
holding on every trading day with a USD/INR rate beside it. So `schedulefa.report` is a walk
over stored observations, storing nothing new, and its **coverage is reported beside it** —
a peak over 40 observed days of a 365-day year is the peak of those 40 days, and a figure that
did not say so would claim more authority than it has.

⚠ **The rate is the one recorded, not SBI's TT buying rate**, which is what the return
requires and is not what a market feed quotes. Every figure names the day it came from so the
correct rate can be looked up for that day. Calling these filing-ready would be the more
convenient lie.

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
  corpactions.py splits and bonuses: read, recorded, applied on the ex-date
  reading.py     the source register, and every instrument every source named
  schedulefa.py  foreign holdings as the calendar-year return asks for them
  overview.py    the one-fold assembly the page and the API read from

backend/app/api/investments.py          summary · holding · transactions · history · entry
                                        corporate-actions · schedule-fa
backend/app/core/tools/investments.py   six tools, draft-then-confirm
backend/app/scripts/seed_investments.py the real portfolio
backend/alembic/versions/…014_investment_ledger.py
backend/alembic/versions/…015_form_entry_source.py
backend/alembic/versions/…017_corporate_actions.py
backend/alembic/versions/…023_sources_and_mentions.py

frontend/src/components/InvestmentsView.tsx   the page
frontend/src/components/PositionSheet.tsx     one holding, in full
frontend/src/components/TransactionEntry.tsx  entry and history
frontend/src/components/CorporateActions.tsx  announced splits, and applying them
frontend/src/components/ForeignHoldings.tsx   the Schedule FA figures
frontend/src/components/ReadingPanel.tsx     sources, what was said, and whether it was worth it
frontend/src/lib/investments.ts               display rules, in one place
```

Tests: `test_investments_ledger.py` (the fold, against Groww),
`test_investments_history.py` (the curve's absences, the corporate-action flag),
`test_investments_overview.py` (the assembly, and which return can be computed),
`test_investments_api.py` (exact money over the wire, ownership, no way to delete),
`test_investments_returns_and_costs.py` (XIRR against Groww, charges against the reference),
`test_investments_entry.py` (validation, correction, staleness),
`test_investments_seed.py` (the script),
`test_investments_corpactions.py` (what the feed says, what is refused, what is written),
`test_investments_schedulefa.py` (the peak, and how honestly its coverage is stated),
`test_investments_reading.py` (who was named, what the model may not add, what the guard refuses).

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

---

## 15. What it reads, and everything it heard named

The system reads two kinds of thing, and keeping them apart is the point.

**Tier 1 — filings.** NSE publishes five RSS feeds with no key and no login: announcements
(every Reg-30 disclosure), results, board meetings, shareholding patterns and insider
dealing. What a company tells the exchange *is* the filing, not a report of one, so these are
registered approved: the module already reads NSE's bhavcopy for the close of record and its
corporate-action feed for splits, and an announcement feed is the same record from the same
registrar.

**Tier 3 — commentary.** Channels are registered **unapproved** and read nothing until you
say so. Adding a source changes what the system can be talked into, which is a decision, not
a setting. And approving one widens what is *read*, never what is *acted on*: a suggestion
whose evidence is only tier 3 still fails its sourcing gate.

### Every instrument every source names

`mentions` records **every** company **every** source names — held or not, acted on or not,
dismissed or not.

⚠ **That clause is the entire reason the table exists.** Judge a channel on the ideas you
acted on and you are measuring your own filter rather than the channel: a source that named
forty companies, of which three were looked at and one worked, reads as **33% instead of
2.5%**. The skipped ideas are missing from the denominator, and they cannot be reconstructed
afterwards — which is why the row is written the moment the thing is said, long before anyone
knows whether it mattered.

### Who was named is code; which direction was meant is the model

Matching is deterministic, so the denominator never depends on a model remembering a company.
The model is then allowed to read a *direction* onto the names the matcher already found —
and **never to add one**. A model that could introduce names would be inventing the very
mentions the attribution measure counts, and an invented mention is indistinguishable from a
real one once written.

A stance is asked of commentary only. An exchange announcement reports that something
happened and takes no side; reading a bull case into "board meeting intimation" would put
noise straight into the numbers.

Matching a name is fussier than it looks. Stripping corporate words wherever they appear
turned *Apar Industries Limited* into `apar` — four characters, under the safety floor — so
only the **trailing** legal form is stripped and "Industries" stays part of the name. Tickers
match case-sensitively, because lower-cased, half the symbols on the exchange are ordinary
English words: `APARINDS` is a mention, "the aparinds of the matter" is not. Measured against
56 live announcements on 20 Sep 2026: zero false positives.

### What the sources actually publish

Measured rather than assumed, on 20 Sep 2026, over each channel's last fifteen uploads:

| Source | Uploads | Named a tracked company |
|---|---|---|
| Aswath Damodaran | 15 | **0** — valuation method, US examples |
| Yadnya Investment Academy | 15 | **0** — macro and personal finance |
| Zerodha | 15 | **0** — IPO explainers, product videos |
| Capitalmind | 2, from 2006 | not the investing firm; their work is a newsletter |

⚠ So the honest position is that the machinery is correct and the commentary yield is near
zero **for these eleven companies**. That is a finding about the sources, not a fault in the
design — and it is exactly what a mention register is for, because without one "the channels
aren't naming my stocks" would be a feeling rather than a count.

⚠ **A known limit, stated rather than hidden.** The matcher only knows companies that are
already tracked, so commentary can tell you something new about what you own — it cannot
*discover* a company you have never heard of. Idea discovery would need a universe of every
listed name, and instruments here are created by recording a holding, never separately.

### What the database refuses

`mentions` is append-only in its **utterance** — instrument, stance, words — and mutable in
what came of it. Writing it as a whole-table guard would have made `became_proposal_id`
unsettable and the column decoration; that is the fourth time this trigger has caught its own
author (`agent_runs`, `proposals.status`, `claims`, and now this). DELETE is refused outright:
a mention that can be removed after the fact is one that never has to be counted.

`sources` is switched off, never deleted. A removed source would orphan every mention that
cited it and quietly rewrite the attribution history along with it.

### Was a source worth reading

A BULL call is a hit if the price rose over the next quarter; a BEAR call is a hit if it fell.
NEUTRAL and MENTION_ONLY make no claim — counted, never scored. The hit rate is **withheld
below 20 settled calls**, like every other measure here, because a figure over six reads
exactly like one over six hundred and nothing on a page can tell the reader which they are
seeing unless it refuses. A call whose horizon has not arrived, or whose price series does not
reach it, is *pending* rather than wrong.

### Two things the live feeds taught

⚠ **A block page is valid XML.** NSE answers a refused client with HTML, which parses cleanly
and yields no items — so the adapter checks the root element. Without that, "we are blocked"
and "the exchange announced nothing today" are the same reading.

⚠ **One document is announced more than once.** The results feed returned four entries and
two links on 21 Sep 2026: the same XBRL file, a second apart, once as `RELATING TO:Annual` and
once as `RELATING TO:Fourth Quarter`. They are two readings of one filing, so the document is
the unit and the bodies are *merged* — the excerpt is the evidence, and dropping one would
throw away half of what the exchange said. A poller that assumed the feed was a set would also
collide with its own insert and lose the whole round to a rollback.

Code: `backend/app/services/investments/reading.py`, `backend/app/services/marketdata/feeds.py`,
`backend/app/jobs/reading.py`, `backend/app/scripts/seed_sources.py`,
`frontend/src/components/ReadingPanel.tsx`. Migration 023.

---

## 16. Discovery: saying "look at this", not only "hold or sell"

A system that only recognises companies you already own can say hold, trim or sell and nothing
else. A research analyst that can only comment on what you already own is a bookkeeper with
opinions — so the reader's vocabulary is **the exchange's own equity list**: 2,595 companies,
symbol and legal name, no key, refreshed weekly.

⚠ **Why not just ask a model which companies were discussed.** A model that can produce names
can produce ones that do not exist, and a fictional company written into `mentions` is
indistinguishable from a real one — in the very table the source-attribution measure counts.
With the exchange's list as the vocabulary, recognising a company never heard of is exactly as
deterministic as recognising one already held.

Eleven regexes were fine; 2,595 would be the slowest thing in the module. Names are **looked
up** instead: the text is tokenised once and its word-runs checked against a dictionary, which
costs the length of the text rather than the size of the vocabulary. 330 live feed items
against the full list in 1.5 seconds.

### Four things the real data taught

| What | Why it mattered |
|---|---|
| The exchange lists TARIL as *Transformers **And** Rectifiers*; everyone writes *Transformers **&** Rectifiers* | Tokenised literally the two never meet, and the company is invisible — silently, because a name that fails to match looks exactly like one never said |
| The instrument is *Kaynes Technology*; the exchange says *Kaynes Technology India Limited* | Longest-match-wins picks the listed spelling, so without resolving back to the holding, a filing about something you own would open a research line for it |
| One poll of five NSE feeds named **184** companies, 21 of them one asset manager's routine ETF notices | A company filing its own paperwork is not recommending itself |
| The exchange carries 165 symbols of 3 characters or fewer and 214 one-word names — ACE, ETERNAL, AMAL are real companies *and* ordinary English | A missed mention costs an idea; a false one corrupts the denominator, and nothing downstream can tell it from a real one |

So **filings open no research lines and record no mentions of companies nobody follows.** The
mention table exists to judge sources that make calls, and the exchange makes none. Filings
about companies already followed are recorded in full — that is news about your own book.

And discovery gets a **higher symbol floor and an explicit ambiguity list**, while a ticker you
already follow keeps the lower one, because that one you chose.

### The research queue

A company something named, that you neither hold nor watch.

⚠ **A candidate is deliberately not priced.** Pricing every name ever mentioned would spend the
API allowance and the disk budget on companies nobody has decided to care about. It has an
identity so it can be referenced and counted; **promotion is what starts the meter.**

⚠ **Dismissal demands a reason**, enforced by a database CHECK rather than by politeness. It is
the only record of what kinds of idea keep being refused, and a queue that could be cleared
silently would discard that every time it was tidied. A dismissed candidate is **not** silently
reopened by being named again — a channel repeating itself is the most ordinary thing a channel
does — though its count still moves, so a review can see it is being pushed.

### The inbox

Drop a link, a video, or just what a friend said — on the page in one always-visible line, or
in chat (*"my friend says Voltamp looks good"*). It is read, the listed companies in it are
recognised the same deterministic way, and anything not already followed opens a queue line.

**You become a measured source.** What you drop is filed with mentions behind it, so in six
months the scorecard can answer whether the tips you act on beat the exchange feed you ignore.
Your official drops and your tips register separately: a page from SEBI and a remark over chai
are different species, and averaging them would make both unreadable.

⚠ **The listing-page problem, measured.** A live Economic Times "stocks in news" page names
**32** companies. Queueing those would bury the handful anyone argued for under a page of
navigation, so a drop naming more than twelve is refused as a listing page and says so —
including its mentions, because a nav bar makes no claims.

Every unhappy path says what happened. A page that came back nearly empty is reported as
needing a browser, because *"nothing was read"* and *"nobody was named"* are different outcomes.
A PDF is refused outright rather than tag-stripped: stripping a binary produces plausible
nonsense, and plausible nonsense in a research note is worse than an honest refusal.

---

## 17. From a name to a decision

A candidate goes through the same four steps every holding does, with the same code.

**1 · Where does it sit?** The model reads what sources said and names a bottleneck.

⚠ **This is the one thing a model decides, and it is allowed to because it is not a number.**
Which chokepoint a business solves is a judgement about what the business *is*. Every figure
that follows — how many imperatives that bottleneck crosses, whether it is crisis-accelerated,
what multiple is defensible, the quality score itself — is computed from the framework and from
filed accounts.

⚠ **It chooses from a closed list of 31 ids and the answer is matched back against it.**
Anything unrecognised becomes *no mapping*, which scores zero rather than guessing.
`NONE` is a first-class and common answer — most listed companies are ordinary businesses this
framework is not about, and forcing a fit is how a random small-cap becomes strategic.

⚠ **And the placement is a proposal.** It scores zero until you agree, with no exception for a
claim that arrived with a confident tone.

**2 · What does it report?** Its annual filings, read and stored beside the words they came
from. **3 · Is it good, and sensibly priced?** From those figures alone. **4 · What stops it?**
The gates, unchanged.

⚠ **No shortcuts for a candidate.** Scoring a company nobody owns more loosely — fewer years, a
guessed sector, a default multiple — would make a new idea look better than an existing holding
purely because less was known about it.

### Verified end to end, on real companies

| Company | Placement | Filings | Quality | Price |
|---|---|---|---|---|
| Voltamp Transformers | B1.1 Power Transmission, 95% | 4 read | **4 of 7 scorable** | ₹10,879 |
| Transformers & Rectifiers | B1.1 Power Transmission, 100% | — | — | — |
| Nestle India | **refused** — "does not address any of the bottlenecks" | — | — | — |

Analysis and following are separate acts, and the split is a spending decision: analysing reads
filings once and fetches one price; following joins the daily price loop for as long as the
company is kept.

---

## 18. When a condition you wrote comes true

A fired invalidation condition used to raise a notification and stop, which left the acting
entirely to whoever happened to read it. **Trigger discipline is the one go/no-go criterion
that is not statistical** — ignore your own conditions even a few times and this never gets
real money whatever the returns say — and a design that only alerts is one where that erodes
without anyone deciding to let it.

So a firing now forms a suggestion, through the same gates and into the same books, because a
proposal raised in a hurry should be held to the rules hardest. One suggestion per company: one
contradiction asks to **reduce**, two asks to **leave**.

⚠ **Never a purchase.** A condition firing is the thesis being contradicted, and a design that
let that produce "add more" would have invented averaging down as a policy.

⚠ **A flaw this exposed.** The confidence gate was action-blind, so low confidence in a company
blocked the suggestion to *leave* it — the less the system understood a holding, the harder it
became to get out of. Confidence is a reason to commit money; its absence is a reason to stop,
never a reason to stay. That gate now applies to buying only.

---

## 19. Looking backwards

Saturdays, month end, quarter end. Sunday is deliberately empty: there is a real risk a system
like this fills every slot with output, and output is not insight.

⚠ **Assembled by code, never written by a model.** Everywhere else here a model is forbidden
from producing a number, and a review is almost entirely numbers. A summary paragraph would be
the single place a figure could be restated wrongly with nothing to check it against.

⚠ **APPEND-ONLY.** A review states what was true at a moment. Regenerating March's in June
would show a position that recovered as never having fallen, and a prediction that failed as
never having been made — and the most interesting thing a review holds is the part that turned
out to be wrong.

What it refuses to soften:

- **Every measure withholds itself below its sample**, in a full sentence rather than a blank.
  A blank reads as zero to anyone scanning; *"0 of 20 resolved claims needed before this means
  anything"* cannot.
- **A queue nobody cleared is named, not counted.** "Three have been waiting a month" prompts
  nothing; naming them turns a statistic into a decision.
- **Unspent budget is reported without apology.** The budget is a ceiling, not a target, and
  framing it as a shortfall would be arguing for activity — the one bias this design is built
  against.
- **The headline leads with what needs doing**, not with the week's return. A review whose
  first line is a number invites reading only that number.
- **Source attribution is monthly and up.** Over seven days it is noise wearing a number.

Code: `services/investments/{reading,candidates,deduce,reviews}.py`,
`services/marketdata/{universe,webpage}.py`, `jobs/{reading,reviews}.py`.
Migrations 024 and 025.
