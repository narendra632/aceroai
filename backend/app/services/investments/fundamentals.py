"""Turning filings into figures the quality score can use.

One job: read a company's results filings, pull out the line items, and store each one beside
the literal text it was filed as. Nothing here judges anything — that is `scoring`. Nothing
here invents anything either: a line item a filing does not carry is **absent**, and absence
travels all the way to the score as *unknown*.

⚠ **Missing is not zero, and the distinction is load-bearing.** A company whose filing has not
been read yet, or which files a line item its industry does not use, must not score badly for
it. Treating a missing input as a bad one is how a genuinely good business gets rejected for a
reason that has nothing to do with the business, and the rejection looks exactly like a
judgement.

⚠ **Two taxonomies, because a bank is not a small industrial.** HDFC Bank files
`InterestEarned` and `InterestExpended` where Kaynes files revenue and finance costs, and
there is no revenue-from-operations in a bank's filing at all. Borrowings are a bank's raw
material rather than its leverage. So the maps below are separate, and the metrics a bank
simply does not have are absent rather than zeroed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Fundamental, Instrument, SourceItem
from app.services.marketdata import nse_xbrl
from app.services.marketdata.http import ProviderError

ZERO = Decimal(0)

#: How many years of history the quality score needs. ⚠ Five, because the return-on-equity
#: test asks for "≥15% in at least three of the last five years" and the retained-earnings
#: test spans five. Fewer years does not make the test stricter — it makes it unanswerable.
HISTORY_YEARS = 5

#: The line items a normal company files, mapped to what this module calls them.
#: Left is the XBRL tag; right is `(metric_key, period_kind, unit)`.
INDAS_MAP: dict[str, tuple[str, str, str]] = {
    "RevenueFromOperations": ("revenue", "YEAR", "inr"),
    "OtherIncome": ("other_income", "YEAR", "inr"),
    "ProfitBeforeTax": ("pbt", "YEAR", "inr"),
    "ProfitLossForPeriod": ("pat", "YEAR", "inr"),
    "ProfitOrLossAttributableToOwnersOfParent": ("pat_owners", "YEAR", "inr"),
    "FinanceCosts": ("finance_costs", "YEAR", "inr"),
    "DepreciationDepletionAndAmortisationExpense": ("dep_amort", "YEAR", "inr"),
    "CashFlowsFromUsedInOperatingActivities": ("ocf", "YEAR", "inr"),
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": (
        "capex",
        "YEAR",
        "inr",
    ),
    "EquityAttributableToOwnersOfParent": ("equity", "POINT", "inr"),
    "EquityShareCapital": ("share_capital", "POINT", "inr"),
    "OtherEquity": ("other_equity", "POINT", "inr"),
    "BorrowingsCurrent": ("borrowings_current", "POINT", "inr"),
    "BorrowingsNoncurrent": ("borrowings_noncurrent", "POINT", "inr"),
    "CashAndCashEquivalents": ("cash", "POINT", "inr"),
    "Inventories": ("inventories", "POINT", "inr"),
    "TradeReceivablesCurrent": ("receivables", "POINT", "inr"),
    "TradePayablesCurrent": ("payables", "POINT", "inr"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_capital", "YEAR", "inr"),
    "FaceValueOfEquityShareCapital": ("face_value", "YEAR", "inr"),
}

#: What a BANK files instead. ⚠ Deliberately short. The quality score's cash-conversion,
#: net-debt and return-on-capital tests measure things a bank does not have, so the metrics
#: that would feed them are simply not collected — and `scoring` reports them unknown rather
#: than failing the bank on arithmetic that does not apply to it.
BANKING_MAP: dict[str, tuple[str, str, str]] = {
    "InterestEarned": ("interest_earned", "YEAR", "inr"),
    "OtherIncome": ("other_income", "YEAR", "inr"),
    "Income": ("revenue", "YEAR", "inr"),
    "InterestExpended": ("interest_expended", "YEAR", "inr"),
    "OperatingProfitBeforeProvisionAndContingencies": ("operating_profit", "YEAR", "inr"),
    "ProfitLossFromOrdinaryActivitiesBeforeTax": ("pbt", "YEAR", "inr"),
    "ProfitLossForThePeriod": ("pat", "YEAR", "inr"),
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates": (
        "pat_owners",
        "YEAR",
        "inr",
    ),
    "CashFlowsFromUsedInOperatingActivities": ("ocf", "YEAR", "inr"),
    "PaidUpValueOfEquityShareCapital": ("paid_up_capital", "YEAR", "inr"),
    "FaceValueOfEquityShareCapital": ("face_value", "YEAR", "inr"),
    # ⚠ A bank files its equity too, just not where an industrial does — `Capital` and
    # `ReservesAndSurplus` rather than `EquityAttributableToOwnersOfParent`. Without these the
    # one quality measure that DOES describe a bank, return on equity, was reported unknown,
    # and the portfolio's anchor holding was left with a score resting on a single component.
    "Capital": ("share_capital", "POINT", "inr"),
    "ReservesAndSurplus": ("other_equity", "POINT", "inr"),
}

MAPS = {nse_xbrl.INDAS: INDAS_MAP, nse_xbrl.BANKING: BANKING_MAP}


def fiscal_period(period_end: dt.date) -> str:
    """`FY26` for the year to 31 March 2026, `FY26Q1` for the quarter to 30 June 2025.

    India's financial year is named for the year it ENDS in and runs April to March, so a
    quarter ending in June belongs to the year ending the following March.
    """
    if period_end.month == 3:
        return f"FY{period_end.year % 100:02d}"
    fy = period_end.year + (1 if period_end.month > 3 else 0)
    quarter = {6: 1, 9: 2, 12: 3}.get(period_end.month)
    return f"FY{fy % 100:02d}Q{quarter}" if quarter else f"FY{fy % 100:02d}P{period_end.month}"


@dataclass
class Ingested:
    """What one sync did, in counts a job row can carry."""

    filings_read: int = 0
    figures_written: int = 0
    skipped_existing: int = 0
    unreadable: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.unreadable is None:
            self.unreadable = []

    def detail(self) -> dict:
        return {
            "filings": self.filings_read,
            "figures": self.figures_written,
            "already_had": self.skipped_existing,
            "unreadable": self.unreadable[:5],
        }


def _best_map(
    facts: list[nse_xbrl.Fact], period_end: dt.date | None = None
) -> tuple[dict | None, list[tuple[str, str, nse_xbrl.Fact]]]:
    """Choose the tag vocabulary by what the file actually contains.

    ⚠ The filename declares the taxonomy for filings made under the Integrated Filing
    framework, and says nothing for the years before it. Trusting the filename alone read every
    pre-2025 bank filing with an industrial's tag map and found nothing at all — a bank with
    two years of history instead of five, reported as "no known tags" rather than as a wrong
    guess. Matching on content is self-correcting and needs no list of naming conventions.
    """
    best_name, best_kept = None, []
    for name, mapping in MAPS.items():
        kept = [
            (metric, unit, fact)
            for tag, (metric, kind, unit) in mapping.items()
            if (fact := nse_xbrl.pick(facts, tag, kind, period_end=period_end)) is not None
        ]
        if len(kept) > len(best_kept):
            best_name, best_kept = name, kept
    return (MAPS[best_name] if best_name else None), best_kept


def _external_id(filing: nse_xbrl.Filing, period_end: dt.date | None = None) -> str:
    """One id per (file, period).

    ⚠ A filing states figures for more than one period: its own, and the prior year in the
    comparative column. Those are two different claims made in one document, so they are two
    records — which also keeps each excerpt small enough to hold every line it cites, rather
    than truncating a document's worth of facts into a 2 KB field and losing the evidence for
    whichever figures happened to come last.
    """
    name = filing.url.rsplit("/", 1)[-1]
    if period_end is None or period_end == filing.period_end:
        return name
    return f"{name}#{fiscal_period(period_end)}"


def existing_source(
    db: Session, filing: nse_xbrl.Filing, period_end: dt.date | None = None
) -> SourceItem | None:
    """The record of this filing's statement about one period, if already parsed."""
    return db.execute(
        sa.select(SourceItem).where(
            SourceItem.source == nse_xbrl.PROVIDER,
            SourceItem.external_id == _external_id(filing, period_end),
        )
    ).scalar_one_or_none()


