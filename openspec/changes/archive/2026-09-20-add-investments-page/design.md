# Design — the Investments page

The ledger already decided the hard things. What is left is a set of presentation decisions
that are easy to get quietly wrong, because every one of them has a version that looks fine
and is a lie.

---

## 1. Money must not become a float

**Decision: every displayed figure is computed in `Decimal` on the server and crosses the wire
as a string. The client parses to `number` only for chart geometry — pixel positions — and
never for anything a person reads.**

This includes percentages and returns. It is tempting to send `unrealised_pct: 0.0734` and
format it in the browser, but the moment the client divides, it has done money arithmetic in
binary floating point, and the answer it prints is not the answer the tests proved.

**Measured, task 0.2.** Pydantic v2 already does the right thing: a `Decimal` field on a
response model serialises to a **quoted JSON string**, exact, trailing zeros intact. So the
models are typed `Decimal` and the wire form is a string for free — no custom serialiser.

⚠ **But there is a second path, and it is the default one.** A route that returns a bare
`dict` instead of a declared response model goes through `jsonable_encoder`, which maps
`Decimal` → `float`:

```
Decimal("0.86242900")  ->  0.862429      # SPCX units, 8dp become 6dp
```

The value is not wrong; the *scale* is gone, and once it is a JS `number` the client can no
longer format it faithfully or add it to anything without doing float arithmetic. Hence the
rule for this change: **every investments route declares a response model.** There is no
stylistic latitude in that.

Rejected:

- **Numbers with client-side formatting.** The normal approach, and wrong here for the reason
  above. It also splits rounding across two languages: `Decimal.quantize` and
  `toFixed` disagree at exact halves, so the same figure could differ between the page and the
  assistant's answer to the same question.
- **A JSON decimal encoding (`{"v": "1234.56", "scale": 2}`).** More faithful and more
  ceremony than this earns. A string is already exact, and the only operation the client
  performs on it is display.

⚠ The consequence to hold on to: **the frontend has no money type and needs none.** If a
component finds itself adding two figures, the addition belongs on the server.

---

## 2. One endpoint for the summary, separate ones for the rest

**Decision: `GET /api/investments/summary` returns positions, marks, totals and both returns
together. Transactions, the value curve, price recording and entry are their own routes.**

The four things in the summary are not four queries — they are one walk over the ledger. The
fold produces positions; valuation marks them; totals aggregates the marks; the return
calculation reads cash flows from the same transactions. Splitting them into four endpoints
would run the walk four times to paint one screen, and the four answers could then disagree if
a write landed between them.

The rest are separate because their lifetimes differ. Recording today's prices should refresh
the summary, not the 200-day curve. Opening the history should not recompute XIRR.

Rejected:

- **One `GET /api/investments/overview` returning everything.** Recording a single price would
  refetch the transaction history and the whole curve.
- **A resource endpoint per service module** (`/positions`, `/marks`, `/totals`, `/returns`).
  Tidy on paper, and it makes the client responsible for stitching together four views of one
  moment — the exact inconsistency the fold exists to prevent.

---

## 3. The value curve on a portfolio with no price history

This is the hardest honest problem on the page. Value over time needs a price per holding per
day, and until Phase 1b there are only the prices Narendra types.

**Decision: two lines from two folds.**

| Line | Source | Density |
|---|---|---|
| **Invested** | transactions alone | exact, every day, from the first trade |
| **Value** | price observations, carried forward from the last on or before that day | only on days where **every** open holding has one |

And the chart states the range the value line covers, rather than drawing it faintly and
hoping the reader infers something.

The strictness is the point. If value were drawn from whatever prices happened to exist, the
line would step every time coverage changed — and a reader would see a portfolio move that
never happened. It is the same rule `BookTotals.is_complete` already applies to the total,
extended through time.

⚠ **On day one the value line is absent, and it stays absent until the feed lands.** That is a
correct answer, not a broken chart: no price has been observed, so nothing is known about what
the book was worth. The invested line still draws, and it is genuinely informative — it is the
record of money going in.

