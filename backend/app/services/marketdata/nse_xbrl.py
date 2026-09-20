"""Company financials, from the filings companies make to the exchange.

Every NSE-listed company files its results in XBRL — tagged, machine-readable numbers — and
NSE publishes those files at open URLs needing no key and no account. This is the only source
in the whole module where the figure the system uses and the figure the company filed are
**the same characters**, which is what makes the anti-fabrication rule enforceable rather than
aspirational: a thesis claiming "ROCE 18%" can be checked back to the line the company itself
submitted.

⚠ Four traps, every one found by calling this live on 20 Sep 2026 rather than by reading
documentation. Each would have produced confident, wrong numbers.

**The symbol must be URL-encoded.** NSE calls GE Vernova `GVT&D`. An unescaped `&` ends the
query parameter, so the request asks about a company called "GVT" and NSE answers, truthfully,
with nothing at all. It looks exactly like a company with no filings.

**Governance filings share the feed with financial ones.** They parse perfectly and contain no
financial line item whatsoever. Filtering on the type is not tidiness; without it the newest
"filing" for half these companies is a board-composition return.

**Context resolution is mandatory.** A March filing reports revenue for the QUARTER and for
the YEAR under the identical tag, distinguished only by which context each fact points at, and
the context ids are meaningless labels like `OneD` and `FourD`. Take the first and Kaynes' FY26
revenue is ₹1,243 Cr instead of the real figure — wrong by four, silently, on every ratio
derived from it.

**Banks speak a different language.** HDFC Bank files `INTEGRATED_FILING_BANKING_*` with
`InterestEarned` and `InterestExpended` where an industrial files revenue and finance costs.
There is no revenue-from-operations in a bank's filing at all. Helpfully the taxonomy is
declared in the FILENAME, so routing needs no guessing.

**What is stored is only what was extracted.** The file itself is parsed in memory and thrown
away — the module's storage budget forbids documents, and the extracted facts plus the literal
lines they came from are what the record needs.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.services.marketdata import http
from app.services.marketdata.http import ProviderError

PROVIDER = "NSE_XBRL"

ROOT = "https://www.nseindia.com"
#: Results filed under the Integrated Filing framework, which took over from Q4 FY25.
INTEGRATED = ROOT + "/api/integrated-filing-results?index=equities&symbol={symbol}"
#: The older results feed. ⚠ It STOPS at December 2024 — a pipeline built on it alone loses
#: every result from March 2025 onward and looks like a company that stopped reporting.
LEGACY = ROOT + "/api/corporates-financial-results?index=equities&period=Quarterly&symbol={symbol}"

#: NSE's API refuses a client that has not visited the site, exactly like the bhavcopy path.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ROOT + "/companies-listing/corporate-filings-financial-results",
}
_PRIME = (ROOT + "/", ROOT + "/companies-listing/corporate-filings-financial-results")

#: Which tag vocabulary a filing uses. Read from the filename, which states it.
INDAS, BANKING, UNKNOWN = "INDAS", "BANKING", "UNKNOWN"
_TAXONOMY = re.compile(r"INTEGRATED_FILING_(\w+?)_", re.IGNORECASE)

#: How long a reporting period runs, in days, with enough slack for 52/53-week years and the
#: odd filing that dates a quarter from the 1st to the 31st.
_QUARTER, _HALF, _YEAR = (80, 100), (170, 195), (350, 380)


class NotPublished(Exception):
    """No filing of this kind for this company. A young listing, not a failure."""


@dataclass(frozen=True)
class Filing:
    """One results filing, before it has been fetched."""

    symbol: str
    period_end: dt.date
    #: Consolidated covers subsidiaries; standalone does not. They are separate files and the
    #: choice must be recorded, because comparing one year's consolidated figure against
    #: another's standalone is a silent apples-to-oranges error.
    consolidated: bool
    url: str
    taxonomy: str

    @property
    def is_annual(self) -> bool:
        """⚠ Only the March filing carries the balance sheet and the cash flow statement.

        Quarterly files hold the profit and loss alone, so anything needing borrowings, equity
        or operating cash flow — which is most of the quality score — exists once a year."""
        return self.period_end.month == 3


@dataclass(frozen=True)
class Fact:
    """One tagged number, with the period it belongs to and the literal text it came from."""

    name: str
    value: Decimal
    period_start: dt.date | None
    period_end: dt.date
    #: QUARTER · HALF · YEAR · POINT (a balance-sheet instant)
    period_kind: str
    #: ⚠ The filed characters, kept verbatim. This is what an echo check compares against, and
    #: a paraphrase of it would defeat the entire point of having one.
    excerpt: str
    #: ⚠ True where this figure describes an EARLIER period than the filing reports on — the
    #: prior-year column every results statement carries. Worth keeping rather than
    #: discarding: legacy March filings tag the year's profit and loss only as a fourth
    #: quarter, so for years before the Integrated Filing framework the comparative in the
    #: NEXT year's filing is the only place the annual figure appears at all.
    is_comparative: bool = False


def client(c: httpx.Client | None = None) -> httpx.Client:
    """A primed client. NSE's API refuses one that has not visited the site first."""
    own = c is None
    c = c or http.client()
    if own:
        c.headers.update(_HEADERS)
        for url in _PRIME:
            try:
                c.get(url, timeout=20)
            except httpx.HTTPError:
                # Priming is best-effort; the request below reports the real failure.
                pass
    return c