def already_read(db: Session, filing: nse_xbrl.Filing) -> bool:
    """Whether this exact filing has been parsed before. Makes the sync cheap to re-run."""
    return existing_source(db, filing) is not None


def _store_source(
    db: Session,
    instrument: Instrument,
    filing: nse_xbrl.Filing,
    kept: list[nse_xbrl.Fact],
    period_end: dt.date,
) -> SourceItem:
    """Write the document record, carrying the literal lines the figures came from.

    ⚠ The excerpt is capped by the database at 2 KB and truncated here at a LINE boundary, so
    what is stored is always whole tagged lines. A half-line would fail an echo check against
    a figure that is perfectly correct, which is the worst kind of false alarm: it looks like
    the model fabricated something.
    """
    lines: list[str] = []
    size = 0
    for fact in kept:
        if size + len(fact.excerpt) + 1 > 2000:
            break
        lines.append(fact.excerpt)
        size += len(fact.excerpt) + 1
    excerpt = "\n".join(lines)

    row = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=instrument.id,
        source=nse_xbrl.PROVIDER,
        external_id=_external_id(filing, period_end),
        url=filing.url,
        title=(
            f"{instrument.symbol} {fiscal_period(period_end)} "
            f"{'consolidated' if filing.consolidated else 'standalone'}"
            + (
                f", as stated in the {fiscal_period(filing.period_end)} filing"
                if period_end != filing.period_end
                else ""
            )
        ),
        # ⚠ When the figure was STATED, not the period it describes. A restatement in a later
        # filing is the more recent claim about that year, and readers prefer the newest.
        published_at=dt.datetime.combine(filing.period_end, dt.time(0, 0), dt.UTC),
        fetched_at=dt.datetime.now(dt.UTC),
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        excerpt=excerpt,
        extraction={
            "taxonomy": filing.taxonomy,
            "consolidated": filing.consolidated,
            "describes": fiscal_period(period_end),
            "comparative": period_end != filing.period_end,
        },
    )
    db.add(row)
    db.flush()
    return row


