"""Deciding what to fetch, fetching it, and writing it down.

Adapters know how to talk to one source. This module knows which holdings need which prices,
and is the only place that writes them. Two entry points, both safe to call at any time:

* `fill_closes` — every missing daily close from a holding's first trade (or its source's
  earliest day) to today. Run by the scheduled jobs. Its first run on any database **is** the
  backfill; there is no separate step to remember on the server.
* `refresh_stale` — a live price for each open holding whose newest price is stale by the
  rules in `pricing.STALE_AFTER`, and nothing for the rest. Called when the portfolio is
  looked at, on the page or through the assistant.

⚠ **Nothing raises past this module.** A source that fails is recorded in the report and the
holdings it would have priced keep their last price, shown with its age. A portfolio view
must never fail because a price feed did.

⚠ **Written observations are never duplicated.** `price_observations` is keyed on
(instrument, time, source, kind) and every insert here is `ON CONFLICT DO NOTHING`, so filling
the same day twice writes nothing the second time.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import FxObservation, Instrument, Portfolio, PriceObservation
from app.services.investments import portfolio as pf
from app.services.investments import pricing
from app.services.marketdata import amfi, angel_one, binance, coingecko, http, nse, twelve_data
from app.services.marketdata.http import ProviderError

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")

#: The exchange rate the US holdings need, in the form `pricing.latest_fx` reads.
USD_INR = "USDINR"
#: Daily rates and live rates are kept apart by source, because the fx table has no `kind`:
#: without the distinction, a rate fetched live this morning would count as "yesterday is
#: filled" and yesterday's daily rate would never be written.
FX_DAILY_SOURCE = twelve_data.PROVIDER
FX_LIVE_SOURCE = f"{twelve_data.PROVIDER}_LIVE"
#: How old the rate may be before a refresh fetches a new one. The rupee moves ~0.3% on a
#: busy day; four hours of that is well under the noise in the prices it converts.
FX_STALE_AFTER = dt.timedelta(hours=4)

#: How far back a company that is WATCHED but not held is priced.
#:
#: ⚠ Not a round number for its own sake. The reflexivity checklist asks whether a stock's
#: 52-week range has blown out and whether its multiple expanded faster than its earnings over
#: twelve months — neither is computable without a year of closes. A watchlist that cannot be
#: valued is a list of names, and the whole point of watching a company is to be able to say
#: whether today is a sensible day to buy it.
WATCHLIST_HISTORY_DAYS = 400

#: The most NEW days a single fill run will fetch from NSE.
#:
#: ⚠ Bounded because adding a watched company asks for ~280 trading days that nothing has ever
#: fetched, and a job that downloads 280 files in one pass is a job that hammers a public
#: archive and runs for ten minutes. Spread over a few runs it is invisible. Days are filled
#: OLDEST FIRST and that order is load-bearing: `_start` resumes from the newest close already
#: stored, so fetching recent days first would move the resume point forward and the older gap
#: would never be filled at all.
MAX_NEW_DAYS_PER_RUN = 120

#: Pause between bhavcopy downloads on a long fill — the first run fetches ~100 files, and
#: NSE's archive is a public service. Module-level so tests can zero it.
FILE_PAUSE = 0.25


# --- when a price belongs ----------------------------------------------------------------
#
# ⚠ The value curve assigns an observation to `observed_at.date()`. So each close is stamped
# at the moment the market actually closed — which is on the right calendar day in UTC and in
# IST alike — and never at midnight, where staleness would read it as hours older than it is.


def nse_close_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(15, 30), IST)


def us_close_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(16, 0), NEW_YORK)


def nav_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(21, 0), IST)


def fx_daily_at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(12, 0), dt.UTC)


# --- what is held, and since when ---------------------------------------------------------


@dataclass
class Span:
    """The days on which an instrument needs a price: from its first trade until today if it
    is still held, or until its last trade if it has been sold out of every book."""

    instrument: Instrument
    first: dt.date
    end: dt.date
    is_open: bool
    #: ⚠ Whether the book has ever TRANSACTED in this instrument, as against merely watching
    #: it. Both need prices; only one can have a corporate action that corrupts a position.
    #: Without the distinction, a bonus announced on a watchlist company would be recorded,
    #: notified and then closed as "nothing held" — noise about a holding that does not exist.
    held: bool = True


def spans(db: Session, today: dt.date) -> list[Span]:
    first: dict[uuid.UUID, dt.date] = {}
    last: dict[uuid.UUID, dt.date] = {}
    open_ids: set[uuid.UUID] = set()

    for portfolio_id in db.execute(sa.select(Portfolio.id)).scalars():
        txns = pf.ledger(db, portfolio_id)
        for t in txns:
            first[t.instrument_id] = min(first.get(t.instrument_id, t.trade_date), t.trade_date)
            last[t.instrument_id] = max(last.get(t.instrument_id, t.trade_date), t.trade_date)
        if txns:
            open_ids.update(
                p.instrument_id
                for p in pf.positions(db, portfolio_id, include_closed=True)
                if p.is_open
            )

    out = []
    if first:
        instruments = db.execute(
            sa.select(Instrument).where(Instrument.id.in_(first), Instrument.deleted_at.is_(None))
        ).scalars()
        for inst in instruments:
            is_open = inst.id in open_ids
            out.append(
                Span(
                    instrument=inst,
                    first=first[inst.id],
                    end=today if is_open else min(last[inst.id], today),
                    is_open=is_open,
                )
            )

    # --- watched but never bought ----------------------------------------------------------
    #
    # ⚠ Everything above is derived from TRANSACTIONS, which meant a company on the watchlist
    # was never priced at all — it never entered the loop. That is not a cosmetic gap: no
    # market price means no margin of safety, and a margin of safety is the single most
    # important thing the quality score produces. A watchlist you cannot value is a list of
    # names.
    #
    # The cost is nearly nothing going forward: NSE's bhavcopy is one file per day carrying
    # every symbol, and those files are already fetched daily for the holdings. Only the
    # historical backfill is new, and `MAX_NEW_DAYS_PER_RUN` spreads it.
    watched = db.execute(
        sa.select(Instrument).where(
            Instrument.deleted_at.is_(None),
            Instrument.is_tracked.is_(True),
            Instrument.asset_class.in_(("EQUITY_IN", "EQUITY_US")),
            Instrument.id.notin_(set(first)) if first else sa.true(),
        )
    ).scalars()
    for inst in watched:
        out.append(
            Span(
                instrument=inst,
                first=today - dt.timedelta(days=WATCHLIST_HISTORY_DAYS),
                end=today,
                is_open=True,
                held=False,
            )
        )
    return sorted(out, key=lambda s: s.instrument.symbol)


def _newest_close(db: Session, instrument_id: uuid.UUID) -> dt.date | None:
    """The day of the newest daily close or NAV, from any source. A typed or live price does
    not count: it says nothing about whether that day's close was recorded."""
    newest = db.execute(
        sa.select(sa.func.max(PriceObservation.observed_at)).where(
            PriceObservation.instrument_id == instrument_id,
            PriceObservation.kind.in_(("CLOSE", "NAV")),
        )
    ).scalar()
    return newest.astimezone(dt.UTC).date() if newest else None