def _rows(c: httpx.Client, url: str, symbol: str) -> list[dict]:
    # ⚠ quote(), not an f-string. `GVT&D` unescaped ends the query parameter.
    target = url.format(symbol=urllib.parse.quote(symbol, safe=""))

    def attempt() -> httpx.Response:
        r = c.get(target, headers=_HEADERS)
        r.raise_for_status()
        return r

    r = http.with_retries(PROVIDER, attempt)
    try:
        body = r.json()
    except ValueError:
        raise ProviderError(PROVIDER, "the filings index was not JSON") from None
    if isinstance(body, dict):
        body = body.get("resultBody") or body.get("data") or []
    return [row for row in body if isinstance(row, dict)]


def _parse_day(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def filings(symbol: str, c: httpx.Client | None = None) -> list[Filing]:
    """Every financial filing NSE lists for a company, newest first.

    Both feeds are read and merged: the legacy one stops at December 2024 and the integrated
    one starts there, so either alone has a hole where the other's coverage is.
    """
    own = c is None
    c = client(c)
    try:
        rows = []
        for url in (INTEGRATED, LEGACY):
            try:
                rows.extend(_rows(c, url, symbol))
            except ProviderError:
                # One feed being unreachable is not both. The other still has history.
                continue
    finally:
        if own:
            c.close()

    out: list[Filing] = []
    seen: set[str] = set()
    for row in rows:
        kind = str(row.get("type") or row.get("type_Sub") or "")
        # ⚠ Governance filings sit in the same feed, parse cleanly, and carry no financial
        # line item at all.
        if "overnance" in kind:
            continue
        url_value = row.get("xbrl")
        if not (isinstance(url_value, str) and url_value.startswith("http")):
            continue
        if url_value in seen:
            continue
        period_end = _parse_day(row.get("qe_Date") or row.get("toDate") or row.get("period"))
        if period_end is None:
            continue
        seen.add(url_value)
        match = _TAXONOMY.search(url_value.rsplit("/", 1)[-1])
        out.append(
            Filing(
                symbol=symbol,
                period_end=period_end,
                consolidated=str(row.get("consolidated") or "").lower().startswith("cons"),
                url=url_value,
                taxonomy=(match.group(1).upper() if match else INDAS),
            )
        )
    return sorted(out, key=lambda f: (f.period_end, f.consolidated), reverse=True)


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _period_kind(start: dt.date | None, end: dt.date) -> str:
    if start is None:
        return "POINT"
    days = (end - start).days + 1
    if _QUARTER[0] <= days <= _QUARTER[1]:
        return "QUARTER"
    if _HALF[0] <= days <= _HALF[1]:
        return "HALF"
    if _YEAR[0] <= days <= _YEAR[1]:
        return "YEAR"
    return "OTHER"


def _contexts(root: ET.Element) -> dict[str, tuple[dt.date | None, dt.date]]:
    """Context id → the period it covers, for contexts with **no dimensions**.

    ⚠ Dimensional contexts are dropped deliberately. A filing reports segment revenue and
    segment assets against the same tags, split by business line; including them would let a
    single segment's revenue be read as the company's, which is a large and plausible wrong
    number. Only the undimensioned entity context describes the whole company.
    """
    out: dict[str, tuple[dt.date | None, dt.date]] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        dimensional = any(_local(el.tag) in ("explicitMember", "typedMember") for el in ctx.iter())
        if dimensional:
            continue
        start = end = None
        for el in ctx.iter():
            name = _local(el.tag)
            if name == "startDate":
                start = _parse_day(el.text)
            elif name == "endDate":
                end = _parse_day(el.text)
            elif name == "instant":
                end = _parse_day(el.text)
        if end is None:
            continue
        ctx_id = ctx.get("id")
        if ctx_id:
            out[ctx_id] = (start, end)
    return out


def facts(
    filing: Filing, c: httpx.Client | None = None, *, comparatives: bool = True
) -> list[Fact]:
    """Every numeric fact in a filing, resolved to the period it actually describes.

    ⚠ Prior-year comparatives are KEPT, flagged as such. Discarding them looked tidy and cost
    a year of history per company: a legacy March filing carries the year-end balance sheet
    but tags its profit and loss as a fourth quarter, so FY24 arrived with equity and
    borrowings and no revenue at all. The comparative column in the FY25 filing is where that
    year's annual figures actually live.

    Where the same period appears in two filings the later statement of it wins, which is also
    the right answer when a company has restated.
    """
    own = c is None
    c = client(c)

    def attempt() -> httpx.Response:
        r = c.get(filing.url, headers=_HEADERS)
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
        raise ProviderError(PROVIDER, "the filing was not parseable XML") from None

    periods = _contexts(root)
    out: list[Fact] = []
    for el in root.iter():
        text = (el.text or "").strip()
        if not text:
            continue
        ctx_id = el.get("contextRef")
        if not ctx_id or ctx_id not in periods:
            continue
        try:
            value = Decimal(text)
        except InvalidOperation:
            continue
        start, end = periods[ctx_id]
        if end > filing.period_end:
            continue  # a forward-looking context; nothing reports on a period not yet ended
        if end != filing.period_end and not comparatives:
            continue
        name = _local(el.tag)
        out.append(
            Fact(
                name=name,
                value=value,
                period_start=start,
                period_end=end,
                period_kind=_period_kind(start, end),
                is_comparative=end != filing.period_end,
                # ⚠ Rebuilt rather than sliced out of the source, because ElementTree does not
                # keep byte offsets. It reproduces the filed tag, context and value exactly,
                # which is what an echo check needs.
                excerpt=f'<{name} contextRef="{ctx_id}">{text}</{name}>',
            )
        )
    if not out:
        raise NotPublished(filing.url)
    return out


def periods_in(facts_: list[Fact]) -> list[dt.date]:
    """Every distinct period end a filing reports on, newest first."""
    return sorted({f.period_end for f in facts_}, reverse=True)


def pick(
    facts_: list[Fact], name: str, kind: str, *, period_end: dt.date | None = None
) -> Fact | None:
    """One fact by tag and period kind. None when the filing does not carry it.

    ⚠ None is a real answer and must stay one. A missing input scores *unknown*, never zero —
    a company rejected because a filing had not been ingested yet is a failure of the pipeline
    wearing the clothes of a judgement about the business.
    """
    for fact in facts_:
        if fact.name != name or fact.period_kind != kind:
            continue
        if period_end is not None and fact.period_end != period_end:
            continue
        return fact
    return None


def preferred(filings_: list[Filing]) -> list[Filing]:
    """One filing per period: consolidated where it exists, standalone where it does not.

    ⚠ Not a convenience. GE Vernova T&D files **only standalone** — it has no subsidiaries, so
    no consolidated statement exists to file. Requiring consolidated would leave the
    portfolio's widest-bottleneck holding with no financials whatsoever, and the failure would
    read as "this company does not report" rather than "this filter is wrong".

    The choice is recorded on every row that results, because comparing one year's
    consolidated figure against another's standalone is a silent apples-to-oranges error.
    """
    best: dict[dt.date, Filing] = {}
    for filing in filings_:
        held = best.get(filing.period_end)
        if held is None or (filing.consolidated and not held.consolidated):
            best[filing.period_end] = filing
    return sorted(best.values(), key=lambda f: f.period_end, reverse=True)


def annual(filings_: list[Filing]) -> list[Filing]:
    """The March filings, newest first — the only ones carrying a balance sheet and cash flow."""
    return [f for f in preferred(filings_) if f.is_annual]