def _write_figures(
    db: Session,
    instrument: Instrument,
    filing: nse_xbrl.Filing,
    source: SourceItem,
    kept: list[tuple[str, str, nse_xbrl.Fact]],
    period_end: dt.date,
) -> int:
    """Insert the figures, doing nothing where they already exist."""
    if not kept:
        return 0
    rows = [
        {
            "instrument_id": instrument.id,
            "fiscal_period": fiscal_period(period_end),
            "metric_key": metric,
            "source_item_id": source.id,
            "value": fact.value,
            "unit": unit,
            "period_end": period_end,
            "consolidated": filing.consolidated,
            "taxonomy": filing.taxonomy,
        }
        for metric, unit, fact in kept
    ]
    # ⚠ `.returning()`, not `rowcount`. A batched INSERT reports -1 for the statement rather
    # than the number of rows it actually wrote, so the count came back negative — which looked
    # like a failure and was in fact a successful write reported by a driver detail.
    stmt = (
        insert(Fundamental).values(rows).on_conflict_do_nothing().returning(Fundamental.metric_key)
    )
    return len(db.execute(stmt).all())


def sync_instrument(
    db: Session,
    instrument: Instrument,
    *,
    years: int = HISTORY_YEARS,
    c: httpx.Client | None = None,
    today: dt.date | None = None,
    reparse: bool = False,
) -> Ingested:
    """Read this company's annual filings and store what they report.

    `reparse` re-reads filings already on file. ⚠ Needed because the tag maps GROW: adding
    `Capital` and `ReservesAndSurplus` so a bank's return on equity could be computed reached
    only filings not yet read, and every bank filing already stored kept its gap silently. The
    figures are written against the ORIGINAL document record, so the provenance of a figure is
    still the filing it came from and no second record of the same document is created.

    Annual filings only. ⚠ Quarterly files carry the profit and loss alone — no balance sheet,
    no cash flow — so everything the quality score needs beyond revenue and profit exists once
    a year. Fetching four files to obtain one file's worth of usable figures would cost four
    times as much and add nothing.
    """
    today = today or dt.date.today()
    report = Ingested()
    if instrument.exchange not in ("NSE", "BSE"):
        return report

    try:
        found = nse_xbrl.filings(instrument.symbol, c)
    except ProviderError as exc:
        report.unreadable.append(f"{instrument.symbol}: {exc.reason}")
        return report

    cutoff = dt.date(today.year - years - 1, 1, 1)
    wanted = [f for f in nse_xbrl.annual(found) if f.period_end >= cutoff][:years]

    for filing in wanted:
        if existing_source(db, filing) is not None and not reparse:
            report.skipped_existing += 1
            continue
        try:
            facts = nse_xbrl.facts(filing, c)
        except (ProviderError, nse_xbrl.NotPublished):
            report.unreadable.append(f"{instrument.symbol} {filing.period_end}")
            continue

        read_any = False
        # ⚠ A filing states figures for its own period AND for the prior year alongside. Both
        # are stored, because for years before the Integrated Filing framework the comparative
        # column is the ONLY place the annual profit and loss appears — the March file of the
        # day tagged its year as a fourth quarter and carried a balance sheet with no revenue.
        for period_end in nse_xbrl.periods_in(facts):
            if period_end.month != 3:
                continue  # an annual figure, or nothing: quarters are not scored
            known = existing_source(db, filing, period_end)
            if known is not None and not reparse:
                continue

            mapping, kept = _best_map(facts, period_end)
            if mapping is None or not kept:
                continue
            source = known or _store_source(
                db, instrument, filing, [f for _, _, f in kept], period_end
            )
            report.figures_written += _write_figures(
                db, instrument, filing, source, kept, period_end
            )
            read_any = read_any or known is None

        if read_any:
            report.filings_read += 1
        else:
            report.skipped_existing += 1

    return report


