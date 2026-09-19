"""NSE's own published files — the daily close of record, and the corporate-action feed.

No key and no login. The bhavcopy is the exchange's official end-of-day file, so a close read
from it is the close, not a broker's report of it. Measured against Angel One on 18 Sep 2026:
identical to the paisa for all four held stocks, and its `FinInstrmId` column **is** Angel's
instrument token — which is how tokens are learned without Angel's 35 MB instrument master.

⚠ NSE is known to refuse datacenter IPs on its main website. These two files are served from
`nsearchives.nseindia.com`, which answered normally from a home connection; whether it does
from the GCP VM is checked there (tasks §8), and Angel's candles cover a day it will not serve.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "NSE"
BHAVCOPY = (
    "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
)
CORPORATE_ACTIONS = "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml"

#: NSE's archive refuses clients that do not look like a browser.
_HEADERS = {"User-Agent": "Mozilla/5.0 (personal portfolio; daily close)"}

#: Equity series whose close is a real traded price. BE/BZ are trade-for-trade segments a
#: stock can be moved into; it is still the same holding at the same price.
_SERIES = ("EQ", "BE", "BZ")


class NotPublished(Exception):
    """No file for that day: a holiday, a weekend, or not yet published. Not a failure."""


@dataclass(frozen=True)
class BhavRow:
    symbol: str
    isin: str
    token: str
    close: Decimal


@dataclass(frozen=True)
class CorporateAction:
    company: str
    purpose: str
    ex_date: dt.date | None


def bhavcopy(day: dt.date, c: httpx.Client | None = None) -> dict[str, BhavRow]:
    """Every equity's close on `day`, keyed by NSE symbol."""
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(BHAVCOPY.format(day=day), headers=_HEADERS)
        if r.status_code == 404:
            return r
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(PROVIDER, attempt)
    finally:
        if own:
            c.close()
    if r.status_code == 404:
        raise NotPublished(day)

    try:
        archive = zipfile.ZipFile(io.BytesIO(r.content))
        name = archive.namelist()[0]
        text = io.TextIOWrapper(archive.open(name), encoding="utf-8")
        rows = list(csv.DictReader(text))
    except (zipfile.BadZipFile, IndexError, UnicodeDecodeError, csv.Error):
        # NSE answers some missing days with an HTML page and a 200. That is "no file".
        raise NotPublished(day) from None

    out: dict[str, BhavRow] = {}
    for row in rows:
        series = (row.get("SctySrs") or "").strip()
        if series not in _SERIES:
            continue
        symbol = (row.get("TckrSymb") or "").strip()
        try:
            close = Decimal((row.get("ClsPric") or "").strip())
        except InvalidOperation:
            continue
        if not symbol or close <= 0:
            continue
        # EQ wins over BE/BZ if a symbol somehow appears in both.
        if symbol in out and series != "EQ":
            continue
        out[symbol] = BhavRow(
            symbol=symbol,
            isin=(row.get("ISIN") or "").strip(),
            token=(row.get("FinInstrmId") or "").strip(),
            close=close,
        )
    if not out:
        raise ProviderError(PROVIDER, "bhavcopy had no equity rows")
    return out


_EX_DATE = re.compile(r"Ex-Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})")
_PURPOSE = re.compile(r"PURPOSE:\s*([^|]+)")


def corporate_actions(c: httpx.Client | None = None) -> list[CorporateAction]:
    """The feed's current items. It names companies, not symbols — see `matches_company`."""
    own = c is None
    c = c or http.client()

    def attempt() -> httpx.Response:
        r = c.get(CORPORATE_ACTIONS, headers=_HEADERS)
        r.raise_for_status()
        return r

    try:
        r = http.with_retries(PROVIDER, attempt)
    finally:
        if own:
            c.close()
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise ProviderError(PROVIDER, "corporate-action feed was not XML") from None

    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        description = item.findtext("description") or ""
        company = title.split(" - Ex-Date")[0].strip()
        ex = _EX_DATE.search(title)
        purpose = _PURPOSE.search(description)
        out.append(
            CorporateAction(
                company=company,
                purpose=(purpose.group(1).strip() if purpose else description.strip()),
                ex_date=dt.datetime.strptime(ex.group(1), "%d-%b-%Y").date() if ex else None,
            )
        )
    return out


#: What changes the number of shares — and so moves the price without moving the value.
#: A dividend does not, and announcing every dividend would bury the actions that matter.
_SHARE_CHANGING = re.compile(r"SPLIT|SUB-DIVISION|BONUS|CONSOLIDATION", re.IGNORECASE)


def changes_share_count(action: CorporateAction) -> bool:
    return bool(_SHARE_CHANGING.search(action.purpose))


_NOISE = re.compile(r"\b(LIMITED|LTD|THE)\b")


def _normalise(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _NOISE.sub("", name.upper()))


def matches_company(action: CorporateAction, names: list[str]) -> bool:
    """Whether the feed's company is one of ours.

    Prefix, not equality: the feed says "Kaynes Technology India Limited" where the holding
    is named "Kaynes Technology". A prefix under eight characters is refused, so a short
    name cannot claim every company that happens to start with it.
    """
    company = _normalise(action.company)
    return any(len(n) >= 8 and company.startswith(n) for n in (_normalise(x) for x in names if x))
