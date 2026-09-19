"""Twelve Data (Basic plan) — US equities and the USD/INR rate.

The key travels in an `Authorization: apikey …` header, not in the URL, so it can never end
up in a log line that records a request address.

⚠ Twelve Data reports most errors as **HTTP 200** with `{"status": "error", "code": 429}` in
the body. Checking the status code alone would store an error message as a price-less
success, so every response's `status` field is checked.

Budget: 800 credits a day, 8 a minute. One credit per call here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.config import settings
from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "TWELVE_DATA"
ROOT = "https://api.twelvedata.com"


def configured() -> bool:
    return bool(settings.twelve_data_api_key)


@dataclass(frozen=True)
class Quote:
    price: Decimal
    #: The session the price belongs to (exchange-local date).
    session: dt.date
    is_market_open: bool


def _get(path: str, params: dict, c: httpx.Client | None) -> dict:
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(
            ROOT + path,
            params=params,
            headers={"Authorization": f"apikey {settings.twelve_data_api_key}"},
        )
        r.raise_for_status()
        return r

    try:
        body = http.json_decimal(http.with_retries(PROVIDER, attempt))
    finally:
        if own:
            c.close()
    if not isinstance(body, dict) or body.get("status") == "error":
        code = body.get("code") if isinstance(body, dict) else None
        raise ProviderError(PROVIDER, f"error {code or 'response'}")
    return body


def quote(symbol: str, c: httpx.Client | None = None) -> Quote:
    body = _get("/quote", {"symbol": symbol}, c)
    try:
        return Quote(
            price=Decimal(str(body["close"])),
            session=dt.date.fromisoformat(str(body["datetime"])[:10]),
            is_market_open=bool(body.get("is_market_open")),
        )
    except (KeyError, ValueError, ArithmeticError):
        raise ProviderError(PROVIDER, "quote missing fields") from None


def daily_series(
    symbol: str, start: dt.date, c: httpx.Client | None = None
) -> list[tuple[dt.date, Decimal]]:
    """Daily closes from `start`, oldest first. Includes today's bar if one exists —
    the caller drops a session that has not finished."""
    body = _get(
        "/time_series",
        {
            "symbol": symbol,
            "interval": "1day",
            "start_date": start.isoformat(),
            "outputsize": "5000",
            "order": "asc",
        },
        c,
    )
    out = []
    for row in body.get("values") or []:
        out.append((dt.date.fromisoformat(str(row["datetime"])[:10]), Decimal(str(row["close"]))))
    return sorted(out)