def sync(
    db: Session,
    *,
    years: int = HISTORY_YEARS,
    c: httpx.Client | None = None,
    reparse: bool = False,
) -> Ingested:
    """Read filings for every tracked Indian equity, held or watched.

    Watched companies matter as much as held ones here: the whole reason to watch a company is
    to be able to say whether today is a sensible day to buy it, and that question is
    unanswerable without its numbers.
    """
    total = Ingested()
    own = c is None
    c = nse_xbrl.client(c)
    try:
        instruments = db.execute(
            sa.select(Instrument)
            .where(
                Instrument.deleted_at.is_(None),
                Instrument.is_tracked.is_(True),
                Instrument.asset_class == "EQUITY_IN",
            )
            .order_by(Instrument.symbol)
        ).scalars()
        for instrument in instruments:
            one = sync_instrument(db, instrument, years=years, c=c, reparse=reparse)
            total.filings_read += one.filings_read
            total.figures_written += one.figures_written
            total.skipped_existing += one.skipped_existing
            total.unreadable.extend(one.unreadable)
            db.commit()
    finally:
        if own:
            c.close()
    return total


# --- reading it back -----------------------------------------------------------------------


@dataclass(frozen=True)
class Figure:
    """One reported number, with everything needed to cite it."""

    metric: str
    fiscal_period: str
    period_end: dt.date
    value: Decimal
    unit: str
    consolidated: bool
    source_item_id: uuid.UUID


def series(db: Session, instrument_id: uuid.UUID, metric: str, *, limit: int = 8) -> list[Figure]:
    """One metric over time, newest first.

    ⚠ Where a period has both a consolidated and a standalone figure the consolidated one
    wins, and only one per period is returned. Mixing bases inside a single series produces a
    trend that is partly a change in the business and partly a change in what was counted.
    """
    rows = db.execute(
        sa.select(Fundamental)
        .join(SourceItem, Fundamental.source_item_id == SourceItem.id)
        .where(Fundamental.instrument_id == instrument_id, Fundamental.metric_key == metric)
        .order_by(
            Fundamental.period_end.desc(),
            Fundamental.consolidated.desc(),
            # ⚠ The most recent STATEMENT of a figure wins, not the earliest. Where a year
            # appears both in its own filing and as a comparative in a later one, the later
            # one is the company's current word on it — which is exactly what a restatement is.
            SourceItem.published_at.desc(),
        )
    ).scalars()

    out: list[Figure] = []
    seen: set[str] = set()
    for row in rows:
        if row.fiscal_period in seen:
            continue
        seen.add(row.fiscal_period)
        out.append(
            Figure(
                metric=row.metric_key,
                fiscal_period=row.fiscal_period,
                period_end=row.period_end,
                value=row.value,
                unit=row.unit,
                consolidated=row.consolidated,
                source_item_id=row.source_item_id,
            )
        )
        if len(out) >= limit:
            break
    return out


def latest(db: Session, instrument_id: uuid.UUID, metric: str) -> Figure | None:
    """The newest reported value of one metric, or None. ⚠ None is an answer."""
    found = series(db, instrument_id, metric, limit=1)
    return found[0] if found else None


def by_period(db: Session, instrument_id: uuid.UUID, *, limit: int = 6) -> dict[str, dict]:
    """Every metric for every period, keyed `period -> metric -> value`.

    One query for the whole quality score, rather than a dozen round trips per component.
    """
    rows = db.execute(
        sa.select(Fundamental)
        .join(SourceItem, Fundamental.source_item_id == SourceItem.id)
        .where(Fundamental.instrument_id == instrument_id)
        .order_by(
            Fundamental.period_end.desc(),
            Fundamental.consolidated.desc(),
            SourceItem.published_at.desc(),
        )
    ).scalars()

    out: dict[str, dict] = {}
    basis: dict[str, bool] = {}
    for row in rows:
        period = out.setdefault(row.fiscal_period, {})
        # First writer wins, and rows arrive consolidated-first, so a standalone figure never
        # overwrites a consolidated one for the same period.
        if row.fiscal_period not in basis:
            basis[row.fiscal_period] = row.consolidated
        if row.consolidated != basis[row.fiscal_period]:
            continue
        period.setdefault(row.metric_key, row.value)
        period.setdefault("_period_end", row.period_end)
        period.setdefault("_consolidated", row.consolidated)
        period.setdefault("_source_item_id", row.source_item_id)
    ordered = sorted(out, key=lambda p: out[p]["_period_end"], reverse=True)[:limit]
    return {p: out[p] for p in ordered}
