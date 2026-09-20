# Tasks

## 1. The tables

- [x] 1.1 Migration 018: `framework_versions` (the theory) and `ab_mappings` (where each
      company sits), split because one changes rarely and the other often
- [x] 1.2 `crossings_status` CHECK — CONFIRMED · PARTIAL · UNSUPPORTED
- [x] 1.3 `off_framework` with a CHECK that it names no bottleneck, and `review_after`
- [x] 1.4 Verified upgrade → downgrade → upgrade

## 2. The theory as data

- [x] 2.1 10 imperatives with urgency, named crisis and stated commitment figure
- [x] 2.2 31 bottlenecks, each carrying its crossing set **and where that set came from**
- [x] 2.3 Aliases (B9.1 ≡ B1.2, B8.2 ≡ B3.1) so one crossing cannot be counted twice by
      arriving at the bottleneck from two imperatives
- [x] 2.4 19 fair multiples, each labelled NOTES (his own number) or ANCHOR (set from the
      market level), with the reasoning on every row
- [x] 2.5 `EARNINGS_ONLY_SECTORS` for banks — **proven, not assumed**: HDFC Bank's filing is
      `INTEGRATED_FILING_BANKING_*` and carries interest earned/expended where an industrial
      carries revenue and finance costs
- [x] 2.6 B1.5 Solar Cell & Module Manufacturing proposed, marked as not from his notes

## 3. The score

- [x] 3.1 `ab_score` — breadth, crisis, timing, commitment, investability. Deterministic;
      no model touches it
- [x] 3.2 An unapproved mapping scores **zero**, however strong the bottleneck
- [x] 3.3 Off-framework scores **`None`**, which is a different answer from zero
- [x] 3.4 A PARTIAL crossing count is reported as a floor, in the score and in the interface
- [x] 3.5 The government-commitment point is **withheld** until source ingestion exists in
      stage 4 — awarding it from the framework's own prose is the system citing itself
- [x] 3.6 Timing is judged against the holding period, so FY28 is inside three years and
      outside one month

## 4. The flows

- [x] 4.1 **A** — the taxonomy carries provenance instead of defaulting to 1
- [x] 4.2 **B** — propose a company into an existing bottleneck; one click approves
- [x] 4.3 **C** — a new bottleneck arrives as a new framework version (B1.5 is the first case)
- [x] 4.4 **D** — a sector with no multiple is flagged, never silently defaulted
- [x] 4.5 Re-mapping supersedes and arrives **unapproved** — a fresh claim does not inherit
      the agreement given to the one it replaced
- [x] 4.6 `needs_attention` — everything blocking a complete score, as a worklist

## 5. The data on the shelf

- [x] 5.1 Sector labels on all 11 Indian equities
- [x] 5.2 Seven watchlist companies added (Apar, Solar, Neuland, Genus, Syrma, Premier, Rolex)
- [x] 5.3 Apar 24 → 26, Rolex 18 → 20, `SOLAR_MANUFACTURING` 18 added
- [x] 5.4 `seed_framework` proposes and **never** approves — a rule with an exception for
      trusted sources is a rule that acquires more exceptions
- [x] 5.5 Seed is idempotent. ⚠ Found live: Postgres has no tuple, so a tuple in the spec
      returned as a list and an unchanged framework compared unequal to itself, installing a
      new version on every run

## 6. Over the wire

- [x] 6.1 `GET /api/investments/framework`
- [x] 6.2 `POST .../mappings/{id}/approve` — the one click the whole score rests on
- [x] 6.3 `POST .../mappings/{id}/remap`
- [x] 6.4 `FrameworkPanel.tsx` — renders "—" for not-applicable and "at least N" for a floor,
      because flattening either prints something untrue

## 7. Proof

- [x] 7.1 `test_investments_frameworks.py` — 35 tests, led by the two **refusals**
- [x] 7.2 Teardown purges `ab_mappings` and `framework_versions`
- [x] 7.3 Full suite: 921 passed, 5 skipped. Was 883.
- [x] 7.4 `npm run build` typechecks and builds

## 8. NSE XBRL, checked live before stage 2 is designed

- [x] 8.1 All 11 companies return financial filings from both endpoints
- [x] 8.2 Kaynes FY26 annual parses with **all 14** line items the quality score needs
- [x] 8.3 ⚠ `GVT&D` must be URL-encoded — an unescaped `&` ends the query parameter, so NSE
      was asked about a company called "GVT" and truthfully answered with nothing
- [x] 8.4 ⚠ Governance filings share the feed with financial ones and must be filtered out
- [x] 8.5 ⚠ Context resolution is mandatory: the March file reports revenue for the quarter
      **and** the year under identical tags. Reading the wrong one is wrong by 4×, silently
- [x] 8.6 ⚠ Banks confirmed to use a different taxonomy, declared in the filename

## 9. Deployment

- [ ] 9.1 Pushed; migration 018 run on the server; both seeds run
- [ ] 9.2 Verified in production

## 10. Documentation

- [x] 10.1 `docs/phase2-framework-inputs.md` committed — the research this stage rests on
- [ ] 10.2 `docs/INVESTMENTS.md` — the framework section (with stage 2, once scores exist)

## 11. Owed at the end of Phase 2

- [ ] 11.1 **The walkthrough.** Hand-held explanation of the whole module — interface,
      arithmetic, framework layer — with worked examples and simulated scenarios under
      different conditions. ⚠ Phase 2 is not complete without this; it is a deliverable he
      asked for, not a courtesy.
- [ ] 11.2 The Schedule FA coverage wording: count days **held**, not days in the period, so
      "priced on 97 of 263 days" stops implying missing data when he simply did not own it yet
