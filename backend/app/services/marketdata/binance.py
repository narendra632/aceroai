"""Binance public market data — crypto history older than CoinGecko's free year.

CoinGecko's Demo plan returns 365 days and no more, but crypto held since November 2024
needs prices back to then, or the value line and the time-weighted return cannot start at
the first purchase. Binance publishes daily candles for years, keyless, on
`data-api.binance.vision` — its public market-data mirror, which serves regions the main API
refuses (the GCP VM is in one).

Prices are in USDT. The caller converts each day at that day's USD/INR rate. Measured on 17
overlapping days in Sept–Oct 2025, Binance × USD/INR matched CoinGecko's own INR price with a
median difference of 0.1% (largest 0.7%) for all four coins held — so the older history joins
the newer without a visible step.

Used only to fill the past; CoinGecko stays the source for everything in its window.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "BINANCE"
KLINES = "https://data-api.binance.vision/api/v3/klines"
_PAGE = 1000


def daily_closes(
    pair: str, start: dt.date, end: dt.date, c: httpx.Client | None = None
) -> list[tuple[dt.date, Decimal]]:
    """USDT close for each UTC day from `start` to `end`, oldest first.

    The day is the candle's own UTC date; its close is the last trade before midnight UTC.
    """
    own = c is None
    c = c or http.client()
    out: list[tuple[dt.date, Decimal]] = []
    cursor = dt.datetime.combine(start, dt.time(0, 0), dt.UTC)
    stop = dt.datetime.combine(end, dt.time(23, 59, 59), dt.UTC)
    try:
        while cursor <= stop:

            def attempt(since: dt.datetime = cursor) -> httpx.Response:
                r = c.get(
                    KLINES,
                    params={
                        "symbol": pair,
                        "interval": "1d",
                        "startTime": int(since.timestamp() * 1000),
                        "endTime": int(stop.timestamp() * 1000),
                        "limit": _PAGE,
                    },
                )
                r.raise_for_status()
                return r

            rows = http.json_decimal(http.with_retries(PROVIDER, attempt))
            if not isinstance(rows, list):
                raise ProviderError(PROVIDER, "klines response was not a list")
            for row in rows:
                day = dt.datetime.fromtimestamp(int(row[0]) / 1000, dt.UTC).date()
                out.append((day, Decimal(str(row[4]))))
            if len(rows) < _PAGE:
                break
            cursor = dt.datetime.combine(out[-1][0] + dt.timedelta(days=1), dt.time(0), dt.UTC)
    finally:
        if own:
            c.close()
    return out