A hand-entry screen for prices was designed and then **cut on Narendra's instruction** once
Phase 1b moved to the same week: it would have been obsolete before it was reviewed. So the
empty state names the market feed as what fills the chart, rather than offering an action that
will not exist. This is the rare case where the honest empty state is *"nothing here yet, and
here is what will change that"* with no button under it — and inventing a button to avoid that
would be worse.

Rejected:

- **Interpolating between observations.** Invents data, and invented data on a chart is
  indistinguishable from measured data. Categorically out.
- **Drawing value from partial coverage.** Produces phantom moves. Considered longest, because
  it makes the chart look better immediately — which is exactly why it is dangerous.
- **Deferring the curve to Phase 1b.** Tempting: the value line is the interesting one. But
  the invested line is exact today, the fold is the piece that takes design, and building it
  now means Phase 1b adds density rather than a feature.
- **Recording each transaction's trade price as a price observation.** Attractive — a trade
  price *is* a market observation — and rejected because `pricing.latest()` would then pick a
  seven-month-old trade price as the current mark for a holding never priced since. That
  changes valuation semantics proven in the ledger change, replacing an honest "unpriced" with
  a stale figure. If this is ever revisited it needs its own source value and exclusion from
  `latest()`, which is a ledger change, not a page change.

**Cost — measured, task 0.1.** 27 transactions, 11 positions, 659 days of history:

| | |
|---|---:|
| Naive: re-fold the whole ledger for every day | **6,265 ms** |
| Incremental: carry positions forward, apply each transaction once | **3.3 ms** |

⚠ **1,887×.** This is not a micro-optimisation, it is the difference between a chart and a
timeout, and the naive version is the one you write without thinking about it. The walk is
`O(days + transactions)`, and stays so as history grows.

---

## 4. When only one return can be computed

The spec requires both measures to appear together, each labelled. But TWR needs valuations at
sub-period boundaries, which need price history — so on a book with no observations, XIRR is
computable and TWR is not.

**Decision: show the one that exists, labelled with what it measures, and name the missing one
and its reason in the same breath. Never label a single figure "return".**

The requirement exists so that a number is never credited to the wrong thing. Silently showing
XIRR alone is precisely the failure it guards against; showing XIRR as *"your timing"* beside
*"strategy return needs price history"* honours it. The spec is amended to say so, because a
rule that has to be quietly bent is a rule that was under-specified.

Rejected:

- **Showing neither until both exist.** Withholds a correct, computable figure to satisfy the
  letter of a rule whose purpose is served by labelling.
- **Approximating TWR from trade prices.** A made-up sub-period boundary produces a real-looking
  number nobody can check.

---

## 5. Correction, on a record that cannot be edited

The interface convention is optimistic mutation with an Undo toast over a soft delete. The
ledger has no soft delete and no update.

**Decision: undo inserts the reversing zero-quantity `ADJUSTMENT` (`entry.reverse`), and the
toast says what actually happened — "Reversed. The original entry stays in the record."
Superseded rows remain in the history, struck through and labelled with what superseded them.**

Two consequences worth being deliberate about:

1. **The gesture is not undo, so it must not be worded as undo.** "Deleted · Undo" would tell
   the user something false about their own ledger — the one record in the system whose value
   depends on it being unrewritable.
2. **There is no window.** The correction is permanent the moment it is made, and correcting
   the correction is another entry. So the confirm is up front, not a five-second grace period.

Rejected:

- **Hiding superseded rows.** Makes the history look tidier and destroys the property the
  append-only design was for: seeing what you believed at the time.
- **An edit form that writes a reversal plus a replacement.** Two rows, one gesture, and a
  history that reads as though the position was sold and rebought. `entry.reverse` already
  rejected this reasoning once; the page does not get to re-adopt it.

---

## 6. Allocation: not a pie

**Decision: one horizontal 100% stacked bar for asset class, and a ranked horizontal bar list
for individual holdings. Unpriced holdings are listed beside it as excluded, with their cost.**