def _start(db: Session, span: Span, floor: dt.date | None = None) -> dt.date:
    newest = _newest_close(db, span.instrument.id)
    start = span.first if newest is None else max(span.first, newest + dt.timedelta(days=1))
    return max(start, floor) if floor else start


def _weekdays(start: dt.date, end: dt.date) -> list[dt.date]:
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


# --- writing ------------------------------------------------------------------------------


def _write_prices(db: Session, rows: list[dict], now: dt.datetime) -> int:
    """Insert observations, skipping any that already exist. Returns how many were new.

    A stamp in the future is pulled back to now: AMFI sometimes publishes a NAV before 21:00,
    and an observation dated later than the moment it was read would never age.
    """
    if not rows:
        return 0
    for row in rows:
        row["observed_at"] = min(row["observed_at"], now)
    # Counted from RETURNING, not `rowcount`: a batched insert reports -1 for that.
    stmt = (
        insert(PriceObservation)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(PriceObservation.instrument_id)
    )
    return len(db.execute(stmt).all())


def _write_fx(db: Session, rows: list[dict], now: dt.datetime) -> int:
    if not rows:
        return 0
    for row in rows:
        row["observed_at"] = min(row["observed_at"], now)
    stmt = insert(FxObservation).values(rows).on_conflict_do_nothing().returning(FxObservation.pair)
    return len(db.execute(stmt).all())


