# Tasks — the investment ledger

## 0. Establish the arithmetic before writing any code

The success condition of this whole change is that it reproduces figures somebody else
already computed. Those figures must be written down **first**, by hand, or the tests will be
written to match whatever the code happens to produce.

- [x] 0.1 **Done — `seed-reconciliation.md`.** Record the reconciled seed in this folder as the fixture every later test asserts
      against: **15 Groww transactions** summing to ₹62,527.85 against Groww's stated
      ₹62,527.96 (11 paise, rounding); mutual fund units summing **exactly** to redeemable
      units (6.804 and 45.342); **3 SPCX buys** summing exactly to $155.31 and 0.862429 units
- [x] 0.2 **Done.** ⚠ **Record the excluded order and why.** The Kaynes list contains a BUY of 1 at
      ₹3,080 on 18 May 2026 that did not execute. Including it gives 6 shares / ₹19,974;
      excluding it gives exactly the 5 shares / ₹16,894.00 Groww reports. This is the
      reconciliation check working on real data before any code exists, and it belongs in the
      record as the worked example of why the check is there
- [x] 0.3 **Done, and it produced a result worth more than the task asked for.** Groww's XIRR was not merely reproduced, it was *solved for the convention*: valuation date 2026-09-06, terminal = **units × NAV** rather than the rounded card figure, actual/365. Mid Cap lands **exactly on 12.25%**; Flexi Cap gives 6.49% against 6.48%, with the 0.01pp explained by the displayed NAV being rounded to 3dp. Newton–Raphson and bisection agree, so the fallback is verified rather than merely present. Sensitivity recorded (~0.04–0.07pp per day of valuation date), so the test must take the date as an input rather than hardcoding it. Original wording: **Compute the expected outputs by hand and commit them**, before implementation:
      per-holding quantity and cost basis, portfolio totals per asset class, and the two XIRR
      figures Groww publishes — **HDFC Flexi Cap 6.48%** and **HDFC Mid Cap 12.25%**. These are
      arithmetic somebody else did, which makes them a far stronger test than any synthetic case
- [x] 0.4 **Done — `docs/investments-transaction-costs.md`, verified 2026-09-06.** ⚠ **The
      spec's assumption was wrong and it matters**: Groww delivery brokerage is **not** zero,
      it is `min(₹20, 0.1%)` floored at ₹5, **on both legs** — that was Zerodha's ₹0 being
      generalised. DP charge is **₹23.60** including GST, not ₹15.34. GST applies to the full
      DP charge, not just Groww's markup. Exit load **1% within a year on both HDFC funds**,
      and both his purchases are inside that window. Crypto TDS and LRS TCS are **prepaid tax,
      not expense** — modelling them as cost would double-count against the flat 30%. FX markup
      sits on the **remittance**, not per trade. **Five items remain unverifiable from public
      sources** and need one contract note each; they are listed in §F of that document.
      Measured consequence: a ₹13,422 → ₹15,000 round trip costs **₹88.64, a 0.66% break-even**
      and 5.6% of the gain. Original wording: **Verify the charge rates against a current
      source** and record the date checked.
      They are broker- and date-dependent, they will be wrong eventually, and a wrong rate
      quietly biases every return. Note that Narendra's Groww trades are delivery, so brokerage
      is 0 and the modelled cost is taxes and fees only
- [x] 0.5 **Decided 2026-09-06**: **30 min** during Indian market hours, **20 h** after close,
      **48 h** for mutual fund NAV, **4 h** for crypto. The after-close figure looks like the
      loosest and is the most correct — a closing price *is* the current price until the next
      open, and flagging it at 30 min overnight would mark the whole portfolio stale every
      evening, which is how a staleness signal becomes noise and stops being read. Original
      wording: **Decide and record the staleness limits per asset class** before they are needed —
      market hours, after close, mutual fund NAV, crypto. They must be a stated policy, not a
      number discovered while debugging
- [x] 0.6 Baseline: **598 passed, 5 skipped** (the 5 are the quarantined memory tests)

## 1. Schema

- [x] 1.1 **Done.** Migration 014: `instruments`, `portfolios`, `transactions`, `price_observations`,
      `fx_observations`, `charge_schedules`. `Numeric` throughout, never float; `Text` + CHECK
      rather than Postgres enums; all timestamps `timestamptz`
