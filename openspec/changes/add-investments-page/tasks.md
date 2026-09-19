# Tasks — the Investments page

## 0. Verify the assumptions before writing production code

- [x] 0.1 **Measure the fold at page scale.** ✅ Summary is ~64 ms on the seeded book — inside
      the 150 ms budget, so the endpoint shape in design §2 stands. `xirr` dominates at 42 ms.
      ⚠ The curve found a real trap: re-folding the ledger per day costs **6,265 ms** over 659
      days against **3.3 ms** for the incremental walk — 1,887×, the difference between a chart
      and a timeout. Both recorded in `design.md` §3.
- [x] 0.2 **Prove the decimal boundary.** ✅ Pydantic v2 serialises a `Decimal` field to an
      exact quoted JSON string, trailing zeros intact — so response models stay typed `Decimal`
      and the wire form is a string for free. ⚠ But `jsonable_encoder`, the path taken by a
      route that returns a bare dict, turns `Decimal("0.86242900")` into `0.862429`. Rule
      adopted: **every route declares a response model.** `design.md` §1.
- [x] 0.3 **Confirm the curve degrades correctly with zero observations.** ✅ On the seeded
      book `latest()` returns 0 marks, all 11 positions report unpriced, `is_complete` is
      False, and nothing raises. The absent-value path is the one that will actually run.
- [x] 0.4 **Confirm suspicious-move detection with one observation.** ✅ A single price
      produces no flag and no error —
      `test_one_observation_produces_no_flag_and_no_error`.
- [x] 0.5 **Confirm the `formatINR` rename is two call sites.** ✅ `InsightsView.tsx:290` and
      `SettingsView.tsx:244`. Nothing else in `frontend/` or `scripts/` references it.
- [x] 0.6 **Check the seeded production book.** ✅ Narendra ran `seed_investments` on the VM on
      2026-09-07. The page renders the real book from its first paint, so the *populated* state
      is what ships — but the empty state is still built and checked, because a restore or a
      second book will meet it.

## 1. The value-over-time fold

- [x] 1.1 `services/investments/history.py` — `Point` (day, invested_inr, value_inr | None,
      priced_count, open_count) and `curve(db, portfolio_id, since=None, until=None)`.
- [x] 1.2 Walk incrementally: carry positions forward, apply each transaction once on its
      trade date. `O(days + transactions)`, never re-folding per day.
- [x] 1.3 Carry prices forward from the last observation on or before each day; convert
      non-INR through the same rule `pricing.value` uses.
- [x] 1.4 ⚠ `value_inr` is `None` unless **every** open holding is priced that day. Partial
      coverage produces no point — a stepped line reads as a portfolio move that never happened.
- [x] 1.5 `covered_range(points)` → the first and last day carrying a value, for the chart to
      state.
- [x] 1.6 `suspicious_moves(db, portfolio_id, threshold=0.25, max_gap_days=4)` — consecutive
      observations per instrument, flagged only when close enough together for a single
      session to explain the move.
- [x] 1.7 Tests — `test_investments_history.py`, **20 passing**. Everything listed, plus: a
      quarantined price is not used, a foreign holding with no rate on record stays unpriced
      rather than being valued at par, and a *recorded* SPLIT silences the warning (the flag is
      about **un**recorded actions, so this one is load-bearing).
- [x] 1.8 ⚠ **Fixed a test-isolation bug this uncovered.** `conftest._purge` never cleaned
      `fx_observations` — nothing had ever written one, so the gap was invisible rather than
      absent. A rate written by one test valued another test's portfolio. Scoped by a
      `pytest` prefix on `source`, since that table has neither a user nor an instrument to
      scope by.
- [x] 1.9 ⚠ **Migration 015** — widen `transactions_entry_source` to admit `FORM`. Found while
      writing §1's tests: a form entry is not `CHAT`, and writing it as one would falsify
      provenance on an append-only record. Purely additive; applied and verified locally.

