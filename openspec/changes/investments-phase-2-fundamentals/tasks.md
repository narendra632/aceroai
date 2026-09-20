# Tasks

## 1. Reading a filing

- [x] 1.1 `nse_xbrl` adapter over NSE's two results feeds, merged (the legacy one stops at
      Dec 2024, the integrated one starts there, so either alone has a hole)
- [x] 1.2 ⚠ URL-encode the symbol — `GVT&D` unescaped ends the query parameter and NSE
      truthfully answers about a company called "GVT" with nothing
- [x] 1.3 ⚠ Filter out governance filings: they parse perfectly and carry no financial line
- [x] 1.4 ⚠ Resolve contexts by their period DATES. Kaynes' March file reports revenue for the
      quarter (Rs 1,243 Cr) and the year (Rs 3,626 Cr) under the identical tag
- [x] 1.5 ⚠ Drop DIMENSIONAL contexts — segment revenue read as the company's is a large,
      plausible, wrong number
- [x] 1.6 ⚠ Consolidated preferred, standalone fallback. GE Vernova files ONLY standalone (no
      subsidiaries); requiring consolidated left the widest-bottleneck holding with no
      financials, reading as "this company does not report"
- [x] 1.7 ⚠ Keep prior-year comparatives, flagged. Found: legacy March filings tag the year's
      P&L as a fourth quarter and carry a balance sheet with no revenue beside it

## 2. Storing it

- [x] 2.1 Migration 019: `source_items` (provenance, 2 KB excerpt cap enforced by CHECK) and
      `fundamentals` (the figures), both append-only
- [x] 2.2 The literal filed characters are stored — an echo check needs the words, and a
      validator comparing a parsed number with itself validates nothing
- [x] 2.3 The document is NOT stored: 200 KB each against a 250 MB module budget
- [x] 2.4 One source item per (file, period), so each excerpt holds every line it cites
- [x] 2.5 PK is (instrument, period, metric, source) — re-parsing writes nothing
- [x] 2.6 ⚠ `.returning()` not `rowcount`: a batched INSERT reports -1, so the count came back
      negative and looked like a failure while the write had succeeded
- [x] 2.7 `reparse` — the tag maps GROW, and adding bank-equity tags reached only unread
      filings while every stored one kept its gap silently
- [x] 2.8 The most recent STATEMENT of a figure wins, which is what a restatement is

## 3. Two vocabularies

- [x] 3.1 ⚠ The tag map is chosen by what the document CONTAINS, not by its filename. The
      filename declares the taxonomy only from the Integrated Filing framework onward, so
      every pre-2025 bank filing was read with an industrial's map and found nothing
- [x] 3.2 ⚠ A bank files its equity as `Capital` + `ReservesAndSurplus`. Without those the one
      quality measure that DOES describe a bank was reported unknown

## 4. The quality score

- [x] 4.1 ROE, ROCE, cash conversion, balance sheet, retained earnings, margin of safety
- [x] 4.2 ⚠ A missing input scores `None`, never zero — and `earned`/`available` are reported
      together, because "6.0" means nothing without knowing six of what
- [x] 4.3 ⚠ A bank's ROCE, cash conversion and net debt report `None`, not zero. Borrowings
      are its raw material; scoring them as leverage makes the anchor holding a value trap
- [x] 4.4 ⚠ `MIN_YEARS_FOR_TREND` — one year cannot answer "three of the last five", so
      scoring it zero is arithmetically right and epistemically wrong. Set to 2, which is a
      measured property of the source: annual P&L exists only from FY25
- [x] 4.5 ⚠ Trailing reported earnings, never a forecast. No filing contains next year's
      profit, so a forecast can be checked against nothing
- [x] 4.6 Every component carries the filings it rested on
- [x] 4.7 ⚠ `MIN_AVAILABLE_FOR_VERDICT` — two quadrants hard-BLOCK a purchase, and a company
      blocked because its filings were not read is indistinguishable from one that deserves it

## 5. The measured flags

- [x] 5.1 Flag 2 (returns falling or below 15%), 8 (margins slipping while revenue scales),
      6 (multiple outrunning earnings), 10 (52-week range) — arithmetic, no model
- [x] 5.2 ⚠ UNKNOWN where nothing was read. A checklist that answers NO by default reports a
      clean bill of health it never checked
- [x] 5.3 Flags 6 and 10 are marked computed, so no later model verdict may overrule them
- [ ] 5.4 Flags 1, 3, 4, 5, 7, 9 — need a model reading news and filings; with source ingestion

## 6. Over the wire, and on the page

- [x] 6.1 `GET /api/investments/framework` carries quality, flags, quadrant and year count
- [x] 6.2 `FrameworkPanel` renders "—" for an absent input and both halves of the score
- [x] 6.3 Quadrants are worded as what they MEAN, not as box names
- [x] 6.4 `fundamentals_sync` job, Sundays, silent

## 7. Proof

- [x] 7.1 `test_investments_fundamentals.py` — 20 tests over hand-written filings carrying
      each real trap
- [x] 7.2 `test_investments_scoring.py` — 23 tests, most of them about refusals
- [x] 7.3 Teardown purges `fundamentals` and `source_items`
- [x] 7.4 Full suite: 975 passed, 5 skipped. Was 932.
- [x] 7.5 Verified against the REAL book: 37 filings, GVT&D scores Q3 at 6.0/9.0

## 8. Deployment

- [ ] 8.1 Pushed; migration 019 run; `fundamentals_sync` run on the server
- [ ] 8.2 Verified in production

## 9. Known limits, recorded rather than implied

- [x] 9.1 Annual P&L exists only for FY25 and FY26 — earlier March filings tag the year as a
      fourth quarter. The remedy, when worth the fetches, is summing four quarterly filings
- [x] 9.2 `retained_earnings` reports unknown: it needs five years of market value and the
      price record does not reach back that far
- [ ] 9.3 Watchlist companies have no margin of safety until the price backfill completes,
      which it does over several runs of `prices_india_close`