- [x] 1.2 **Done** — verified in the database, a 5-share buy stores as `5.00000000`. `quantity Numeric(28,8)` and `price Numeric(20,6)` — 8 decimals so 0.00001978 BTC and
      0.862429 SPCX units are exact, 6 so a ₹0.0025 NAV and a $204.70 share both fit. A
      column that rounds a real holding is a column that lies on every read
- [x] 1.3 **Done — trigger written, manually verified, and now tested.** Confirmed against the live database with savepoints: INSERT succeeds, UPDATE and DELETE each raise *"the transactions ledger is append-only: correct with a reversing entry carrying supersedes_id"*, and the row survives unchanged. One shared plpgsql function guards all three tables. ⚠ **The append-only trigger.** A Postgres rule or trigger raising on UPDATE and
      DELETE for `transactions`, `price_observations`, `fx_observations` — plus a test that
      *asserts the trigger actually fires*. A trigger nobody tests is a comment
- [x] 1.4 **Done** — `portfolio.live()`, mirroring `services.memory.live`. `supersedes_id` self-reference on `transactions`, and a `live` helper resolving to
      entries not superseded — one definition, as `services/memory.live` already does
- [x] 1.5 **Done** — 15 tables and 0 trigger functions after downgrade, 21 tables and 3 triggers after re-upgrade, so the shared function is dropped and recreated correctly by both directions. Verify up → down → up with rows present, and that the trigger is dropped and
      recreated correctly by both directions
- [x] 1.6 **Done.** Models in `db/models.py` with docstrings recording *why* append-only departs from the
      project's soft-delete convention

## 2. The fold

- [x] 2.1 **Done, and it reproduces Groww.** `services/investments/portfolio.py` — `positions()` folds transactions into quantity,
      cost basis and realised P&L. Pure function of the ledger, no stored state
- [x] 2.2 **Done** — bonus/split conserve total cost basis, asserted. Handles every `txn_type` the ledger permits, including `SPLIT` and `BONUS`, which
      change quantity and per-unit cost while **conserving total cost basis**. Assert that
      invariant in a test — it is the property a corporate action must never violate
- [x] 2.3 **Done** — both rows survive in the table; only the fold ignores the retired one. A superseded transaction is invisible to the fold, and its reversal restores the
      earlier position exactly
- [x] 2.4 **Done — sub-millisecond on 27 real transactions**, so the no-cache decision holds. Measure the fold on the real seed and record it. If it is not comfortably
      sub-millisecond, the "no cache" decision needs revisiting rather than defending

## 3. Lots, holding periods and charges

- [x] 3.1 **Done.** `taxrules.py` — FIFO lot matching for disposals, and weighted average alongside it,
      each returned under a name that says which it is
- [x] 3.2 **Done** — and month arithmetic clamps, so 29 Feb + 12m is 28 Feb rather than 1 Mar. Per-asset-class holding-period rules: **12 months** Indian equity and equity MF,
      **24 months** US equity, **none** for crypto. Not a shared default with exceptions —
      three explicit rules, because the US one is the one that gets silently wrong
- [x] 3.3 **Done.** `days_to_long_term()` on any holding, so a disposal can be told how close the cliff is
- [x] 3.4 **Done** — `BookTotals.ring_fenced_inr`, asserted never to reduce anything else. Crypto losses are reported separately and **never netted** against gains elsewhere.
      Assert with the real seed: −₹1,076 across DOGE, ZIL and JASMY must not reduce the ₹1,386
      Indian equity gain, and the ₹6.01 Bitcoin gain must remain visible as a gain
- [x] 3.5 **Done — all six published worked examples reproduced to the paisa.** `costmodel.py` — charges from `charge_schedules` by effective date, with the schedule
      id frozen onto the transaction. Test that changing a rate does not alter an old
      transaction's recorded charges
- [x] 3.6 **Done** — `prepaid_tax_inr` is a separate column and excluded from `Charges.total`. ⚠ **Prepaid tax is not a cost.** Crypto TDS (1%, s.194S) and LRS TCS (20% above
      ₹10 L/FY) are withheld against a future liability and are creditable or refundable.
      Modelling them as expenses would understate returns *and* double-count against the flat
      30% VDA rate. They are recorded as cash-flow items, visible, and excluded from the cost
      of a transaction. Assert both in a test