## 2. The API

- [x] 2.1 `api/schemas.py` — investment response models. ⚠ Money fields are typed `Decimal`
      and every route declares its response model, per 0.2. A route returning a bare dict
      silently drops to float, so there is no stylistic latitude here.
- [x] 2.2 `GET /api/investments/summary` — positions, marks with age, totals (including the
      ring-fenced crypto figure and the unpriced/stale lists), and both returns with the
      reason when one is unavailable. **One fold.**
- [x] 2.3 `GET /api/investments/holdings/{symbol}` — lots, days-to-long-term per lot, FIFO and
      weighted-average bases both named, charges and prepaid tax separated, currency
      decomposition where the holding is not INR, and the instrument's price observations.
- [x] 2.4 `GET /api/investments/transactions` — full history newest first, each row carrying
      whether it is superseded and by what.
- [x] 2.5 `GET /api/investments/history` — the curve, the covered range, and the flags from 1.6.
- [x] 2.6 `POST /api/investments/transactions/draft` → `entry.prepare`. `POST .../transactions`
      → `entry.record`. ⚠ Two routes because they are two steps, and the second accepts only
      what the first produced.
- [x] 2.7 `POST /api/investments/transactions/{id}/reverse` → `entry.reverse`. No DELETE route
      exists at all — an endpoint whose name promises deletion on an append-only table is a
      lie in the OpenAPI schema.
- [x] 2.8 ⚠ **No route writes a price.** Cut with the price screen: the ledger change already
      established that an HTTP surface with no consumer is scaffolding, and Phase 1b's adapters
      call `pricing.record` directly as a service, never over HTTP.
- [x] 2.9 Register the router in `main.py`.
- [x] 2.10 Tests — `test_investments_api.py`, **26 passing**. Everything listed, plus: the
      confirm route ignores a `charges_inr` sent by the client, and **the OpenAPI schema is
      asserted to contain no DELETE/PUT/PATCH under `/api/investments`** — checking the
      published schema rather than one URL, so a route added later under a path this test
      never guessed cannot slip past.
- [x] 2.11 `services/investments/overview.py` — the one-fold assembly the routes read from,
      with **21 passing tests**. ⚠ Caught a real bug while writing them: the XIRR terminal
      built from `totals.market_value_inr + ring_fenced_inr` understates the book by crypto's
      entire cost basis, because that field excludes ring-fenced holdings and `ring_fenced_inr`
      is their *unrealised* gain rather than their value. Now summed from the valued positions,
      with a regression test.
- [x] 2.12 ⚠ **Corrected a misconception in the design.** `IfSoldNow` was built to show FIFO
      and weighted average disagreeing. On a **full** disposal they cannot: both relieve the
      entire cost basis. They diverge on a partial sale. The panel now reports the total once,
      says the two bases agree, and gives the long-term/short-term split — which is where lot
      identity actually changes what a sale costs.

## 3. Client and formatting

- [x] 3.1 `lib/format.ts` — rename `formatINR` → `approxINRFromUSD`, update both call sites,
      and comment why the name carries the unit.
- [x] 3.2 Add `formatRupees(value: string)` — Indian digit grouping, `₹1,23,456`; and
      `formatSignedPct(value: string)`. Both take strings and never do arithmetic.
- [x] 3.3 `lib/api.ts` — types and calls for every route in §2. Money typed as `string`, so a
      component that tries to add two figures fails to compile.

## 4. Chart primitives

- [x] 4.1 `ui/chart.tsx` — `Lines`: two or more series, **one** axis, hues fixed to the entity,
      legend plus direct end labels. ⚠ Not `StackedArea` — value already contains invested, so
      stacking them draws a total that means nothing.
- [x] 4.2 A series may contain gaps. A `null` breaks the path; it never bridges.
- [x] 4.3 `StackedBar` — one horizontal 100% bar, 2px surface gap between segments, per-segment
      label where it fits and a legend regardless.