def _price(inst: Instrument, at: dt.datetime, source: str, kind: str, price: Decimal) -> dict:
    return {
        "instrument_id": inst.id,
        "observed_at": at,
        "source": source,
        "kind": kind,
        "price": price,
        "currency": inst.currency,
    }


@dataclass
class Report:
    """What a run did. Counts and short reasons only — this lands in `job_runs.detail`."""

    written: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failed: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)

    def detail(self) -> dict:
        out: dict = {"written": dict(self.written)}
        if self.failed:
            out["failed"] = self.failed
        if self.unresolved:
            out["unresolved"] = sorted(set(self.unresolved))
        return out


# --- identifiers --------------------------------------------------------------------------


def _bhav_row(rows: dict[str, nse.BhavRow], inst: Instrument) -> nse.BhavRow | None:
    """The bhavcopy line for a holding: by token once known, else by symbol or alias."""
    if inst.angel_token:
        for row in rows.values():
            if row.token == inst.angel_token:
                return row
    for name in (inst.symbol, *(inst.aliases or ())):
        row = rows.get(name.upper())
        if row is not None:
            return row
    return None


def _learn_from_bhav(inst: Instrument, row: nse.BhavRow) -> None:
    """Fill the holding's ISIN and Angel token from the exchange's own file, once."""
    if not inst.isin and row.isin:
        inst.isin = row.isin
    if not inst.angel_token and row.token:
        inst.angel_token = row.token


# --- daily closes -------------------------------------------------------------------------

GROUPS = ("NSE", "MF", "US", "CRYPTO")


def fill_closes(
    db: Session,
    groups: tuple[str, ...] = GROUPS,
    *,
    now: dt.datetime | None = None,
    c: httpx.Client | None = None,
) -> Report:
    """Fill every missing daily close for the given groups. Commits after each group, so a
    failure late in a long first run does not throw away what was already fetched."""
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(IST).date()
    report = Report()
    all_spans = spans(db, today)
    own = c is None
    c = c or http.client()
    try:
        for group, fill in (
            ("NSE", _fill_nse),
            ("MF", _fill_mf),
            ("US", _fill_us),
            ("CRYPTO", _fill_crypto),
        ):
            if group not in groups:
                continue
            try:
                fill(db, all_spans, now, c, report)
                db.commit()
            except Exception as exc:  # noqa: BLE001 - one source must not stop the others
                db.rollback()
                report.failed[group] = (
                    exc.reason if isinstance(exc, ProviderError) else type(exc).__name__
                )
                log.warning("price fill for %s failed: %s", group, report.failed[group])
    finally:
        if own:
            c.close()
    return report


def _fill_nse(db: Session, all_spans: list[Span], now, c, report: Report) -> None:
    mine = [s for s in all_spans if s.instrument.exchange == "NSE"]
    needed: dict[dt.date, list[Span]] = defaultdict(list)
    for span in mine:
        for day in _weekdays(_start(db, span), span.end):
            needed[day].append(span)

    unfetched: dict[uuid.UUID, list[dt.date]] = defaultdict(list)
    by_id = {s.instrument.id: s for s in mine}

    # ⚠ Oldest first, and capped. `_start` resumes from the newest close already stored, so
    # fetching recent days first would advance the resume point past the gap and the older days
    # would never be fetched at all. The cap simply stops one run doing a whole year.
    days = sorted(needed)[:MAX_NEW_DAYS_PER_RUN]
    for i, day in enumerate(days):
        if i and FILE_PAUSE:
            time.sleep(FILE_PAUSE)
        try:
            rows = nse.bhavcopy(day, c)
        except nse.NotPublished:
            continue  # a holiday, or not out yet: tried again next run
        except ProviderError:
            for span in needed[day]:
                unfetched[span.instrument.id].append(day)
            continue
        batch = []
        for span in needed[day]:
            row = _bhav_row(rows, span.instrument)
            if row is None:
                report.unresolved.append(span.instrument.symbol)
                continue
            _learn_from_bhav(span.instrument, row)
            batch.append(
                _price(span.instrument, nse_close_at(day), nse.PROVIDER, "CLOSE", row.close)
            )
        report.written["NSE"] += _write_prices(db, batch, now)

    if not unfetched:
        return
    # NSE's file could not be fetched for these days — not "no file", an actual failure.
    # Angel's candles are the same closes by another route.
    if not angel_one.configured():
        report.failed["NSE"] = f"{sum(map(len, unfetched.values()))} day(s) unavailable"
        return
    for instrument_id, days in unfetched.items():
        inst = by_id[instrument_id].instrument
        if not inst.angel_token:
            continue
        try:
            candles = angel_one.daily_candles(inst.angel_token, min(days), max(days), c)
        except ProviderError as exc:
            report.failed[angel_one.PROVIDER] = exc.reason
            return
        wanted = set(days)
        batch = [
            _price(inst, nse_close_at(d), angel_one.PROVIDER, "CLOSE", close)
            for d, close in candles
            if d in wanted
        ]
        report.written[angel_one.PROVIDER] += _write_prices(db, batch, now)


