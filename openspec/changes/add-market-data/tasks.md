# Tasks — market data (Investments Phase 1b)

## 0. Verify the assumptions before writing production code

- [x] 0.1 **Angel One login, quote and candles, from the laptop.** ✅ Login `SUCCESS` from an
      IP that is *not* the app's registered static IP — the IP rule gates orders only. The
      "Trading" key returns LTP for all four stocks and daily candles back to 2021, so the
      forum reports of new keys failing on history do not apply.
- [x] 0.2 **Angel One availability.** ⚠ An hour later `apiconnect.angelone.in` refused TCP
      entirely for 60+ minutes while `smartapi.`, `www.` and `margincalculator.` answered.
      Forum threads report the same, unexplained. → closes come from NSE (design §3).
- [x] 0.3 **NSE bhavcopy.** ✅ `BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip`, 200 KB, no
      key. Closes equal Angel's to the paisa; `FinInstrmId` equals Angel's token for all four
      (1333, 12092, 16783, 27839); carries ISIN. ⚠ Symbol is `GVT&D`, not `GVTD`.
- [x] 0.4 **Instrument master.** ⚠ Answers **404 to HEAD** and 200 to GET — a probe using
      HEAD would conclude it moved. 35 MB / 151,599 rows: rejected for the e2-micro.
- [x] 0.5 **CoinGecko Demo.** ✅ One call prices all four coins in INR. ⚠ `days=1000` is
      refused (error 10012): history is **365 days**.
- [x] 0.6 **Twelve Data Basic.** ✅ SPCX quote and daily series from 2026-06-11; USD/INR
      quote and series. Header auth (`Authorization: apikey …`) works — key stays out of URLs.
- [x] 0.7 **AMFI / mfapi.** ✅ Both funds: NAVAll lines and full history to 2013.
- [x] 0.8 **NSE corporate-action RSS.** ✅ 101 items; identifies companies by **name**,
      not symbol (design §6).
- [ ] 0.9 **From the GCP VM (Narendra):** Angel One and NSE reachable from a cloud IP.
      Commands in §8. Not blocking the build — only which source serves production.

## 1. Schema

- [x] 1.1 Migration 016: `instruments.angel_token`, `instruments.coingecko_id`; data fixes
      (GVT&D + alias, four coin IDs, two fund codes + ISINs). ✅ Upgrade, downgrade and
      re-upgrade all run clean on the dev database.
- [x] 1.2 Model fields on `Instrument`.

## 2. Adapters

- [x] 2.1 `marketdata/http.py`: client factory, retry with backoff, `ProviderError`, cooldown,
      and `json_decimal` — money is parsed straight to `Decimal`, never through a float.
- [x] 2.2 `angel_one.py`: login with cached session (re-login once on **any** refusal),
      `quote_ltp`, `daily_candles`.
- [x] 2.3 `nse.py`: `bhavcopy(date)`, `corporate_actions()`, name matching.
- [x] 2.4 `coingecko.py`: `prices`, `daily_history`, `search_id`.
- [x] 2.5 `twelve_data.py`: `quote`, `daily_series` (errors inside a 200 are errors).
- [x] 2.6 `amfi.py`: `latest_navs`, `nav_history`.

## 3. Orchestration

- [x] 3.1 NSE ISIN + token learned from the bhavcopy inside `fill_closes`; crypto via search.
- [x] 3.2 `fill_closes` — per-source gap filling, idempotent, Angel candles as NSE fallback.
- [x] 3.3 `refresh_stale` — live prices only for stale/missing marks.
- [x] 3.4 Corporate-action matching by normalised company name (≥ 8 characters).
- [x] 3.5 **Found:** the staleness rule (UTC vs IST, Indian hours on Nasdaq, weekends).
      Rewritten; see design §7. Old tests encoded the bug and were corrected.

## 4. Jobs, route, tools

- [x] 4.1 `jobs/prices.py`: `prices_india_close`, `prices_daily`, `corporate_actions_watch`.
- [x] 4.2 `POST /api/investments/prices/refresh` with a response model.
- [x] 4.3 `get_portfolio` calls `refresh_stale` first and reports each price's source.
      (`get_position` reports no price, so it needs no refresh.)

## 5. Frontend

- [x] 5.1 The page refreshes prices in the background after it has drawn, then reloads.
- [x] 5.2 Price source named: in the position sheet, and as a tooltip in the holdings table.

