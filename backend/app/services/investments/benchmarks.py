"""What you could have bought instead.

Beating nothing is easy. The question the whole exercise eventually rests on is whether this
beat the alternative — and the alternative has to be something that was genuinely available,
priced the way it would genuinely have been priced.

⚠ **The alternative is an index FUND, not an index.** A total-return index is the right idea:
the headline price index understates the real alternative by roughly the dividend yield, and
benchmarking against it is winning by accounting. But an index cannot be bought. A fund's NAV
is a total-return series by construction — dividends are reinvested into it — and it carries
the expense ratio and tracking error a real alternative would have charged. That makes this
benchmark slightly *harder* to beat than a raw index would be for someone who cannot buy one,
which is the honest direction for the asymmetry to run.

⚠ **The S&P 500 benchmark is the rupee-denominated fund**, because the portfolio's accounts
are in rupees. A dollar-denominated benchmark would credit or blame the comparison for a
currency move nobody made a decision about.

⚠ **Nothing here is annualised.** Every figure is the plain return over the stated window,
because annualising a two-month number produces something that looks like a yearly rate and is
mostly noise — and the window is always shown beside the figure.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

import httpx
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Benchmark, BenchmarkValue, Portfolio
from app.services.investments import history, overview
from app.services.investments import portfolio as pf
from app.services.marketdata import amfi

log = logging.getLogger(__name__)

ZERO = Decimal(0)

#: Above this share of the book sitting in things no index stands in for — crypto, funds — the
#: comparison is flagged. ⚠ Not hidden and not corrected for: the portfolio's own return
#: genuinely includes them, and quietly excluding them would be picking the flattering subset.
#: Saying so is what keeps the number readable rather than merely available.
MISMATCH_SHARE = Decimal("0.10")

#: How far back a first sync reaches. ⚠ Enough to cover a year of holding plus the run-up a
#: comparison needs, and no further — a benchmark's deep history is never read and would be
#: several thousand rows per fund of pure storage.
HISTORY_DAYS = 500

#: The alternatives, and what each stands in for.
#:
#: ⚠ Direct plans, deliberately. A regular plan carries a distribution commission the investor
#: would not have paid buying it themselves, and benchmarking against the more expensive share
#: class would be flattering the portfolio by about a percent a year.
REGISTRY: tuple[dict, ...] = (
    {
        "key": "NIFTY50_TRI",
        "name": "UTI Nifty 50 Index Fund, direct growth",
        "proxy_for": "Nifty 50 total return — an index fund because an index cannot be bought",
        "source": amfi.PROVIDER,
        "external_id": "120716",
        "region": "IN",
    },
    {
        "key": "SP500_TR",
        "name": "Motilal Oswal S&P 500 Index Fund, direct growth",
        "proxy_for": "S&P 500 total return, in rupees — the exposure actually available here",
        "source": amfi.PROVIDER,
        "external_id": "148381",
        "region": "US",
    },
)


def install(db: Session) -> list[Benchmark]:
    """Register the alternatives. Idempotent."""
    out = []
    for spec in REGISTRY:
        row = db.execute(
            sa.select(Benchmark).where(Benchmark.key == spec["key"])
        ).scalar_one_or_none()
        if row is None:
            row = Benchmark(id=uuid.uuid4(), **spec)
            db.add(row)
            db.flush()
        out.append(row)
    return out


def sync(db: Session, c: httpx.Client | None = None, *, days: int = HISTORY_DAYS) -> dict:
    """Fetch each benchmark's history and store what is new.

    ⚠ One failure does not end the round. A benchmark that could not be reached leaves its
    last known value in place and is reported — a comparison against a stale benchmark is
    wrong, but a comparison against nothing is unavailable, and the caller needs to tell them
    apart.
    """
    start = dt.date.today() - dt.timedelta(days=days)
    report: dict = {"written": 0, "failed": {}}

    for row in install(db):
        try:
            series = amfi.nav_history(row.external_id, start, c)
        except Exception as exc:  # noqa: BLE001 - one bad fund must not end the round
            log.warning("benchmark %s could not be synced: %s", row.key, type(exc).__name__)
            report["failed"][row.key] = type(exc).__name__
            continue

        if not series:
            report["failed"][row.key] = "no history returned"
            continue

        # ⚠ ON CONFLICT DO NOTHING, not an upsert. The table is append-only and a NAV that
        # changed after the fact would be a benchmark moving under a result.
        written = db.execute(
            insert(BenchmarkValue)
            .values(
                [{"benchmark_id": row.id, "on_day": day, "value": value} for day, value in series]
            )
            .on_conflict_do_nothing(index_elements=["benchmark_id", "on_day"])
            .returning(BenchmarkValue.on_day)
        ).all()
        report["written"] += len(written)
        row.last_synced_at = dt.datetime.now(dt.UTC)

    db.flush()
    return report


def series(db: Session, key: str) -> tuple[list[dt.date], list[Decimal]]:
    """One benchmark's values, oldest first."""
    rows = db.execute(
        sa.select(BenchmarkValue.on_day, BenchmarkValue.value)
        .join(Benchmark, Benchmark.id == BenchmarkValue.benchmark_id)
        .where(Benchmark.key == key)
        .order_by(BenchmarkValue.on_day)
    ).all()
    return [row[0] for row in rows], [row[1] for row in rows]