def _fill_mf(db: Session, all_spans: list[Span], now, c, report: Report) -> None:
    mine = [s for s in all_spans if s.instrument.asset_class == "MF_IN"]
    fallback: dict[str, tuple[Decimal, dt.date]] | None = None
    for span in mine:
        inst = span.instrument
        if not inst.amfi_scheme_code:
            report.unresolved.append(inst.symbol)
            continue
        start = _start(db, span)
        if start > span.end:
            continue
        try:
            history = amfi.nav_history(inst.amfi_scheme_code, start, c)
        except ProviderError:
            # mfapi.in is a community mirror; AMFI's own file still has today's NAV.
            if fallback is None:
                codes = {
                    s.instrument.amfi_scheme_code for s in mine if s.instrument.amfi_scheme_code
                }
                fallback = amfi.latest_navs(codes, c)
            history = [
                (day, nav)
                for code, (nav, day) in fallback.items()
                if code == inst.amfi_scheme_code and day >= start
            ]
        batch = [
            _price(inst, nav_at(day), amfi.PROVIDER, "NAV", nav)
            for day, nav in history
            if day <= span.end
        ]
        report.written["AMFI"] += _write_prices(db, batch, now)


def _last_us_session(now: dt.datetime) -> dt.date:
    """The newest US session that has finished. A bar for a session still trading is not a
    close, and storing it as one would freeze a mid-day price into the history."""
    local = now.astimezone(NEW_YORK)
    return local.date() if local.time() >= dt.time(16, 15) else local.date() - dt.timedelta(days=1)


def _fill_us(db: Session, all_spans: list[Span], now, c, report: Report) -> None:
    mine = [s for s in all_spans if s.instrument.asset_class == "EQUITY_US"]
    if not mine:
        return
    if not twelve_data.configured():
        report.failed["US"] = "not configured"
        return
    finished = _last_us_session(now)
    for span in mine:
        start = _start(db, span)
        stop = min(span.end, finished)
        if start > stop:
            continue
        series = twelve_data.daily_series(span.instrument.symbol, start, c)
        batch = [
            _price(span.instrument, us_close_at(d), twelve_data.PROVIDER, "CLOSE", close)
            for d, close in series
            if start <= d <= stop
        ]
        report.written["US"] += _write_prices(db, batch, now)

    # The rate every US holding is valued through, from the first day one was held.
    usd_first = min(s.first for s in mine if s.instrument.currency == "USD")
    newest = db.execute(
        sa.select(sa.func.max(FxObservation.observed_at)).where(
            FxObservation.pair == USD_INR, FxObservation.source == FX_DAILY_SOURCE
        )
    ).scalar()
    start = (
        usd_first
        if newest is None
        else max(usd_first, newest.astimezone(dt.UTC).date() + dt.timedelta(days=1))
    )
    today_utc = now.astimezone(dt.UTC).date()
    if start >= today_utc:
        return
    series = twelve_data.daily_series("USD/INR", start, c)
    rows = [
        {"pair": USD_INR, "observed_at": fx_daily_at(d), "source": FX_DAILY_SOURCE, "rate": rate}
        for d, rate in series
        if start <= d < today_utc  # today's bar is still moving
    ]
    report.written["FX"] += _write_fx(db, rows, now)


def _resolve_coin(inst: Instrument, c, report: Report) -> str | None:
    if inst.coingecko_id:
        return inst.coingecko_id
    found = coingecko.search_id(inst.symbol, c)
    if found:
        inst.coingecko_id = found
    else:
        report.unresolved.append(inst.symbol)
    return found


