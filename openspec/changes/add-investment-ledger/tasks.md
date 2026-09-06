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
- [ ] 0.6 Run the full suite and record the count

## 1. Schema

- [ ] 1.1 Migration 014: `instruments`, `portfolios`, `transactions`, `price_observations`,
      `fx_observations`, `charge_schedules`. `Numeric` throughout, never float; `Text` + CHECK
      rather than Postgres enums; all timestamps `timestamptz`
- [ ] 1.2 `quantity Numeric(28,8)` and `price Numeric(20,6)` — 8 decimals so 0.00001978 BTC and
      0.862429 SPCX units are exact, 6 so a ₹0.0025 NAV and a $204.70 share both fit. A
      column that rounds a real holding is a column that lies on every read
- [ ] 1.3 ⚠ **The append-only trigger.** A Postgres rule or trigger raising on UPDATE and
      DELETE for `transactions`, `price_observations`, `fx_observations` — plus a test that
      *asserts the trigger actually fires*. A trigger nobody tests is a comment
- [ ] 1.4 `supersedes_id` self-reference on `transactions`, and a `live` helper resolving to
      entries not superseded — one definition, as `services/memory.live` already does
- [ ] 1.5 Verify up → down → up with rows present, and that the trigger is dropped and
      recreated correctly by both directions
- [ ] 1.6 Models in `db/models.py` with docstrings recording *why* append-only departs from the
      project's soft-delete convention

## 2. The fold

- [ ] 2.1 `services/investments/portfolio.py` — `positions()` folds transactions into quantity,
      cost basis and realised P&L. Pure function of the ledger, no stored state
- [ ] 2.2 Handles every `txn_type` the ledger permits, including `SPLIT` and `BONUS`, which
      change quantity and per-unit cost while **conserving total cost basis**. Assert that
      invariant in a test — it is the property a corporate action must never violate
- [ ] 2.3 A superseded transaction is invisible to the fold, and its reversal restores the
      earlier position exactly
- [ ] 2.4 Measure the fold on the real seed and record it. If it is not comfortably
      sub-millisecond, the "no cache" decision needs revisiting rather than defending

## 3. Lots, holding periods and charges

- [ ] 3.1 `taxrules.py` — FIFO lot matching for disposals, and weighted average alongside it,
      each returned under a name that says which it is
- [ ] 3.2 Per-asset-class holding-period rules: **12 months** Indian equity and equity MF,
      **24 months** US equity, **none** for crypto. Not a shared default with exceptions —
      three explicit rules, because the US one is the one that gets silently wrong
- [ ] 3.3 `days_to_long_term()` on any holding, so a disposal can be told how close the cliff is
- [ ] 3.4 Crypto losses are reported separately and **never netted** against gains elsewhere.
      Assert with the real seed: −₹1,076 across DOGE, ZIL and JASMY must not reduce the ₹1,386
      Indian equity gain, and the ₹6.01 Bitcoin gain must remain visible as a gain
- [ ] 3.5 `costmodel.py` — charges from `charge_schedules` by effective date, with the schedule
      id frozen onto the transaction. Test that changing a rate does not alter an old
      transaction's recorded charges
- [ ] 3.6 ⚠ **Prepaid tax is not a cost.** Crypto TDS (1%, s.194S) and LRS TCS (20% above
      ₹10 L/FY) are withheld against a future liability and are creditable or refundable.
      Modelling them as expenses would understate returns *and* double-count against the flat
      30% VDA rate. They are recorded as cash-flow items, visible, and excluded from the cost
      of a transaction. Assert both in a test
- [ ] 3.7 **Exit load reuses the FIFO lot matcher from 3.1** rather than getting a second one.
      1% on units redeemed within a year of *their own* allotment — which is per lot, which is
      exactly what 3.1 already computes. Both HDFC funds are inside that window today
- [ ] 3.8 ⚠ **Mutual funds held in demat incur a DP charge on redemption**; SOA-held units do
      not. Narendra's are demat (folio 40754072). Whether Groww's ₹16.50 markup applies to MF
      debits is unverified — model the CDSL ₹3.25 as certain and flag the markup as unknown
      rather than assuming either way

## 4. Returns

- [ ] 4.1 `returns.py` — XIRR by Newton–Raphson (r₀ = 0.10, 100 iterations, tol 1e-7) with
      bisection over [-0.9999, 10.0] on divergence. `Decimal`, no dependencies
- [ ] 4.2 ⚠ **Verified against an independent source, not against itself**: a spreadsheet's
      XIRR on the same flows to 6 decimals, plus a deliberately hard case with flows clustered
      near the end. A test comparing the implementation to its own prior output proves nothing
- [ ] 4.3 **Reproduce Groww's published XIRR**: HDFC Flexi Cap 6.48%, HDFC Mid Cap 12.25%.
      Any difference must be explained — not tolerated with a loose assertion