- [x] 4.4 Hover: a date-anchored crosshair and tooltip on `Lines`, a per-segment tooltip on
      `StackedBar`. Touch targets larger than the marks.
- [x] 4.5 Both honour light and dark from theme tokens, and text wears text tokens rather than
      a series colour.

## 5. Summary

- [x] 5.1 `InvestmentsView.tsx` with loading, error-with-retry, and empty states — the empty
      state naming the seed command rather than saying "no data".
- [x] 5.2 The header figures: invested, current value, unrealised, realised — each with the
      figure the server computed, `tabular-nums`, sign shown by glyph as well as colour.
- [x] 5.3 ⚠ Crypto reported on its own line, not netted. The wording says why in one clause.
- [x] 5.4 Incompleteness beside the total: the holdings named rather than counted, at the
      same prominence as the figure.
- [x] 5.6 ⚠ **Caught myself breaking rule §1.** The per-asset-class subtotals and the
      excluded-cost figure were being summed **in the browser** — displayed money assembled
      by float arithmetic, immediately after the server took care to be exact. Moved to
      `overview._by_asset_class` and `Summary.unpriced_cost_inr`, with two tests. The only
      client-side sum left is a bar width, which is geometry.
- [x] 5.5 Returns: both when both exist; otherwise the available one labelled with what it
      measures and the missing one named with its reason.

## 6. Holdings

- [x] 6.1 The table above `md`: symbol and name, quantity, average cost, last price with age,
      value, unrealised (absolute and %), and a long-term chip. Real `<th scope>`.
- [x] 6.2 Sortable headers as buttons with `aria-sort`; sorting is client-side over the
      server's strings via a comparator that parses once, and never re-derives a displayed
      figure.
- [x] 6.3 Grouped by asset class, each group subtotalled.
- [x] 6.4 Cards below `md` — symbol, value, P/L, flags. ⚠ Not a horizontally scrolling table.
- [x] 6.5 Unpriced rows show no value and say so inline; stale rows show the age.
- [x] 6.6 The suspicious-move flag on the row, with the size and date of the move and what to
      check.
- [x] 6.7 The position sheet: lots with dates and unit costs, days to long-term per lot, FIFO
      **and** weighted average each named, charges and prepaid tax separated, currency
      decomposition on SPCX, the instrument's transactions, and its observed prices.

## 7. Allocation and value over time

- [x] 7.1 Allocation by asset class as one 100% `StackedBar`; by holding as a ranked bar list.
- [x] 7.2 ⚠ Unpriced holdings listed adjacent with their cost, not in a footnote — allocation
      is computed on market value and silently omits them otherwise.
- [x] 7.3 The curve: invested and value as `Lines`, with the covered range stated in the frame.
- [x] 7.4 ⚠ With no observations — which is what ships — the invested line alone, and a
      sentence naming the market feed as what fills the rest. **No action button**, because the
      action does not exist; inventing one to avoid a bare empty state would be worse.
- [x] 7.5 A range control (3M / 6M / 1Y / All) placed with the chart, not in the app header.

## 8. Entry, history and correction

- [x] 8.1 The entry form: instrument, action, quantity, price, date, and the fields a
      non-INR or crypto entry needs. Themed controls throughout — the shared `DatePicker` and
      `Select`, never a native one.
- [x] 8.2 Submit calls the draft route and shows what came back: charges, prepaid tax, net
      rupees, every warning, and whether it will create a new instrument.
- [x] 8.3 Confirm writes. Optimistic where it is safe, with rollback and a stated failure.
- [x] 8.4 The history list: newest first, superseded rows struck through and labelled with what
      superseded them.
- [x] 8.5 Correction from a history row → the reverse route. ⚠ The toast says "Reversed. The
      original entry stays in the record." Never "Deleted · Undo".
- [x] 8.6 The confirm is up front, because the correction is permanent the moment it is made.

## 9. Accessibility, keyboard and mobile