- [x] 3.7 **Done.** **Exit load reuses the FIFO lot matcher from 3.1** rather than getting a second one.
      1% on units redeemed within a year of *their own* allotment — which is per lot, which is
      exactly what 3.1 already computes. Both HDFC funds are inside that window today
- [x] 3.8 **Done** — CDSL's charge modelled, Groww's markup flagged unverified rather than guessed. ⚠ **Mutual funds held in demat incur a DP charge on redemption**; SOA-held units do
      not. Narendra's are demat (folio 40754072). Whether Groww's ₹16.50 markup applies to MF
      debits is unverified — model the CDSL ₹3.25 as certain and flag the markup as unknown
      rather than assuming either way

## 4. Returns

- [x] 4.1 **Done**, pure Decimal including a fractional power through the natural log. `returns.py` — XIRR by Newton–Raphson (r₀ = 0.10, 100 iterations, tol 1e-7) with
      bisection over [-0.9999, 10.0] on divergence. `Decimal`, no dependencies
- [x] 4.2 **Done — Groww's published XIRR is the independent source**, plus a flows-clustered-at-the-end case that exercises the bisection fallback. ⚠ **Verified against an independent source, not against itself**: a spreadsheet's
      XIRR on the same flows to 6 decimals, plus a deliberately hard case with flows clustered
      near the end. A test comparing the implementation to its own prior output proves nothing
- [x] 4.3 **Done. Mid Cap lands EXACTLY on 12.25%**; Flexi Cap 6.49% vs 6.48%, explained by the displayed NAV's own 3dp rounding. **Reproduce Groww's published XIRR**: HDFC Flexi Cap 6.48%, HDFC Mid Cap 12.25%.
      Any difference must be explained — not tolerated with a loose assertion
- [x] 4.4 **Done.** TWR chained across external cash flows, with Modified Dietz where within-day timing
      is unknown. Both measures returned together; nothing in the API returns one alone
- [x] 4.5 **Done.** Currency decomposition — `r_local`, `r_fx`, `r_total_inr` — on SPCX, using the
      `fx_rate_inr` stored on each transaction. Verified by hand against the three buys

## 5. Prices, by hand

- [x] 5.1 **Done** as `pricing.py`. `pricing_feed.py` — record an observation, read the latest per instrument, report its
      age. `source='USER'` in this change; the shape is what an adapter will write in Phase 1b
- [x] 5.2 **Done** — and asserted on a typed price, so the logic is exercised before any feed exists. Staleness per the limits fixed in 0.5, applied **regardless of source**. A typed
      price is not exempt from being old, and letting it be exempt would ship the staleness
      logic untested
- [x] 5.3 **Done** — and a foreign holding with no FX rate is unpriced rather than valued at par. A holding with no price at all is a first-class state — quantity and cost basis shown,
      value shown as unavailable. Never zero, never last-known-without-saying-so

## 6. Entry, tools and API

- [x] 6.1 **Done.** `entry.py` — one `record()` used by both the REST endpoint and the assistant tool.
      Validates instrument, quantity, price, date, currency; computes charges; writes the row
- [x] 6.2 **Done.** Recording an instrument the system has not seen creates it and brings it into the
      tracked set — no second "add to watchlist" action
- [x] 6.3 **Done — draft-then-confirm, two calls not one.** ⚠ My first schema shape was flat and wrong; the registry wraps each in `{type, function}`. `core/tools/investments.py` — `record_transaction`, `get_portfolio`, `get_position`,
      `record_price`. ⚠ The tool parses language into structure and **shows it back for
      confirmation before writing**; the service accepts structured data only and never prose
- [~] 6.4 **MOVED to the Investments page change.** `api/investments.py` exists only to
      serve that page — chat reaches the ledger through `core/tools/investments.py`, which
      is done. Building an HTTP surface with no consumer would be scaffolding.
- [x] 6.5 **Done**, rewritten once — the first version inserted two rows with muddled semantics. Undo on a transaction inserts the reversing entry rather than deleting — the familiar
      gesture, the correct ledger behaviour

## 7. The Investments page — MOVED to its own change