def _as_of(days: list[dt.date], values: list[Decimal], day: dt.date) -> Decimal | None:
    """The last value on or before `day`.

    ⚠ Carry-forward only, never backwards. A NAV published tomorrow says nothing about what
    the alternative was worth today, and using it would let a comparison change its own past.
    """
    index = bisect_right(days, day)
    return values[index - 1] if index else None


@dataclass(frozen=True)
class Line:
    """One alternative over one window."""

    key: str
    name: str
    #: ⚠ Shown. A benchmark that is a proxy has to announce it, or a comparison against it
    #: reads as a comparison against the index itself.
    proxy_for: str
    region: str
    start_value: Decimal | None
    end_value: Decimal | None
    #: None when the window is not covered on both sides. A return computed from a
    #: carried-forward value at one end is a return against a date that never happened.
    change_pct: Decimal | None
    detail: str


@dataclass(frozen=True)
class Comparison:
    """The book against the alternatives, over the same window."""

    start: dt.date
    end: dt.date
    portfolio_pct: Decimal | None
    lines: list[Line]
    #: The book's India/US split, as the blend is weighted.
    weights: dict[str, Decimal]
    blended_pct: Decimal | None
    #: ⚠ False when the portfolio's own return could not be computed on the same grid.
    #: Comparing a figure against a benchmark it does not share a window with is worse than
    #: not comparing.
    readable: bool
    detail: str
    #: ⚠ The share of the book no index stands in for — crypto and funds, which are in the
    #: portfolio's own return and have no counterpart in the blend. Above `MISMATCH_SHARE` the
    #: two sides are measuring different things and `caveat` says so.
    non_equity_share: Decimal = ZERO
    caveat: str | None = None


def _split(db: Session, portfolio_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Decimal]:
    """How the book divides between India and the US, by current value in rupees.

    ⚠ By value, not by count. Two US holdings worth a tenth of the book are not half of it,
    and a blend weighted by count would compare against an alternative nobody held.

    ⚠ Equities only. Crypto and funds are tracked and reported, but the system never proposes
    them — including them would weigh a decision nobody made against an index that had nothing
    to do with it.

    ⚠ Routed through `overview.summary`, which already converts each asset class to rupees at
    the recorded rate. Re-deriving that here would be a second place that decides what a
    dollar was worth, and the two would eventually disagree about a day.
    """
    try:
        totals = {
            row.asset_class: row.market_value_inr
            for row in overview.summary(db, portfolio_id, user_id).by_asset_class
        }
    except Exception:  # noqa: BLE001 - an unvalued book simply has no split to report
        return {"IN": Decimal(1), "US": ZERO, "OTHER_SHARE": ZERO}

    india = totals.get("EQUITY_IN") or ZERO
    america = totals.get("EQUITY_US") or ZERO
    other = sum(
        (value or ZERO)
        for asset_class, value in totals.items()
        if asset_class not in ("EQUITY_IN", "EQUITY_US")
    )
    whole = india + america
    everything = whole + other
    if whole <= 0:
        # ⚠ Defaulting to all-India rather than to nothing. A book with no priced equity has
        # no meaningful split, and the Indian side is the one the framework is about — but the
        # blend refuses to compute at all unless both benchmarks loaded, so this never
        # silently becomes "the Nifty is the whole alternative".
        return {"IN": Decimal(1), "US": ZERO, "OTHER_SHARE": ZERO}

    return {
        "IN": (india / whole).quantize(Decimal("0.0001")),
        "US": (america / whole).quantize(Decimal("0.0001")),
        # ⚠ How much of the book the blend does NOT represent. Crypto and funds are in the
        # portfolio's own return but have no index standing in for them, so a large share here
        # means the two sides of the comparison are measuring different things — and saying so
        # is the difference between a caveat and a misreading.
        "OTHER_SHARE": (other / everything).quantize(Decimal("0.0001")) if everything else ZERO,
    }


