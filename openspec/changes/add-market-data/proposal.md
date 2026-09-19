# Market data — Investments Phase 1b

## Why

The ledger knows exactly what was bought and what it cost, and has no idea what any of it is
worth. Every price today is one someone typed, so the page shows eleven unpriced holdings, the
value line is absent, and half of the Groww acceptance test is owed.

The accounts exist and every source has been **called live before this proposal was
written** (section 0 of `tasks.md` records what each returned). Nothing below rests on a
provider's documentation alone.

## What Changes

- **Four free sources, each for what it is best at.**

  | Holdings | Daily close | Live price |
  |---|---|---|
  | NSE equities (4) | **NSE bhavcopy** — official, keyless, carries ISIN | **Angel One** quote |
  | Mutual funds (2) | **AMFI** `NAVAll.txt`, history from **mfapi.in** | — (one NAV a day) |
  | US equity (SPCX) + USD/INR | **Twelve Data** daily series | Twelve Data quote |
  | Crypto (4) | **CoinGecko** daily history | CoinGecko simple price |

  ⚠ NSE closes come from the exchange's own file, not from Angel One. Found by probing: Angel's
  API host went unreachable for over an hour on the afternoon of 19 Sep while every other
  Angel host answered, and the forum shows the same unexplained timeouts going back years. The
  bhavcopy's closes matched Angel's to the paisa, and its instrument IDs **are** Angel's
  tokens. So the close of record never depends on Angel, and Angel is used for the one thing
  only a broker feed provides — the price during market hours. If the bhavcopy is unavailable
  for a day, Angel's daily candles fill that day instead.

- **Prices are observations, written append-only, never twice.** Adapters write the same
  `price_observations` / `fx_observations` rows a typed price does, with a different `source`.
  The existing primary key (instrument, time, source, kind) makes a re-run a no-op.

- **Gap filling, not a separate backfill step.** Each scheduled run fills every missing day
  from a holding's first trade (or the provider's limit) to today. The first run on any
  database *is* the backfill — nothing to remember to run on the server.

  ⚠ *Superseded (design §8): older crypto days now come from Binance's public data, and
  the value line starts at the first purchase.* CoinGecko's free tier returns **365 days**,
  and that window slides: each day of delay
  loses one more day. Crypto held since December 2024 will have a value line from about
  September 2025. Narendra's decision (2026-09-19): accept it — no paid plan, no typed history.

- **Instruments identified by codes that do not change.** Migration 016 adds `angel_token`
  and `coingecko_id`; NSE equities also get their ISIN, all read from the bhavcopy. It
  corrects `GVTD` to NSE's real symbol `GVT&D` (keeping `GVTD` as an alias, so chat still
  finds it) and sets the two confirmed AMFI scheme codes.

- **Three scheduled jobs and one refresh route.**
  - `prices_india_close` — weekdays 19:00 IST, after NSE publishes: NSE closes.
  - `prices_daily` — 07:30 IST: crypto, US close, USD/INR, fund NAVs.
  - `corporate_actions_watch` — weekdays 20:00 IST: NSE's corporate-action feed, and a
    notification for any **split, bonus or consolidation** on a held stock, so it gets
    recorded before it shows up as a phantom loss.
  - `POST /api/investments/prices/refresh` — fetches live prices **only for marks that are
    stale**. The page calls it on open, in the background; the assistant's portfolio tools
    call the same service function. One implementation, two callers.

- **Angel One is read-only by construction.** The adapter contains exactly three URLs:
  login, quote and daily candles. There is no order, holdings or GTT code to block, because
  none was written. A test asserts the module names no other Angel route.

## New dependencies

- **`pyotp`** — turns the stored TOTP secret into the current six-digit code. ✅ Approved
  by Narendra 2026-09-19 and already added.
- Everything else uses `httpx`, already a dependency. The Angel One SDK is **not** used
  (approved 2026-09-19): it would bring order-placing methods into the process and three
  transitive packages onto the e2-micro.

## Non-goals (this change)

- **Automatic corporate-action transactions.** The watch *notifies*; a person records the
  split or bonus. Parsing ratios out of free text and writing them to an append-only ledger
  without review is how a feed invents a holding.
- **Intraday history.** Live prices are stored as they are fetched, but no intraday chart.
- **A WebSocket feed.** Ticks are pointless for a weeks-to-quarters horizon.
- **Price quarantine.** The existing suspicious-move warning covers the case; automatic
  distrust of prices is a later change if a real bad print ever shows up.
- **CoinGecko attribution and Twelve Data's display licence.** Narendra's call (2026-09-19):
  a private single-user app; not pursued.
- **A circuit breaker.** At four scheduled calls a day there is nothing to protect. Retries
  with backoff, plus a short in-process cooldown so repeated page opens do not hammer a dead
  host, cover it. Failure stays visible where it matters: the price is shown as stale.

## Impact

- **Backend:** `app/services/marketdata/` (new: one module per provider plus orchestration),
  `app/jobs/prices.py` (new), migration 016, `app/api/investments.py` (+1 route),
  `app/core/tools/investments.py` (portfolio tools refresh stale marks first),
  `app/config.py` (six settings, already added).
- **Frontend:** the Investments page calls refresh when it opens, and shows where a price
  came from.
- **Production:** the six values must be added to the server's `.env`. Two reachability
  checks (Angel One and NSE, from the GCP VM) are listed for Narendra in `tasks.md`, because
  cloud IPs are what these hosts are most likely to refuse.
