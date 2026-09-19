"""CoinGecko (Demo plan) — crypto in rupees, directly.

INR is asked for directly rather than USD converted at our own rate: CoinGecko's INR price is
what an Indian exchange would show, and converting would bake a second source's timing into
every crypto valuation.

⚠ **History is capped at 365 days on this plan** — a request for 1,000 was refused with error
10012. The window slides, so a day not fetched before it falls out is gone from this source.
Gap filling fetches everything it can on its first run for exactly that reason.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx

from app.config import settings
from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "COINGECKO"
ROOT = "https://api.coingecko.com/api/v3"
MAX_HISTORY_DAYS = 365


def configured() -> bool:
    return bool(settings.coingecko_api_key)


def _get(path: str, params: dict, c: httpx.Client | None) -> object:
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(
            ROOT + path,
            params=params,
            headers={"x-cg-demo-api-key": settings.coingecko_api_key, "accept": "application/json"},
        )
        r.raise_for_status()
        return r

    try:
        return http.json_decimal(http.with_retries(PROVIDER, attempt))
    finally:
        if own:
            c.close()


def prices(ids: list[str], c: httpx.Client | None = None) -> dict[str, tuple[Decimal, dt.datetime]]:
    """Current INR price and the time CoinGecko last updated it, per coin ID."""
    if not ids:
        return {}
    body = _get(
        "/simple/price",
        {"ids": ",".join(ids), "vs_currencies": "inr", "include_last_updated_at": "true"},
        c,
    )
    out = {}
    for coin, row in (body or {}).items():
        if "inr" not in row:
            continue
        at = row.get("last_updated_at")
        when = dt.datetime.fromtimestamp(int(at), dt.UTC) if at else dt.datetime.now(dt.UTC)
        out[coin] = (Decimal(row["inr"]), when)
    return out


def daily_history(
    coin: str, days: int, c: httpx.Client | None = None
) -> list[tuple[dt.datetime, Decimal]]:
    """Daily INR prices for the last `days` days (at most 365), each at 00:00 UTC.

    CoinGecko appends one more point — the price right now, at an arbitrary minute. It is
    dropped: it is not a daily observation, and the live refresh records current prices.
    """
    days = max(1, min(days, MAX_HISTORY_DAYS))
    body = _get(
        f"/coins/{coin}/market_chart",
        {"vs_currency": "inr", "days": str(days), "interval": "daily"},
        c,
    )
    if not isinstance(body, dict) or "prices" not in body:
        raise ProviderError(PROVIDER, "history response had no prices")
    out = []
    for ms, price in body["prices"]:
        when = dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC)
        if when.hour or when.minute or when.second:
            continue
        out.append((when, Decimal(price)))
    return out


def search_id(symbol: str, c: httpx.Client | None = None) -> str | None:
    """CoinGecko's ID for a ticker: exact symbol match, the highest-ranked by market cap.

    Tickers collide — there is more than one coin called JASMY-something — and the one a
    person holds is overwhelmingly the largest.
    """
    body = _get("/search", {"query": symbol}, c)
    coins = [
        x
        for x in (body or {}).get("coins", [])
        if str(x.get("symbol", "")).upper() == symbol.upper()
    ]
    if not coins:
        return None
    coins.sort(key=lambda x: x.get("market_cap_rank") or 10**9)
    return coins[0]["id"]