def _fill_crypto(db: Session, all_spans: list[Span], now, c, report: Report) -> None:
    mine = [s for s in all_spans if s.instrument.asset_class == "CRYPTO"]
    if not mine:
        return
    if not coingecko.configured():
        report.failed["CRYPTO"] = "not configured"
        return
    today = now.astimezone(dt.UTC).date()
    # The plan's window is 365 days *including* today; a day outside it is refused.
    floor = today - dt.timedelta(days=coingecko.MAX_HISTORY_DAYS - 1)
    for span in mine:
        coin = _resolve_coin(span.instrument, c, report)
        if coin is None:
            continue
        start = _start(db, span, floor)
        if start > min(span.end, today):
            continue
        points = coingecko.daily_history(coin, (today - start).days + 1, c)
        batch = [
            _price(span.instrument, at, coingecko.PROVIDER, "CLOSE", price)
            for at, price in points
            if start <= at.date() <= span.end
        ]
        report.written["CRYPTO"] += _write_prices(db, batch, now)

    _fill_crypto_before_window(db, mine, floor, now, c, report)


def _oldest_close(db: Session, instrument_id: uuid.UUID) -> dt.date | None:
    oldest = db.execute(
        sa.select(sa.func.min(PriceObservation.observed_at)).where(
            PriceObservation.instrument_id == instrument_id,
            PriceObservation.kind.in_(("CLOSE", "NAV")),
        )
    ).scalar()
    return oldest.astimezone(dt.UTC).date() if oldest else None


def _as_of(series: list[tuple[dt.date, Decimal]], day: dt.date) -> Decimal | None:
    """The last value on or before `day` — a weekend uses Friday's rate, never Monday's."""
    found = None
    for d, value in series:
        if d > day:
            break
        found = value
    return found


def _fill_crypto_before_window(
    db: Session, mine: list[Span], floor: dt.date, now, c, report: Report
) -> None:
    """Days before CoinGecko's 365-day window, from Binance in USDT × that day's USD/INR.

    ⚠ Real prices, not an estimate between the purchase price and the first CoinGecko day.
    A straight line drawn between two known points would put a smooth, invented history under
    the value line and the time-weighted return, and both would read it as fact.

    Stamped the way CoinGecko stamps: the close of UTC day D at 00:00 UTC on D+1, so the two
    sources describe a day identically. Runs until the gap is closed, then asks nothing.
    """
    if not twelve_data.configured():
        return
    rates: list[tuple[dt.date, Decimal]] | None = None
    for span in mine:
        oldest = _oldest_close(db, span.instrument.id)
        gap_end = (oldest or floor) - dt.timedelta(days=1)
        if gap_end < span.first:
            continue
        if rates is None:
            rates = twelve_data.daily_series("USD/INR", span.first - dt.timedelta(days=7), c)
        pair = f"{span.instrument.symbol.upper()}USDT"
        try:
            closes = binance.daily_closes(
                pair, span.first - dt.timedelta(days=1), gap_end - dt.timedelta(days=1), c
            )
        except ProviderError as exc:
            report.failed[f"{binance.PROVIDER}:{span.instrument.symbol}"] = exc.reason
            continue
        batch = []
        for day, usdt in closes:
            at = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), dt.UTC)
            rate = _as_of(rates, day)
            if rate is None or not span.first <= at.date() <= gap_end:
                continue
            price = (usdt * rate).quantize(Decimal("0.000001"))
            batch.append(_price(span.instrument, at, binance.PROVIDER, "CLOSE", price))
        report.written[binance.PROVIDER] += _write_prices(db, batch, now)


# --- live prices --------------------------------------------------------------------------


def refresh_stale(
    db: Session,
    *,
    now: dt.datetime | None = None,
    c: httpx.Client | None = None,
) -> Report:
    """Fetch a live price for each open holding whose newest price is missing or stale.

    Fresh holdings cost nothing: opening the page twice in a minute makes one set of
    requests, and opening it in the evening after the closes are in makes none.
    """
    now = now or dt.datetime.now(dt.UTC)
    report = Report()
    held = [s for s in spans(db, now.astimezone(IST).date()) if s.is_open]
    if not held:
        return report
    marks = pricing.latest(db, [s.instrument.id for s in held], at=now)
    stale = [
        s.instrument
        for s in held
        if s.instrument.id not in marks or marks[s.instrument.id].is_stale
    ]

    own = c is None
    c = c or http.client()
    try:
        steps = (
            (angel_one.PROVIDER, angel_one.configured(), _live_nse),
            (coingecko.PROVIDER, coingecko.configured(), _live_crypto),
            (twelve_data.PROVIDER, twelve_data.configured(), _live_us),
            (amfi.PROVIDER, True, _live_mf),
        )
        for provider, configured, step in steps:
            if not configured or http.cooling(provider):
                continue
            try:
                if step(db, stale, held, now, c, report):
                    http.mark_up(provider)
                db.commit()
            except ProviderError as exc:
                db.rollback()
                http.mark_down(provider)
                report.failed[provider] = exc.reason
    finally:
        if own:
            c.close()
    return report


