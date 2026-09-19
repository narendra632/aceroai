# Design — market data

## 1. Shape

```
app/services/marketdata/
  http.py         one httpx client factory, retry with backoff, per-provider cooldown
  angel_one.py    login (cached session), quote, daily candles — nothing else
  nse.py          bhavcopy for a date; corporate-action feed
  coingecko.py    simple price; daily history (≤ 365 days)
  twelve_data.py  quote; daily series (equities and USD/INR)
  amfi.py         today's NAVs (NAVAll.txt); history (mfapi.in)
  feed.py         fill_closes(), refresh_stale(), share_changing_actions() — the only writer
app/jobs/prices.py   prices_india_close, prices_daily, corporate_actions_watch
```

Adapters return plain values and raise `ProviderError`. They never touch the database.
`feed` decides what to fetch, writes observations, and turns
a provider failure into a counted miss — **nothing raises past the job or the route**.

Every adapter accepts an optional `httpx.Client`. Tests pass one built on
`httpx.MockTransport`, so they exercise real request construction and real response parsing
without a network and without a new test dependency.

## 2. Timestamps: which day a price belongs to

The value curve assigns an observation to `observed_at.date()`. So a daily close is stamped at
the moment the market actually closed, which lands on the right calendar day:

| Source | `observed_at` | `kind` |
|---|---|---|
| NSE bhavcopy / Angel candle | trade date 15:30 Asia/Kolkata | `CLOSE` |
| Twelve Data equity | trade date 16:00 America/New_York | `CLOSE` |
| AMFI / mfapi | NAV date 21:00 Asia/Kolkata | `NAV` |
| CoinGecko history | the point's own timestamp (00:00 UTC) | `CLOSE` |
| Any live quote | the provider's quote time, else now | `LAST` |
| USD/INR daily | date 12:00 UTC | (fx table) |

⚠ Angel's candles are stamped `T00:00:00+05:30`. Taking that literally would put the close at
the *start* of the day, and every staleness check would read it as nine hours older than it is.

## 3. Gap filling

For each instrument: `start = max(first trade date, provider limit, newest close + 1 day)`,
`end = today`. Missing days are grouped so that one NSE file serves every stock for that day.

- **NSE:** one bhavcopy per missing weekday. 404 means holiday *or* not yet published; either
  way the day is simply retried next run, and it stops being "missing" once a later close
  exists — `newest close + 1` moves past it. No holiday calendar to maintain.
- **Fallback:** days the bhavcopy could not be fetched at all (error, not 404) are requested
  from Angel's daily candles for that instrument.
- **CoinGecko:** `market_chart?days=N&interval=daily`, N clamped to 365.
- **Twelve Data / mfapi:** one series request per instrument from `start`.

The first run on a fresh database therefore fetches everything that exists; every later run
fetches a day or two. Measured on the real book: ~110 bhavcopy files (≈200 KB each) once.

## 4. Live prices

`refresh_stale(db)` looks at the current marks and fetches only instruments whose mark is
missing or stale by `pricing.staleness_limit` — which had to be rewritten first (section 7). So during market hours an NSE
price older than 30 minutes is refreshed; after the close, last night's price is current and
nothing is fetched. Twelve Data's 800/day allowance is therefore used a handful of times a day.

Angel's session (JWT) is cached in-process and reused until it fails auth, then re-created.
Logging in on every call would be ~30 logins a day for no benefit.

## 5. Identifiers

Migration 016 adds nullable `instruments.angel_token` and `instruments.coingecko_id`, and fixes
the known rows by `(exchange, symbol)`:

- `GVTD` → `GVT&D`, alias `GVTD` kept (chat and old notes still find it).
- Crypto: BTC→`bitcoin`, DOGE→`dogecoin`, ZIL→`zilliqa`, JASMY→`jasmycoin` (all four
  returned INR prices under these IDs in the probe).
- Funds: HDFCMIDCAP→`118989` (`INF179K01XQ0`), HDFCFLEXICAP→`118955` (`INF179K01UT0`),
  confirmed by Narendra 2026-09-19.