A pie invites comparing adjacent slices, which people do badly, and it asserts that what it
shows is the whole. Here it demonstrably is not: any unpriced holding is missing from the
denominator, so a pie would silently redistribute its weight across everything else.

Rejected:

- **A pie or donut.** The above, plus the label collisions that arrive with eleven holdings.
- **A treemap.** Better at part-to-whole than a pie and worse at ranking, which is the actual
  question ("what am I most exposed to?").

⚠ Allocation is computed on **market value where priced**, and the unpriced list is rendered
next to it rather than in a footnote — a caveat below the fold is a caveat nobody reads.

---

## 7. Two chart primitives, still no library

`ui/chart.tsx` has `StackedArea`, `Bars`, `Sparkline`, `Legend`. Neither thing this page needs
is among them:

- **`Lines`** — two or more series on **one** axis. Not `StackedArea`: invested and value are
  not additive — value already contains invested — so stacking them would draw a total that
  means nothing.
- **`StackedBar`** — a single horizontal 100% bar with a 2px surface gap between segments.

Both follow the rules already written at the top of that file: hues assigned in fixed order and
attached to the entity, a legend whenever there are two or more series plus direct labels, one
axis ever, recessive grid, text in text tokens. Both get the hover layer — a crosshair with a
date-anchored tooltip on `Lines`, a per-segment tooltip on `StackedBar`.

Rejected: **adding Recharts.** Argued in the proposal. The honest summary is that this page
needs two more shapes, not a rendering engine.

---

## 8. `formatINR` is a trap and gets renamed

```ts
export function formatINR(usd: number): string   // multiplies by 88
```

It converts **dollars** to approximate rupees for model-cost display. On a page full of real
rupee figures, calling it on a rupee amount would render ₹89,015 as ₹78,33,320 — a plausible
number, wrong by 88×, that nobody would question.

**Decision: rename it `approxINRFromUSD`, and add `formatRupees(inr: string)` for actual
rupees with Indian digit grouping (`₹1,23,456`).** Two call sites, both in views this change
does not otherwise touch.

Rejected: **leaving it and naming the new one something else.** The collision is not in the
names, it is in the argument — both take a bare number and only one is rupees. Renaming makes
the unit part of the call.

---

## 9. Eleven columns do not fit a phone

**Decision: the holdings table is a real `<table>` above `md`, and a list of cards below it —
symbol, value, P/L, and the flags that matter — each opening the same detail sheet.**

Rejected: **a horizontally scrolling table on mobile.** It hides the columns that matter behind
a gesture nobody performs, on the device this app is installed on.

The detail sheet is the same component either way, which is where the columns that do not fit
actually live: lots with dates and unit costs, days to long-term per lot, FIFO **and** weighted
average both named, charges and prepaid tax separated, currency decomposition on SPCX, the
instrument's transactions, and its price observations.

---

## 10. The suspicious-move flag

**Decision: flag a holding when two consecutive price observations four calendar days or fewer
apart differ by more than 25%.**

The gap limit is the part that is easy to leave out. Comparing observations a month apart and
calling a 30% difference "a single-day move" would fire constantly on typed prices, and a
warning that fires constantly is a warning that gets ignored — the same failure the 20-hour
after-close staleness limit exists to avoid. Four days covers a weekend plus a holiday.

⚠ **Known limitation, stated rather than hidden:** a 1:4 bonus moves the price about 20% and
will not trip this. The threshold is set where a false positive is rare, because the real fix
is the corporate-action feed in Phase 1b, not a lower number here.

---

## 11. What the page does *not* get to decide

Everything the ledger settled stays settled, and the page renders it rather than re-deriving
it: staleness limits, ring-fencing, the amount-versus-quantity rule, FIFO alongside weighted
average, prepaid tax excluded from charges, unpriced reported as unpriced. If a figure on the
page disagrees with the assistant's answer to the same question, the page is wrong, because
they call the same functions and only one of them is allowed to have arithmetic in it.