def _live_nse(db, stale, held, now, c, report: Report) -> bool:
    mine = [i for i in stale if i.exchange == "NSE" and i.angel_token]
    if not mine:
        return False
    ltp = angel_one.quote_ltp([i.angel_token for i in mine], c)
    batch = [
        _price(i, now, angel_one.PROVIDER, "LAST", ltp[i.angel_token])
        for i in mine
        if i.angel_token in ltp
    ]
    report.written[angel_one.PROVIDER] += _write_prices(db, batch, now)
    return True


def _live_crypto(db, stale, held, now, c, report: Report) -> bool:
    mine = [i for i in stale if i.asset_class == "CRYPTO" and i.coingecko_id]
    if not mine:
        return False
    quotes = coingecko.prices([i.coingecko_id for i in mine], c)
    batch = [
        _price(i, quotes[i.coingecko_id][1], coingecko.PROVIDER, "LAST", quotes[i.coingecko_id][0])
        for i in mine
        if i.coingecko_id in quotes
    ]
    report.written[coingecko.PROVIDER] += _write_prices(db, batch, now)
    return True


def _live_us(db, stale, held, now, c, report: Report) -> bool:
    did = False
    batch = []
    for inst in (i for i in stale if i.asset_class == "EQUITY_US"):
        q = twelve_data.quote(inst.symbol, c)
        # Outside market hours the quote IS the session's close; say so, so the history has it.
        if q.is_market_open:
            batch.append(_price(inst, now, twelve_data.PROVIDER, "LAST", q.price))
        else:
            batch.append(
                _price(inst, us_close_at(q.session), twelve_data.PROVIDER, "CLOSE", q.price)
            )
        did = True
    report.written[twelve_data.PROVIDER] += _write_prices(db, batch, now)

    if any(s.instrument.currency == "USD" for s in held):
        newest = db.execute(
            sa.select(sa.func.max(FxObservation.observed_at)).where(FxObservation.pair == USD_INR)
        ).scalar()
        if newest is None or now - newest > FX_STALE_AFTER:
            q = twelve_data.quote("USD/INR", c)
            report.written["FX"] += _write_fx(
                db,
                [{"pair": USD_INR, "observed_at": now, "source": FX_LIVE_SOURCE, "rate": q.price}],
                now,
            )
            did = True
    return did


def _live_mf(db, stale, held, now, c, report: Report) -> bool:
    mine = [i for i in stale if i.asset_class == "MF_IN" and i.amfi_scheme_code]
    if not mine:
        return False
    navs = amfi.latest_navs({i.amfi_scheme_code for i in mine}, c)
    batch = [
        _price(
            i,
            nav_at(navs[i.amfi_scheme_code][1]),
            amfi.PROVIDER,
            "NAV",
            navs[i.amfi_scheme_code][0],
        )
        for i in mine
        if i.amfi_scheme_code in navs
    ]
    report.written[amfi.PROVIDER] += _write_prices(db, batch, now)
    return True


# --- corporate actions --------------------------------------------------------------------


def share_changing_actions(
    db: Session, actions: list[nse.CorporateAction], *, today: dt.date | None = None
) -> list[tuple[Instrument, nse.CorporateAction]]:
    """Splits, bonuses and consolidations announced for a stock that is currently held."""
    today = today or dt.datetime.now(IST).date()
    # ⚠ `s.held`, not just `s.is_open`. A watched company has an open span because it needs
    # prices, and it has no position for a split to corrupt — announcing one would be a
    # warning about a holding that does not exist.
    held = [
        s.instrument
        for s in spans(db, today)
        if s.is_open and s.held and s.instrument.exchange == "NSE"
    ]
    out = []
    for action in actions:
        if not nse.changes_share_count(action):
            continue
        for inst in held:
            if nse.matches_company(action, [inst.name, inst.symbol, *(inst.aliases or ())]):
                out.append((inst, action))
    return out