- [x] 9.1 Full keyboard pass: visible focus, order following layout, the sheet trapping and
      restoring focus.
- [x] 9.2 Screen-reader pass: table semantics, `aria-sort`, figures announced with their unit,
      the incompleteness statement in the same region as the total it qualifies.
- [x] 9.3 Gain and loss never carried by colour alone.
- [x] 9.4 Every touch target reachable without hover, at a size that can be hit.
- [x] 9.6 ⚠ **Two defects caught in review of my own code.** `SortHeader` was declared
      *inside* the view — a new component type on every render, so React remounts it and the
      button loses focus the instant it is pressed, breaking sort-by-keyboard silently. And
      its alignment class was interpolated (`text-${align}`), which Tailwind cannot extract,
      so it would have emitted no CSS at all. Both fixed, both commented.
- [x] 9.7 ⚠ **Decimal strings are compared numerically, never to `"0"`.** The server sends
      `"0.00"` after arithmetic, so `value !== "0"` is true for zero — which would have shown
      an empty crypto panel and a phantom "tax withheld" row.
- [ ] 9.5 ⚠ **Narendra's to check** — spacing, contrast and motion cannot be judged from
      source. The whole page at 360px, in light and dark.

## 10. Wiring

- [x] 10.1 `Sidebar` — a nav item with an icon not already in use, in an order that makes sense
      beside the others.
- [x] 10.2 `AppShell` — the view, its title and subtitle, and `investments` in the
      notification deep-link list, so a future job can point a push at it.
- [x] 10.3 Composer draft and view state across navigation. ⚠ **Found a failure and fixed
      it:** the view unmounts on a view switch, so a half-typed transaction was lost if you
      left the page to look something up — exactly what the interface standard forbids. The
      entry form now keeps its fields in `sessionStorage` while it has content, and clears
      them on record or cancel. Session, not local: an unfinished sentence should not still
      be waiting next week. Every access is wrapped, because a private window makes it throw
      on read as well as write.

## 11. Verification

- [x] 11.1 From `backend/`: `uv run ruff format .` and `uv run ruff check .` clean.
- [x] 11.2 `uv run pytest` — **755 passed, 5 skipped** (683 before this change began, 750
      after the ledger archive). The quarantined set is unchanged at 5.
- [x] 11.3 From `frontend/`: `npm run lint` and `npm run build` — ⚠ `build`, because
      `tsc --noEmit` checks nothing in this project.
- [x] 11.4 ⚠ `.env` untouched and unstaged — verified against `git status` and the staged
      file list.
- [x] 11.6 ⚠ **A methodology note worth keeping.** A 13-minute suite run was diagnosed as
      the battery; it was actually a *second* pytest run overlapping it on the shared dev
      database. Two runs produce dozens of fake failures AND a wildly inflated time. Alone,
      the suite is 3m41s.
- [x] 11.7 ⚠ **Closed a gap in the entry form.** `prepare` requires an exchange and asset
      class for an unknown symbol, so recording a *new* holding failed with an error the
      form gave no way to answer. It now reveals those fields when the server says the
      symbol is new — and a test pins the server wording the form matches on, so changing
      one without the other cannot pass silently.
- [ ] 11.5 **Compare against Groww on the real book.** Open the page beside the app and check
      holdings, quantities and invested line by line. ⚠ Value cannot be compared until the
      feed lands — that half of the acceptance test moves to Phase 1b, and this task records
      that it is owed rather than dropping it.

## 11b. What running it for the first time found

- [x] 11b.1 ⚠ **The headline said "Invested ₹0" against ₹1,03,924.93.** `BookTotals.invested_inr`
      accumulates only PRICED holdings and skips ring-fenced ones, so it stays comparable with
      market value — right for its job, catastrophic as a headline on a book with no prices.
      Added `Summary.cost_basis_inr` (every holding, crypto included), which is what a person
      means by "invested", with a regression test. **No test would have caught this; only
      looking at it did.**
