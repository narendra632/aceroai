# Tasks

## 1. Corporate actions — the record

- [x] 1.1 Migration 017: `corporate_actions`, with a `dedupe_key` unique per instrument
      (NULLs are distinct in Postgres, so an undated announcement keyed on `ex_date` would
      insert afresh every evening — exactly what the column prevents)
- [x] 1.2 CHECK constraints: a ratio is wholly present or wholly absent and positive;
      `APPLIED` if and only if a transaction is attached
- [x] 1.3 `CorporateAction` model, documenting why this table is **not** append-only
- [x] 1.4 Verified upgrade → downgrade → upgrade

## 2. Corporate actions — reading the feed

- [x] 2.1 `corpactions.parse`: ratio as an exact `Fraction`, never a rounded decimal
- [x] 2.2 Refuse a bare `SPLIT a:b`; refuse an announcement carrying a bonus *and* a split;
      refuse a multiplier outside 1/50…50
- [x] 2.3 Ratios stored as integers (1/3 has no exact decimal, and a third of a holding
      rounded at storage time is a rounding error written permanently into the quantity)
- [x] 2.4 Checked against the **live** NSE feed: 101 items, 99 `DIVIDEND`, zero false
      positives (20 Sep 2026). ⚠ No split or bonus was in the feed that day, so the
      split/bonus wordings are covered by unit tests over forms NSE publishes, not by a live
      match — recorded here rather than implied

## 3. Corporate actions — applying

- [x] 3.1 `entry.record_action`, beside `record`, so every append to the ledger stays in one
      module; negative quantities and a zero price allowed, and each documented
- [x] 3.2 `corpactions.apply` writes the change on the **ex-date**, not the day it was read
- [x] 3.3 Nothing held → `IGNORED` with a reason, so the holding is not flagged for ever
- [x] 3.4 Undated announcements are never applied on a schedule
- [x] 3.5 **Fix `_rescale_lots`**: each lot's quantity scales up and its unit cost scales
      down, instead of every lot being handed the book average

## 4. Gate G7 and the interface

- [x] 4.1 `corpactions.open_actions` — one definition, read by the page and the assistant
- [x] 4.2 `Holding.open_action`, and the announced flag outranks the guessed one
- [x] 4.3 `GET/POST /api/investments/corporate-actions` (+ apply, dismiss), ownership
      established through the book's own transactions — an id is not an authorisation
- [x] 4.4 `CorporateActions.tsx`, placed **above** the chart and the holdings, because it
      explains a number that is otherwise read first and believed

## 5. Schedule FA

- [x] 5.1 `history.price_series` / `fx_series` / `value_as_of` made public — one reader of the
      price record, not two that can drift apart
- [x] 5.2 `schedulefa.report`: calendar year, per foreign security, day-by-day walk
- [x] 5.3 Coverage reported beside the peak
- [x] 5.4 Every year since the first foreign purchase offered, not only years with activity
- [x] 5.5 `GET /api/investments/schedule-fa`, and `ForeignHoldings.tsx`
- [x] 5.6 The TT-buying-rate caveat stated on the card, not only in the code

## 6. Storage budget

- [x] 6.1 `vitals.table_bytes` using `pg_total_relation_size` via `to_regclass` (NULL for a
      table a migration has not created yet, rather than raising)
- [x] 6.2 `investments_disk_watch`, Mondays, banded and repeated daily while unresolved

## 7. Proof

- [x] 7.1 `test_investments_corpactions.py` — 41 tests: what is read, what is **refused**,
      what is written, G7, the routes, the job
- [x] 7.2 `test_investments_schedulefa.py` — the peak placed on a day with no transaction, so
      an implementation sampling transaction dates cannot pass
- [x] 7.3 Teardown purges `corporate_actions` before the rows they point at
- [x] 7.4 Full suite: 882 passed, 5 skipped (the quarantined memory tests). Was 868.
- [x] 7.5 `npm run build` typechecks and builds

## 8. Deployment

- [ ] 8.1 Pushed, migration 017 run on the server
- [ ] 8.2 Verified against production

## 9. Documentation

- [x] 9.1 `docs/INVESTMENTS.md` §12 rewritten, §12a added, §13 code map updated
- [x] 9.2 `docs/JOBS.md` — the new job and its window
- [x] 9.3 `.env` confirmed not staged