- [ ] 4.4 TWR chained across external cash flows, with Modified Dietz where within-day timing
      is unknown. Both measures returned together; nothing in the API returns one alone
- [ ] 4.5 Currency decomposition — `r_local`, `r_fx`, `r_total_inr` — on SPCX, using the
      `fx_rate_inr` stored on each transaction. Verified by hand against the three buys

## 5. Prices, by hand

- [ ] 5.1 `pricing_feed.py` — record an observation, read the latest per instrument, report its
      age. `source='USER'` in this change; the shape is what an adapter will write in Phase 1b
- [ ] 5.2 Staleness per the limits fixed in 0.5, applied **regardless of source**. A typed
      price is not exempt from being old, and letting it be exempt would ship the staleness
      logic untested
- [ ] 5.3 A holding with no price at all is a first-class state — quantity and cost basis shown,
      value shown as unavailable. Never zero, never last-known-without-saying-so

## 6. Entry, tools and API

- [ ] 6.1 `entry.py` — one `record()` used by both the REST endpoint and the assistant tool.
      Validates instrument, quantity, price, date, currency; computes charges; writes the row
- [ ] 6.2 Recording an instrument the system has not seen creates it and brings it into the
      tracked set — no second "add to watchlist" action
- [ ] 6.3 `core/tools/investments.py` — `record_transaction`, `get_portfolio`, `get_position`,
      `record_price`. ⚠ The tool parses language into structure and **shows it back for
      confirmation before writing**; the service accepts structured data only and never prose
- [ ] 6.4 `api/investments.py` — portfolio, positions, transactions, record, record price.
      Marshals HTTP and calls the same services
- [ ] 6.5 Undo on a transaction inserts the reversing entry rather than deleting — the familiar
      gesture, the correct ledger behaviour

## 7. The Investments page

- [ ] 7.1 Holdings table: quantity, average cost, current value, unrealised P&L, weight, and
      **price age** where a price is stale
- [ ] 7.2 Allocation view by asset class and currency, per `ui-standards`
- [ ] 7.3 Equity curve, folded on read, with both XIRR and TWR shown together and labelled
- [ ] 7.4 Transaction entry and history; history shows superseded entries as superseded rather
      than hiding them
- [ ] 7.5 ⚠ **The corporate-action warning.** Until Phase 1b there is no automatic ingestion, so
      the page flags any holding that moved more than 25% in a day with "this may be an
      unrecorded corporate action" rather than reporting it as a loss. This is the named
      mitigation for the accepted risk in the proposal
- [ ] 7.6 Keyboard and screen-reader pass, per the project's UI bar

## 8. Seed the real portfolio

- [ ] 8.1 A seeding script, idempotent, writing the reconciled data from 0.1
- [ ] 8.2 ⚠ Dogecoin (₹840, 4 buys) and Bitcoin (₹150, 2 buys) as **one aggregate row each** at
      the average price, dated to the **first** buy, `entry_source=IMPORT`, with a note saying
      it is an aggregate. The per-buy amounts are not recoverable from CoinSwitch and an
      invented breakdown would be worse than a labelled aggregate. ZIL and JASMY are exact
- [ ] 8.3 SPCX with `fx_rate_inr` on each of the three buys, so 4.5 has real data
- [ ] 8.4 **Reconciliation test**: the seeded ledger reproduces every figure from 0.3. This is
      the test the whole change exists to pass

## 9. Verification

- [ ] 9.1 From `backend/`: `uv run ruff format .`
- [ ] 9.2 From `backend/`: `uv run pytest` — full suite green, count recorded and compared
      against 0.6. ⚠ Confirm the dev database container is up first; a stopped one makes the
      suite hang with no output rather than fail
- [ ] 9.3 From `frontend/`: `npm run lint` **and** `npm run build` — lint runs checks the build
      does not
- [ ] 9.4 Confirm `.env` is **not** staged before committing
- [ ] 9.5 After deploy: seed the real portfolio and compare the page against Groww, CoinSwitch
      and INDmoney side by side. **Any difference beyond modelled charges is a defect**, not a
      rounding excuse

## 10. Documentation

- [ ] 10.1 New `docs/INVESTMENTS.md` — the ledger model, why append-only, the two books, what
      is computed rather than stored
- [ ] 10.2 `docs/ARCHITECTURE.md` — six new tables (14 → 20), the `services/investments/`
      package, the ERD
- [ ] 10.3 `docs/ROADMAP.md` — Phase 1 landed; what Phase 1b and Phase 2 now depend on
- [ ] 10.4 The Learn page — one card on why a position is computed rather than stored, and one
      on why a correction is a new entry rather than an edit
- [ ] 10.5 **Docs and diagrams reflect what was built.** If a diagram or card turns out not to
      need changing, say so explicitly here rather than dropping the item — "checked" and
      "forgotten" must stay distinguishable