- [x] 11b.2 ⚠ **The suite could not run against a database holding the real book.** Seeding
      the dev database — the only way to see the page with data — collided every fixture that
      uses a real symbol on `instruments_unique_live`, as ninety-odd unrelated errors.
      `conftest.make_instrument` now gets-or-creates, so fixtures share instrument rows with
      the real book. Positions fold per portfolio, so no assertion changes.
- [x] 11b.3 ⚠ **Second-order effect of that fix.** A shared instrument is no longer *orphaned*,
      so the purge stopped reaching its price observations and they collided on the primary
      key in a later, unrelated test. Prices written by a test now carry a `pytest` source and
      are purged by it — the same rule FX rates already followed. 34 call sites updated.
- [x] 11b.4 Verified end to end on the seeded book: Docker, migrations at 015, API on :8000,
      Vite on :5173, all 7 investment routes live, **756 passed** with the real portfolio
      present in the database.

## 11c. What Narendra found by using it

- [x] 11c.1 ⚠⚠ **All six assistant tools had never worked.** `tools.execute` passes
      `user_id: uuid.UUID`; `core/tools/investments.py` was written against a `User` and did
      `user.id`, so every one raised `AttributeError` on its first line and the user was told
      "the portfolio service failed" for every question about their own holdings. **This
      shipped in the ledger change and I reported the tools as working.** Fixed, and
      `test_investments_tools.py` (15 tests) now drives all six through `execute` — the
      existing tool tests only asserted the schemas registered, and a test that never invokes
      a handler cannot discover that no handler can run.
- [x] 11c.2 ⚠ **"Invested —" was a stale dev server, not a bug.** The running uvicorn had
      `by_asset_class` and `covered_days` but not `cost_basis_inr`; `--reload` had stopped
      picking up changes. The frontend asked for a field the backend no longer knew about.
      Confirmed against `/openapi.json` rather than guessed, and fixed by restarting.
- [x] 11c.3 **Prices were rendered raw.** Average cost showed
      `₹741.7469696969696969696969697` and lots showed `₹787.800000`. Added `formatPrice`,
      which adapts its scale (₹4,133.20 but ₹0.84 for Dogecoin) and trims meaningless zeros.
      Applied at all eight render sites.
- [x] 11c.4 **A holding-period date read as the purchase date.** "230 days to long-term ·
      Apr 27" — that Apr 27 is a *year later*, and `formatDay` omits the year. Added
      `formatDateFull`.
- [x] 11c.5 ⚠ **The sidebar scrolled away with the page.** Every other view wraps itself in
      `flex-1 overflow-y-auto`; this one did not, so its content grew the shell instead of
      scrolling inside it. The single structural thing this page got wrong against the
      others.
- [x] 11c.6 ⚠ **A production write path leaked into other tests.** `record_price` stores
      source `USER` — indistinguishable from a real price — so the tools test poisoned a
      shared instrument. Rule adopted and documented: **a test exercising a production write
      path uses data that cannot collide with the real book.** Verified: after a full run,
      **zero** leaked price or FX rows, with the real book still present.

## 12. Documentation

- [x] 12.1 `docs/INVESTMENTS.md` — §10 no longer says "No Investments page yet"; a section on
      what the page shows and the three honesty rules it enforces.
- [x] 12.2 `docs/ARCHITECTURE.md` — the new API surface and service module.
- [x] 12.3 `docs/ROADMAP.md` — the page moves from "not built" to built; Phase 1b becomes next,
      and carries the value half of the Groww comparison.
- [x] 12.4 `AGENTS.md` — "Not built yet" no longer names the Investments page.
- [x] 12.5 Learn cards — 74 → **77 explanations**: "A chart that refuses to guess", "Money
      travels as text", and "The loss that never happened". The reversing-entry card already
      existed from the ledger change, so a fourth would have restated it.
- [x] 12.6 **Docs and diagrams reflect what was built.**