def portfolio_change(
    db: Session, portfolio_id: uuid.UUID, start: dt.date, end: dt.date
) -> tuple[Decimal | None, str]:
    """What the book itself did over the window, with the timing of money in and out removed.

    ⚠ **Time-weighted, through the module's own TWR, not a fresh calculation here.** A first
    version of this subtracted net purchases from the change in value, and on the real book it
    reported **3915%** — because a purchase in dollars was netted off at its dollar face value
    against a rupee portfolio, and because money added late in a window that started small
    swamps the arithmetic whatever the currency. Both are exactly the problems TWR exists to
    solve, and this module already has one that has been tested against Groww.

    ⚠ TWR is the right measure against a benchmark specifically. The alternative is "what if I
    had put this in an index fund instead", which is a question about the *holdings*, not about
    when cash happened to arrive — XIRR answers the other one and would credit the comparison
    for good timing that the benchmark had no opportunity to match.
    """
    points = history.curve(db, portfolio_id, since=start, until=end)
    covered = history.covered_range(points)
    if covered is None:
        return None, "the book has no valued history yet"
    if covered[0] > start:
        return None, f"the book's history starts on {covered[0]}, inside this window"

    txns = pf.ledger(db, portfolio_id)
    flows = [(day, amount) for day, amount in pf.cash_flows(txns) if start <= day <= end]

    # ⚠ `window_days=None`: the window is the caller's, and re-trimming it to a rolling year
    # here would silently compare a twelve-month portfolio figure against a six-month
    # benchmark — a comparison whose two halves cover different time.
    result = overview._time_weighted(points, flows, window_days=None)
    if result.value is None:
        return None, result.unavailable_because or "the book could not be valued over this window"
    return Decimal(result.value).quantize(Decimal("0.0001")), f"{start} to {end}"


def compare(
    db: Session,
    user_id: uuid.UUID,
    *,
    start: dt.date,
    end: dt.date | None = None,
) -> Comparison:
    """The book against every alternative, over the same window and the same grid."""
    end = end or dt.date.today()

    real = db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user_id,
            Portfolio.kind == "REAL",
            Portfolio.deleted_at.is_(None),
        )
    ).scalar_one_or_none()

    portfolio_pct, detail = (
        portfolio_change(db, real.id, start, end) if real else (None, "no real book yet")
    )
    weights = _split(db, real.id, user_id) if real else {"IN": Decimal(1), "US": ZERO}

    lines: list[Line] = []
    for row in db.execute(
        sa.select(Benchmark).where(Benchmark.is_active.is_(True)).order_by(Benchmark.region)
    ).scalars():
        days, values = series(db, row.key)
        opening = _as_of(days, values, start)
        closing = _as_of(days, values, end)
        covered = bool(days) and days[0] <= start
        if opening and closing and covered and opening > 0:
            change = ((closing - opening) / opening).quantize(Decimal("0.0001"))
            line_detail = f"{start} to {end}"
        else:
            change = None
            line_detail = (
                f"history starts on {days[0]}, inside this window"
                if days
                else "no history fetched yet"
            )
        lines.append(
            Line(
                key=row.key,
                name=row.name,
                proxy_for=row.proxy_for,
                region=row.region,
                start_value=opening,
                end_value=closing,
                change_pct=change,
                detail=line_detail,
            )
        )

    by_region = {line.region: line.change_pct for line in lines}
    # ⚠ The blend needs BOTH sides, or it is not a blend. Weighting one benchmark at 100%
    # because the other failed to load would present a single index as the whole alternative.
    if all(by_region.get(region) is not None for region in ("IN", "US")):
        blended = (weights["IN"] * by_region["IN"] + weights["US"] * by_region["US"]).quantize(
            Decimal("0.0001")
        )
    else:
        blended = None

    other = weights.get("OTHER_SHARE", ZERO)
    caveat = None
    if other >= MISMATCH_SHARE:
        caveat = (
            f"{other:.0%} of the book is crypto or funds, which no index here stands in for. "
            f"The portfolio figure includes them and the blend does not, so this comparison "
            f"is between two different things by roughly that much."
        )

    return Comparison(
        start=start,
        end=end,
        portfolio_pct=portfolio_pct,
        lines=lines,
        weights={k: v for k, v in weights.items() if k != "OTHER_SHARE"},
        blended_pct=blended,
        readable=portfolio_pct is not None and blended is not None,
        detail=detail,
        non_equity_share=other,
        caveat=caveat,
    )