NSE `isin` and `angel_token` are **not** hard-coded: `fill_closes` learns them from the
bhavcopy by exact symbol or alias, which also serves any stock recorded later. A crypto with no
`coingecko_id` is looked up once via CoinGecko `/search` (exact symbol, best market-cap rank).
A fund with no scheme code stays manually priced and is reported — guessing between a fund's
Direct/Regular/Growth/IDCW variants picks a price that is plausible and wrong.

## 6. Corporate actions

NSE's `Corporate_action.xml` names **companies, not symbols** ("Kaynes Technology India
Limited"). A held stock matches when the item's company name, normalised (case, punctuation,
"limited"/"ltd"), starts with the instrument's normalised name or an alias. Only purposes
containing SPLIT, BONUS or CONSOLIDATION notify; dividends do not. Tag
`corpaction-{symbol}-{exdate}` with `already_said`, so each action is reported once.

## 7. Found while building

- **The staleness rule was wrong in three ways**, invisible while every price was typed: it
  read the UTC clock against Indian hours, applied Indian hours to Nasdaq, and let Friday's
  close go stale on Saturday. Rewritten per market in its own timezone, with a closing price
  current until the next session opens (never under the old floors). Found because the first
  live refresh re-fetched SPCX on every call over a weekend.
- **Tests now run in their own database.** The first real prices broke 18 tests that price
  fictional books on real symbols (HDFCBANK now had a real close). The dev database had
  already caused two earlier classes of leak. `tests/conftest.py` creates and migrates
  `<db>_test`; a test-wide guard blanks market-data keys and refuses real HTTP.
- **Angel One's host answers 404 to HEAD** on the instrument master while serving it on GET.
- **FastAPI 0.139 hides included routers from `app.routes`**, so the auth test that claimed to
  cover "every route" was a hand list that had missed the reverse route. It now reads the
  OpenAPI schema and fails if it finds none.

## 8. Returns, made correct and readable (Narendra, 2026-09-19)

- **TWR chained daily** — `value today ÷ (value yesterday + money added today)` — replacing
  purchase-cut periods at Modified Dietz 0.5, which diluted a 58% fall into -15.6%. The first
  purchase day is chained from nothing, as every later purchase day already was.
- **Crypto history back to the first purchase** from Binance (`marketdata/binance.py`), for
  days before CoinGecko's window only.
- **TWR reported over a rolling year** (`TWR_WINDOW_DAYS`), with the since-start figure in
  the explanation. Since-inception chaining cannot recover from an early collapse — -74%
  needs +290% — so it would ignore everything the user does from here.
- **A short rupee line on each card, the long note behind an "i"** (`components/InfoTip.tsx`).
  What the number *is* — "per year", "12 months to <date>" — stays on the card: a tooltip is
  invisible to someone scanning and costs a tap on a phone.
- **Chart axis labels carry the year** past ~8 months, and every chart tooltip gives the full
  date. "May 23" on a three-year range does not say which year. A 3Y range was added.
- Verified: XIRR reproduces today's value to the paisa; TWR equals an independent hand chain.

## Rejected

- **Angel One as the source of daily closes.** Its API host was unreachable for over an hour
  during the probe; the bhavcopy is the exchange's own record and needs no login.
- **Angel One's SDK.** Puts order-placing methods in the process; safety would be a deny-list
  to maintain. Direct `httpx` means the order URLs are not in the codebase at all.
- **Angel's 35 MB instrument master** for token lookup. Parsing it costs hundreds of MB of RAM
  on a 1 GB e2-micro. The bhavcopy carries the same tokens in 200 KB.
- **A one-off backfill script.** Someone has to remember to run it on the server, and until
  they do, production has no history. Gap filling makes the first scheduled run do it.
- **`yfinance`.** Unofficial, rate-limited from cloud IPs, fails silently.
- **CoinGecko's paid tier, typed history, or a line interpolated from the purchase price**
  for crypto before Sept 2025. Binance's public data gives real daily closes for free
  (USDT × that day's USD/INR, matching CoinGecko to a median 0.1%). Interpolation would put
  an invented history under the value line and the TWR.
- **Fixing the 18 leaking tests one by one** (fictional symbols, pinned clocks). It would
  have treated the symptom; the cause was tests sharing a database with a real life.
- **Storing provider IDs in one JSON column.** Two explicit columns are queryable, typed and
  self-describing; a JSON bag hides typos until runtime.
