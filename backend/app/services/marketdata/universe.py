"""Every company listed on the exchange — the vocabulary the reader recognises names with.

NSE publishes its complete equity list as one CSV: symbol, legal name, series, ISIN, listing
date. No key, no login, 183 KB, **2,595 companies** as of 21 Sep 2026.

⚠ **This file is what makes discovery possible without letting a model invent names.** The
obvious way to find a company nobody is tracking is to ask a model what companies were
discussed — and a model that can produce names can produce ones that do not exist, which
would put fictional companies into the very table the source-attribution measure counts. With
the exchange's own list as the vocabulary, recognition stays exactly as deterministic for a
company never heard of as it is for one already held.

⚠ **The list is a fact about the exchange, not about the portfolio.** A company being listed
says nothing about whether it is worth owning, and nothing here scores, ranks or filters. It
answers one question: *is this string the name of a real listed company, and which one.*
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "NSE_UNIVERSE"
EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

_HEADERS = {"User-Agent": "Mozilla/5.0 (personal portfolio; listed company list)"}

#: Series whose members are ordinary traded equity. BE and BZ are trade-for-trade segments a
#: stock can be moved into; it is the same company, so it stays in the vocabulary.
SERIES = ("EQ", "BE", "BZ")

#: ⚠ A floor, not a guess. The live file carried 2,595 companies; a fetch that returns a
#: fraction of that is a truncated download or a changed format, and silently replacing the
#: vocabulary with a short one would make the reader blind to most of the exchange without
#: anything appearing to fail.
MIN_PLAUSIBLE = 1500


@dataclass(frozen=True)
class Listed:
    """One listed company, as the exchange names it."""

    symbol: str
    name: str
    series: str
    isin: str | None
    listed_on: dt.date | None
    #: As the exchange states it. None where the column is blank or not a positive number.
    face_value: Decimal | None = None


def _face(raw: str) -> Decimal | None:
    """A positive face value, or None. ⚠ Zero is not a face value; it is the gap this fills."""
    try:
        value = Decimal((raw or "").strip())
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _date(raw: str) -> dt.date | None:
    raw = (raw or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def fetch(c: httpx.Client | None = None) -> list[Listed]:
    """The exchange's current equity list.

    ⚠ Column names in this file carry **leading spaces** (`' SERIES'`, `' ISIN NUMBER'`),
    which is why every header is stripped before use rather than read literally. A reader that
    trusted the header text would find every field except SYMBOL missing, and would record a
    universe of names with no ISINs rather than failing.
    """
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(EQUITY_LIST, headers=_HEADERS)
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(PROVIDER, attempt)
    finally:
        if own:
            c.close()

    reader = csv.DictReader(io.StringIO(r.text))
    out: list[Listed] = []
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        symbol, name = row.get("SYMBOL", ""), row.get("NAME OF COMPANY", "")
        series = row.get("SERIES", "")
        if not symbol or not name or series not in SERIES:
            continue
        out.append(
            Listed(
                symbol=symbol,
                name=name,
                series=series,
                isin=row.get("ISIN NUMBER") or None,
                listed_on=_date(row.get("DATE OF LISTING", "")),
                face_value=_face(row.get("FACE VALUE", "")),
            )
        )

    if len(out) < MIN_PLAUSIBLE:
        raise ProviderError(PROVIDER, f"the equity list returned only {len(out)} companies")
    return out