## 6. Tests

- [x] 6.1 Adapter parsing and request shape, via `httpx.MockTransport` — 23 tests.
- [x] 6.2 Angel adapter names only its three routes, and refuses any other.
- [x] 6.3 Gap filling: fills, is idempotent, respects first trade and the 365-day limit,
      skips holidays without re-asking, falls back to candles, survives a provider error.
- [x] 6.4 `refresh_stale` skips fresh marks; a failing source cools down.
- [x] 6.5 Corporate actions: bonus announced once; dividend and unheld company not.
- [x] 6.6 Closes are stamped at the market's close on the right day.
- [x] 6.7 **Tests moved to their own database** (design §7), with a no-network guard.
- [x] 6.8 The "every route needs a session" test now reads the OpenAPI schema (it had
      silently missed the reverse route).

## 7. Run it for real

- [x] 7.1 ✅ First real fill on the dev database: 44 s, every holding priced from its first
      trade (crypto from 2025-09-20), second run writes nothing. Book complete, none stale:
      invested ₹1,03,924.93, worth ₹1,03,253.21. Value line covers 365 of 672 days.
- [x] 7.2 ~~The value half of the Groww comparison~~ — dropped by Narendra (2026-09-19): he
      will check on his phone and report anything wrong.
- [x] 7.3 ✅ **Angel One through the production adapter** — on the phone hotspot: login,
      LTP for all four, candles, session reuse. The outage was between Narendra's HOME
      connection and `apiconnect.angelone.in` (hotspot: 200, home: no TCP) — not Angel's
      server. Worth rechecking from home; production calls from the VM regardless.
      Original note: Its host has refused connections
      from this laptop since ~16:10 IST on 19 Sep; the probe's login/quote/candles had
      succeeded before that with the same routes and bodies. One difference is untested
      live: the adapter sends the local IP as `X-ClientPublicIP` (Angel's own SDK sends a
      hard-coded one). Check: `uv run python -c "from app.services.marketdata import
      angel_one; print(angel_one.quote_ltp(['1333']))"`.
- [ ] 7.4 **A real bonus or split in NSE's feed.** Every item on 19 Sep was a dividend, so
      the purpose wording (`BONUS`, `SPLIT`, `SUB-DIVISION`, `CONSOLIDATION`) is from
      NSE's documented format, not observed. The 25% move warning remains the backstop.

- [x] 7.5 **TWR fixed and made readable** (design §8): daily chaining, first purchase day
      counted, a rupee sentence with each figure. Regression tests from the real book.
- [x] 7.6 **Crypto history before CoinGecko's window from Binance** (design §8). Real book:
      1,188 closes written, value line now 672 of 672 days from 17 Nov 2024; second run
      writes nothing. XIRR -1.79% a year; TWR -74.37% in total — both hand-verified.

- [x] 7.7 **Presentation, after Narendra used it** (design §8): TWR over a rolling year with
      the since-start figure in its note; long notes moved behind an "i"; chart axes carry the
      year and tooltips the full date; a 3Y range. Suite 824 passed.

- [x] 7.8 **Found on the deployed server:** migration 016's data fixes reach an EXISTING
      database only. Production migrated an empty schema, then the seed re-created the
      instruments with `GVTD` and no scheme codes — GE Vernova and both funds unpriced, and
      nothing said so. The identifiers now live in the seed as well, which also renames an
      instrument found under an old name rather than adding a second row. Two tests.

## 8. Production (Narendra)

- [ ] 8.1 Add the six values to the server's `.env` (`docs/DEPLOY.md` → Market data).
- [ ] 8.2 On the VM (SSH button):
      the two `curl` commands in `docs/DEPLOY.md` → Market data. Any number other than
      `000` means reachable.

## 9. Verification

- [x] 9.1 `uv run ruff format .` and `uv run pytest` from backend/ — **824 passed, 5 skipped**
      (was 771). `npm run build` and `npm run lint` from frontend/ — clean.
- [ ] 9.2 `.env` is not staged — checked at commit.
- [x] 9.3 docs and diagrams reflect what was built: `docs/INVESTMENTS.md` (§4 staleness, §10,
      new §14), `docs/ROADMAP.md`, `docs/DEPLOY.md` (Market data), `docs/JOBS.md` (three
      jobs), `AGENTS.md` (convention 14: tests in their own database), `.env.example`.
      No diagram shows the price path, so none needed changing.