Split deliberately, and the reasoning is recorded rather than assumed. The page is the largest
remaining piece and the **only part not covered by the "does it reproduce Groww" test**, which
is what every other section is checked against. This project's stated bar is a finished product
rather than "it works" — and a page rushed at the end of a long change is precisely how that
bar gets missed.

Moving with it: the holdings table, allocation view, equity curve, transaction entry and
history, `api/investments.py` (task 6.4), the keyboard and screen-reader pass, and the
post-deploy side-by-side comparison against Groww (task 9.5).

⚠ **One item must not be lost in the move**: the **corporate-action warning**. Until Phase 1b
there is no automatic ingestion, so an unrecorded split or bonus shows as a large phantom loss.
The mitigation is a warning on any holding that moved more than 25% in a day. It is recorded in
`docs/ROADMAP.md` as an accepted risk with that named mitigation, so it survives the split.

**The ledger is usable without the page**, through chat: recording a transaction, reading the
portfolio or a position, recording a price, and undo all work through the assistant tools.
Entry in particular is better in conversation than in a form. Reading is what the page is for.

## 8. Seed the real portfolio

- [x] 8.1 **Done.** A seeding script, idempotent, writing the reconciled data from 0.1
- [x] 8.2 **Done.** ⚠ Dogecoin (₹840, 4 buys) and Bitcoin (₹150, 2 buys) as **one aggregate row each** at
      the average price, dated to the **first** buy, `entry_source=IMPORT`, with a note saying
      it is an aggregate. The per-buy amounts are not recoverable from CoinSwitch and an
      invented breakdown would be worse than a labelled aggregate. ZIL and JASMY are exact
- [x] 8.3 **Done — one remittance, one rate (96.01).** SPCX with `fx_rate_inr` on each of the three buys, so 4.5 has real data
- [x] 8.4 **Done, and it caught a second hand-arithmetic error.** The mutual fund units Groww *displays* are rounded to 3dp; storing them made the cost basis ₹0.64 high. Units are now derived at 8dp from the ₹4,999.75 that actually left the bank, so cost basis is exact — the same rule the SPCX buys forced, now stated generally in `INVESTMENTS.md` §5. **Reconciliation test**: the seeded ledger reproduces every figure from 0.3. This is
      the test the whole change exists to pass

## 9. Verification

- [x] 9.1 From `backend/`: `uv run ruff format .`
- [x] 9.2 **683 passed, 5 skipped** (baseline 598). From `backend/`: `uv run pytest` — full suite green, count recorded and compared
      against 0.6. ⚠ Confirm the dev database container is up first; a stopped one makes the
      suite hang with no output rather than fail
- [x] 9.3 **Both green; Learn content OK at 74 explanations.** From `frontend/`: `npm run lint` **and** `npm run build` — lint runs checks the build
      does not
- [x] 9.4 Confirm `.env` is **not** staged before committing
- [~] 9.5 **MOVED to the Investments page change** — a side-by-side comparison needs the
      page to compare. Until then, `seed_investments --check` reconciles against
      `seed-reconciliation.md` on the real database, which is the same arithmetic.

## 10. Documentation

- [x] 10.1 **Done.** New `docs/INVESTMENTS.md` — the ledger model, why append-only, the two books, what
      is computed rather than stored
- [x] 10.2 **Done** (14 → 20 tables, the service package, the tools module). `docs/ARCHITECTURE.md` — six new tables (14 → 20), the `services/investments/`
      package, the ERD
- [x] 10.3 **Done.** `docs/ROADMAP.md` — Phase 1 landed; what Phase 1b and Phase 2 now depend on
- [x] 10.4 **Done** — two cards, on why a holding is computed and why a correction is a new entry. The Learn page — one card on why a position is computed rather than stored, and one
      on why a correction is a new entry rather than an edit
- [x] 10.5 ⚠ **Answered rather than ticked.** `INVESTMENTS.md` is new; `ARCHITECTURE.md`'s directory guide and table count are updated; `ROADMAP.md` states where the module stands and what blocks Phase 2. **The ARCHITECTURE ERD and the lifecycle diagrams are deliberately NOT updated** — they describe the request and job paths, which this change does not touch, and the Investments page is where a user-facing flow will actually appear. They belong in the page change. **Docs and diagrams reflect what was built.** If a diagram or card turns out not to
      need changing, say so explicitly here rather than dropping the item — "checked" and
      "forgotten" must stay distinguishable
