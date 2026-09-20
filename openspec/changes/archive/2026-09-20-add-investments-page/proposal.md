# The Investments page

## Why

The ledger reproduces Groww to eleven paise and nobody can see it. Eleven holdings, five
Kaynes lots, a 24-month clock on SPCX, FIFO and weighted average disagreeing in sign — all of
it is reachable only by asking the assistant a question you already knew to ask.

That is backwards for this module. Reviewing a portfolio is *looking*: scanning what is held,
noticing what moved, seeing which lot crosses long-term next month. A conversation answers a
question. A page raises one.

It is also the last piece not covered by the "does it reproduce Groww" test that checked
everything else, which is why it was split out rather than rushed at the end of a long change.

## What Changes

- **A page that shows the whole book.** Totals, holdings, allocation, value over time, entry,
  and the full transaction history.

- **Money crosses the wire as decimal strings, never as JSON numbers.** ⚠ `0.1 + 0.2` is the
  oldest bug in software and a portfolio is nothing but sums of money. The backend computes
  every displayed figure — including percentages — in `Decimal` and serialises it as a string.
  The frontend converts to a number only for chart geometry, never for anything shown.

- **One fold, one endpoint, for the things that render together.** Positions, marks, totals and
  returns all come out of the same walk over the ledger. Splitting them across endpoints would
  run that walk three times to draw one screen. Transactions, the value curve and price entry
  are separate, because they have different lifetimes.

- **Entry on the page is the same two steps as in chat.** The form calls `prepare` and shows
  the costed draft — charges, prepaid tax, net rupees, warnings — and writes only on confirm.
  One code path, so a validation cannot be skipped by choosing the form.

- **Correction is a first-class action, not a delete.** The ledger is append-only, so the
  page's undo records the reversing `ADJUSTMENT` and says so: *"Reversed. The original entry
  stays in the record."* Superseded rows stay visible, struck through, rather than disappearing.

- **What cannot be priced is named, never zeroed.** An unpriced holding shows no value and says
  why; a total that excludes holdings says which ones. A stale mark shows its age everywhere it
  appears.

- **Crypto is shown apart from the rest.** Its losses offset nothing under s.115BBH, so a
  single netted figure would show a position the tax code does not permit.

- **The value curve is two folds, and admits which one is sparse.** Invested is exact and dense
  — it comes from transactions alone. Value exists only on days where every open holding has an
  observed price, and the chart states the range it covers. ⚠ Nothing is interpolated.

- **A move too large to be a price move is flagged.** More than 25% between two observations
  four days or fewer apart is surfaced as a possible unrecorded split or bonus — the mitigation
  named as an accepted risk when the ledger shipped.

- **Two chart primitives and a rename.** `Lines` (multi-series, one axis) and `StackedBar`
  (100% horizontal) join `ui/chart.tsx`. ⚠ `formatINR(usd)` — which converts dollars at a fixed
  88 for cost display — is renamed `approxINRFromUSD`, because a function of that name sitting
  next to real rupee figures is an 88× error waiting to happen. Two call sites.

## Capabilities

### Modified Capabilities

- **`investments`** — gains what the *interface* owes the record: that the book is visible
  without asking, that an incomplete figure says so, that correction is offered where the
  record is shown, and that a suspicious move is flagged. One existing requirement is
  refined: when only one of the two return measures can be computed, the missing one is named
  rather than the other being presented as "the return".

- **`ui-standards`** — the requirement that every stored field be editable gains its
  append-only exception. Not a loosening: correction stays mandatory, and the exception
  specifies that it is expressed as a superseding entry with both versions visible.

### Unchanged

- **`assistant-tools`** — no tool is added or altered. The page and the six existing tools call
  the same service functions, which is the point.
- **`scheduled-jobs`** — nothing runs on a schedule. There is still no feed to poll.

## Impact

**Schema.** ⚠ **One line, found during implementation — this section originally said "none".**
Migration 015 widens the `transactions_entry_source` check constraint to admit `FORM`. The
ledger shipped with `CHAT, SCREENSHOT, PROPOSAL_APPROVAL, CORP_ACTION, IMPORT`, and a
transaction typed into the page's form is none of them. Writing it as `CHAT` was the cheap way
out and is wrong: the distinction `entry_source` actually carries is **whether a language model
interpreted this or a person typed the fields**, and collapsing the two makes an append-only
record lie about how it came to exist. Purely additive — every existing row still satisfies the
widened constraint. No other figure the page shows needs schema it does not already have.

**Backend.** New `app/api/investments.py` (the routes deferred from the ledger change) and
`app/services/investments/history.py` (the value-over-time fold and suspicious-move detection).
`app/api/schemas.py` gains the investment shapes; `app/main.py` registers one router. ⚠ No
route writes a price — see the non-goals.

**Frontend.** New `components/InvestmentsView.tsx` and its parts (summary, holdings table,
position sheet, allocation, curve, entry form, history). `ui/chart.tsx` gains
`Lines` and `StackedBar` with a hover layer. `lib/api.ts` gains the client. `lib/format.ts`
gains `formatRupees` for real rupees and renames the USD converter. `Sidebar` gains a nav item,
`AppShell` a view and a `#investments` deep-link target.

**Documentation.** `docs/INVESTMENTS.md` (§10 currently says "No Investments page yet"),
`docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `AGENTS.md` ("Not built yet" names it), and the
Learn page.

**Dependencies.** ⚠ **None, and one is deliberately declined.** A charting library — Recharts,
visx, Chart.js — would be the obvious way to draw two of these. `ui/chart.tsx` already renders
SVG directly for exactly the reasons that still apply: theme tokens make light and dark correct
by construction rather than by overriding a library's defaults, and the whole file is 357 lines
against a dependency tree measured in megabytes. If a chart here needs something genuinely hard
— zoom, brushing, thousands of points — that is the moment to ask, and this change does not
reach it.

## Non-goals (this change)

- **No market data feed, and no way to type a price either.** ⚠ Reversed on Narendra's
  instruction, 2026-09-07: the Angel One feed is being built the same evening, so a
  hand-entry screen would be obsolete before it was reviewed. The consequence is accepted and
  visible — until the feed lands, the page shows what the book **cost** and not what it is
  **worth**, and the value line on the chart does not exist. The valuation, staleness and
  curve machinery is built and tested here regardless, so Phase 1b adds observations rather
  than a feature.
- **No MIRROR book in the interface.** It is empty until proposals exist, and a book selector
  offering one real choice is scaffolding pretending to be a feature. It arrives with Phase 2.
- **No scoring, proposals, gates, or theses on the page.** Not one model call. The page reads
  the ledger and nothing else.
- **No `portfolio_history` assistant tool.** The curve is a page object. Until a feed makes the
  value line dense, a tool for it would return a mostly-absent series, and the assistant
  already answers what is held and what it is worth.
- **No editing a transaction.** Never — that is the ledger's whole design. Correction is a
  reversing entry.
- **No screenshot or CSV import.** v1.5, unchanged.
- **No `daily_valuations` cache.** Still premature: the curve walks 27 transactions across
  ~200 days, and section 0 measures it before anything is designed around it.
- **No tax computation.** Holding periods, lots and flags are shown. A liability figure is not,
  ever.
