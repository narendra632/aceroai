"""Mutual fund NAVs — AMFI's own daily file, and history from mfapi.in.

AMFI publishes every scheme's NAV in one text file, once a day; that is the source of truth.
mfapi.in is a free community mirror of the same data with per-scheme history, used only for
history, because AMFI's own historical interface is a form, not an API.

No key for either. A fund has one NAV a day, so there is no live price to fetch.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "AMFI"
NAV_ALL = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI = "https://api.mfapi.in/mf/{code}"


def _fetch(url: str, c: httpx.Client | None) -> httpx.Response:
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(url)
        r.raise_for_status()
        return r

    try:
        return http.with_retries(PROVIDER, attempt)
    finally:
        if own:
            c.close()


def latest_navs(
    codes: set[str], c: httpx.Client | None = None
) -> dict[str, tuple[Decimal, dt.date]]:
    """Today's NAV for each scheme code asked for.

    ⚠ Parsed from both ends of the line: the code is the first field and NAV and date are the
    last two. The scheme name between them has been seen split across several fields
    ("HDFC Mid Cap Fund;Direct Plan;Growth Option"), so counting fields from the left breaks.
    """
    text = _fetch(NAV_ALL, c).text
    out: dict[str, tuple[Decimal, dt.date]] = {}
    for line in text.splitlines():
        fields = [f.strip() for f in line.split(";")]
        if len(fields) < 4 or fields[0] not in codes:
            continue
        try:
            nav = Decimal(fields[-2])
            day = dt.datetime.strptime(fields[-1], "%d-%b-%Y").date()
        except (InvalidOperation, ValueError):
            continue  # "N.A." and friends
        if nav > 0:
            out[fields[0]] = (nav, day)
    return out


def nav_history(
    code: str, start: dt.date, c: httpx.Client | None = None
) -> list[tuple[dt.date, Decimal]]:
    """Daily NAVs on or after `start`, oldest first."""
    body = http.json_decimal(_fetch(MFAPI.format(code=code), c))
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise ProviderError(PROVIDER, "history response had no data")
    out = []
    for row in rows:
        try:
            day = dt.datetime.strptime(str(row["date"]), "%d-%m-%Y").date()
            nav = Decimal(str(row["nav"]))
        except (KeyError, ValueError, InvalidOperation):
            continue
        if day >= start and nav > 0:
            out.append((day, nav))
    return sorted(out)
