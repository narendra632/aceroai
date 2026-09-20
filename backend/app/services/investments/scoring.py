"""The quality-and-price score, and the flags that can be computed rather than judged.

**No model is invoked in this module and none may be.** Every figure comes from a filing a
company made and every ratio is arithmetic. That is not caution — it is the whole basis on
which any of this can be trusted, because a language model writes a well-argued thesis with
fabricated figures in exactly the register it uses to write one with real figures, and the
measured failure rate on questions about real filings is around four in five.

⚠ **A missing input scores `None`, never zero.** The result is reported as "6.0 out of 8.0
available" with the unavailable parts named. A company rejected because a filing had not been
read yet is a pipeline failure dressed as a judgement about the business, and it is
indistinguishable from the real thing unless the two are kept apart in the arithmetic itself.

⚠ **A bank is measured differently, because most of this does not apply to one.** Depreciation
and capital expenditure are immaterial to a bank, borrowings are its raw material rather than
its leverage, and operating cash flow swings with deposit flows rather than with trading
performance. So those components report `None` for a bank rather than failing it on arithmetic
about something it does not have — which would classify the portfolio's anchor holding as a
value trap and permanently block adding to it.

**Four of the ten reflexivity flags are computed here.** The checklist asks ten questions;
six need a model reading news and filings and arrive with the reading layer. These four are
arithmetic over prices and filed numbers, so they are answered exactly and need no judgement
at all — and two of them (6 and 10) are specified to OVERRIDE whatever a model later says,
because a measurable thing should never be a matter of opinion.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import PriceObservation
from app.services.investments import frameworks, fundamentals

ZERO = Decimal(0)
HUNDRED = Decimal(100)

#: How many years a multi-year test needs before it will answer at all.
#:
#: ⚠ The return-on-equity rule is "at or above 15% in three of the last five years". Read ONE
#: year and that rule cannot be satisfied at all, so scoring it zero is arithmetically correct
#: and epistemically wrong — the result is indistinguishable from a company that genuinely
#: failed for five years.
#:
#: Two, not three, and the reason is a measured property of the source rather than a
#: preference. The exchange publishes a full-year profit and loss only from the Integrated
#: Filing framework onward, which begins with FY25; every March filing before that tags its
#: year as a fourth quarter and carries a balance sheet with no revenue beside it, and the
#: prior-year comparative in a later filing turns out to be balance-sheet only. So two years
#: is what exists in machine-readable form today, and a threshold of three would report every
#: company in the book as unknown for ever.
#:
#: Two years of a 25% return is genuine evidence where one year is a snapshot. The year count
#: is stated in every component's detail so nobody mistakes it for five, and the quadrant
#: refuses a hard verdict regardless — see `MIN_AVAILABLE_FOR_VERDICT`.
#:
#: The remedy, when it is worth the fetches: sum four quarterly filings per missing year.
MIN_YEARS_FOR_TREND = 2
MIN_YEARS_FOR_CASH = 2

#: Below this many available points, the reading is too thin to call a company anything.
#:
#: ⚠ Two of the four quadrants HARD-BLOCK a purchase. Blocking on a half-read set of filings is
#: a pipeline failure wearing the clothes of a judgement about the business — and from the
#: outside the two look identical.
MIN_AVAILABLE_FOR_VERDICT = Decimal(6)


@dataclass(frozen=True)
class Part:
    """One component of the score. `points is None` means the inputs were not there."""

    name: str
    points: Decimal | None
    available: Decimal
    detail: str
    #: The figures this rested on, so every number can be traced back to a filing.
    cites: list[uuid.UUID] = field(default_factory=list)

    @property
    def is_known(self) -> bool:
        return self.points is not None


@dataclass(frozen=True)
class QualityScore:
    """How good the business is, and how sensibly it is priced.

    ⚠ `earned` and `available` are reported together and must be shown together. "6.0" means
    nothing on its own: six out of ten is mediocre and six out of six is excellent, and the
    difference is entirely whether the filings had been read.
    """

    earned: Decimal
    available: Decimal
    parts: list[Part]
    #: Components whose inputs were missing, named so the interface can say which.
    unknown: list[str]

    @property
    def ratio(self) -> Decimal | None:
        """Earned over available — what the quadrant is decided on. None when nothing is known."""
        return (self.earned / self.available) if self.available else None

    @property
    def is_complete(self) -> bool:
        return not self.unknown


def _mean(values: list[Decimal]) -> Decimal | None:
    return (sum(values, ZERO) / Decimal(len(values))) if values else None


def _get(periods: dict[str, dict], period: str, metric: str) -> Decimal | None:
    value = periods.get(period, {}).get(metric)
    return value if isinstance(value, Decimal) else None


def _annual(periods: dict[str, dict]) -> list[str]:
    """Full-year periods only, newest first. Quarterly rows never enter a yearly ratio."""
    return [p for p in periods if "Q" not in p]


def _roe(periods: dict[str, dict], period: str) -> Decimal | None:
    pat = _get(periods, period, "pat_owners") or _get(periods, period, "pat")
    equity = _get(periods, period, "equity") or _sum_equity(periods, period)
    if pat is None or not equity:
        return None
    return pat / equity * HUNDRED


def _sum_equity(periods: dict[str, dict], period: str) -> Decimal | None:
    capital = _get(periods, period, "share_capital")
    other = _get(periods, period, "other_equity")
    if capital is None and other is None:
        return None
    return (capital or ZERO) + (other or ZERO)


def _roce(periods: dict[str, dict], period: str) -> Decimal | None:
    """(profit before tax + finance costs) ÷ (equity + borrowings).

    ⚠ Finance costs are added back because return on CAPITAL asks what the whole capital base
    earned, before deciding who it was paid to. Leaving them out measures the equity holder's
    slice and calls it the business's return, which flatters a company with no debt and
    punishes one that borrows to build something worth building.
    """
    pbt = _get(periods, period, "pbt")
    finance = _get(periods, period, "finance_costs")
    equity = _get(periods, period, "equity") or _sum_equity(periods, period)
    if pbt is None or equity is None:
        return None
    borrowings = (_get(periods, period, "borrowings_current") or ZERO) + (
        _get(periods, period, "borrowings_noncurrent") or ZERO
    )
    capital = equity + borrowings
    if not capital:
        return None
    return (pbt + (finance or ZERO)) / capital * HUNDRED


def _cites(periods: dict[str, dict], used: list[str]) -> list[uuid.UUID]:
    out = []
    for period in used:
        ref = periods.get(period, {}).get("_source_item_id")
        if isinstance(ref, uuid.UUID):
            out.append(ref)
    return out


def quality_score(
    db: Session,
    instrument,
    spec: dict,
    *,
    market_cap: Decimal | None = None,
) -> QualityScore:
    """Score the business and its price, from filings alone.

    `market_cap` is the only input that is not a filed number — it is price × shares, and the
    price half comes from the observation record. Without it the margin-of-safety component
    reports unknown rather than assuming anything about the price.
    """
    periods = fundamentals.by_period(db, instrument.id, limit=6)
    years = _annual(periods)
    is_bank = frameworks.values_on_earnings(spec, instrument.sector)
    parts: list[Part] = []

    # --- return on equity ---------------------------------------------------------------
    roes = [(p, _roe(periods, p)) for p in years[:5]]
    known_roe = [(p, v) for p, v in roes if v is not None]
    if len(known_roe) < MIN_YEARS_FOR_TREND:
        parts.append(
            Part(
                "roe",
                None,
                Decimal(2),
                f"{len(known_roe)} year(s) of return on equity read; the rule asks about three "
                "of five, and fewer cannot answer it either way",
            )
        )
    else:
        strong = [p for p, v in known_roe if v >= 15]
        points = Decimal(2) if len(strong) >= 3 else Decimal(1) if len(strong) == 2 else ZERO
        parts.append(
            Part(
                "roe",
                points,
                Decimal(2),
                f"at or above 15% in {len(strong)} of {len(known_roe)} year(s) read"
                + ("; fewer than five years are on file" if len(known_roe) < 5 else ""),
                _cites(periods, [p for p, _ in known_roe]),
            )
        )

    # --- return on capital ---------------------------------------------------------------
    if is_bank:
        # ⚠ A bank's borrowings ARE its business. Return on capital employed treats debt as
        # funding for operations, which describes an industrial and not a lender.
        parts.append(Part("roce", None, Decimal(2), "return on capital does not describe a bank"))
    else:
        roces = [v for p in years[:5] if (v := _roce(periods, p)) is not None]
        average = _mean(roces)
        if average is None or len(roces) < MIN_YEARS_FOR_TREND:
            parts.append(
                Part(
                    "roce",
                    None,
                    Decimal(2),
                    f"{len(roces)} year(s) of return on capital read; an average over fewer "
                    "describes a moment rather than a business",
                )
            )
        else:
            points = Decimal(2) if average >= 15 else Decimal(1) if average >= 12 else ZERO
            parts.append(
                Part(
                    "roce",
                    points,
                    Decimal(2),
                    f"{average:.1f}% average over {len(roces)} year(s) read",
                    _cites(periods, years[: len(roces)]),
                )
            )

    # --- cash conversion -------------------------------------------------------------------
    if is_bank:
        parts.append(
            Part(
                "cash_conversion",
                None,
                Decimal(2),
                "a bank's operating cash flow follows deposit flows, not trading performance",
            )
        )
    else:
        ratios = []
        for period in years[:3]:
            ocf, pat = _get(periods, period, "ocf"), _get(periods, period, "pat")
            if ocf is not None and pat:
                ratios.append(ocf / pat)
        mean = _mean(ratios)
        if mean is None or len(ratios) < MIN_YEARS_FOR_CASH:
            parts.append(
                Part(
                    "cash_conversion",
                    None,
                    Decimal(2),
                    f"{len(ratios)} year(s) with both cash flow and profit; one year of working "
                    "capital is a swing, not a habit",
                )
            )
        else:
            points = (
                Decimal(2)
                if mean >= Decimal("0.8")
                else Decimal(1)
                if mean >= Decimal("0.6")
                else ZERO
            )
            parts.append(
                Part(
                    "cash_conversion",
                    points,
                    Decimal(2),
                    f"{mean:.2f} of profit arrived as cash, averaged over {len(ratios)} year(s)",
                    _cites(periods, years[: len(ratios)]),
                )
            )

    # --- balance sheet ------------------------------------------------------------------------
    if is_bank:
        parts.append(
            Part("balance_sheet", None, Decimal(1), "borrowings are a bank's raw material")
        )
    else:
        newest = years[0] if years else None
        pbt = _get(periods, newest, "pbt") if newest else None
        dep = _get(periods, newest, "dep_amort") if newest else None
        finance = _get(periods, newest, "finance_costs") if newest else None
        if newest is None or pbt is None or dep is None:
            parts.append(Part("balance_sheet", None, Decimal(1), "net debt or earnings unknown"))
        else:
            ebitda = pbt + (finance or ZERO) + dep
            net_debt = (
                (_get(periods, newest, "borrowings_current") or ZERO)
                + (_get(periods, newest, "borrowings_noncurrent") or ZERO)
                - (_get(periods, newest, "cash") or ZERO)
            )
            if ebitda <= 0:
                parts.append(
                    Part("balance_sheet", ZERO, Decimal(1), "earnings before interest are negative")
                )
            else:
                multiple = net_debt / ebitda
                parts.append(
                    Part(
                        "balance_sheet",
                        Decimal(1) if multiple < 2 else ZERO,
                        Decimal(1),
                        f"net debt is {multiple:.1f}× earnings before interest and depreciation",
                        _cites(periods, [newest]),
                    )
                )

    # --- retained earnings ---------------------------------------------------------------------
    # ⚠ Reported unknown until a market-cap history exists. The test asks whether each rupee
    # retained created at least a rupee of market value over five years, which needs the market
    # cap at both ends; the price record does not yet reach back five years for these companies.
    parts.append(
        Part(
            "retained_earnings",
            None,
            Decimal(1),
            "needs five years of market value, which the price record does not yet reach",
        )
    )

    # --- margin of safety -------------------------------------------------------------------------
    parts.append(_margin_of_safety(periods, years, spec, instrument, market_cap, is_bank))

    earned = sum((p.points for p in parts if p.points is not None), ZERO)
    available = sum((p.available for p in parts if p.points is not None), ZERO)
    return QualityScore(
        earned=earned,
        available=available,
        parts=parts,
        unknown=[p.name for p in parts if p.points is None],
    )


def _margin_of_safety(
    periods: dict[str, dict],
    years: list[str],
    spec: dict,
    instrument,
    market_cap: Decimal | None,
    is_bank: bool,
) -> Part:
    """How far below a defensible worth the market is asking.

    ⚠ Deliberately crude and identical every month. A rough number computed the same way can be
    compared across months; a sophisticated one computed differently each time cannot, and the
    comparison is the entire point of running this for a year.

    ⚠ **Trailing reported earnings, never a forecast.** No filing contains next year's profit,
    so a forecast cannot be checked against anything — and an unverifiable number is exactly
    what this module forbids. The consequence is real and worth stating: a fast-growing company
    will look expensive here even where a forward estimate would call it fair.
    """
    multiple = frameworks.multiple_for(spec, instrument.sector)
    if market_cap is None:
        return Part("margin_of_safety", None, Decimal(2), "no market value for the company yet")

    usable = years[:3]
    if is_bank:
        # Profit, not owner earnings: depreciation and capex are immaterial to a bank, so the
        # owner-earnings adjustment would subtract noise from a number it cannot improve.
        earnings = [v for p in usable if (v := _get(periods, p, "pat")) is not None]
        basis = "profit after tax"
    else:
        earnings = []
        for period in usable:
            pat = _get(periods, period, "pat")
            dep = _get(periods, period, "dep_amort")
            if pat is None or dep is None:
                continue
            # Owner earnings: profit, plus depreciation, less the capex needed to stand still.
            # ⚠ Maintenance capex is disclosed nowhere, so depreciation stands in for it — the
            # two then cancel, which is why this lands close to profit and is flagged as a proxy.
            earnings.append(pat + dep - dep)
        basis = "owner earnings (maintenance capex proxied by depreciation)"

    normalised = _mean(earnings)
    if normalised is None or normalised <= 0:
        return Part(
            "margin_of_safety",
            None,
            Decimal(2),
            "no positive earnings to value" if normalised is not None else "earnings unknown",
        )

    worth = normalised * multiple.value
    try:
        mos = (worth - market_cap) / worth
    except (InvalidOperation, ZeroDivisionError):
        return Part("margin_of_safety", None, Decimal(2), "the valuation did not compute")

    points = Decimal(2) if mos >= Decimal("0.25") else Decimal(1) if mos >= 0 else ZERO
    caveat = " ⚠ the default multiple was used" if multiple.is_fallback else ""
    return Part(
        "margin_of_safety",
        points,
        Decimal(2),
        (
            f"{mos * 100:.0f}% below a worth of {multiple.value}× {basis} "
            f"over {len(earnings)} year(s){caveat}"
            if mos >= 0
            else f"{abs(mos) * 100:.0f}% ABOVE a worth of {multiple.value}× {basis}{caveat}"
        ),
        _cites(periods, usable[: len(earnings)]),
    )


# --- the flags that are arithmetic rather than judgement -------------------------------------


@dataclass(frozen=True)
class Flag:
    """One checklist answer. ⚠ Every flag is a RED flag: YES is bad."""

    number: int
    question: str
    verdict: str  # YES · NO · UNKNOWN
    evidence: str
    #: True where the answer is measured, so no model verdict may override it.
    computed: bool = True


def _closes(db: Session, instrument_id: uuid.UUID, since: dt.date) -> list[Decimal]:
    rows = db.execute(
        sa.select(PriceObservation.price)
        .where(
            PriceObservation.instrument_id == instrument_id,
            PriceObservation.quality == "OK",
            PriceObservation.observed_at >= dt.datetime.combine(since, dt.time(0, 0), dt.UTC),
        )
        .order_by(PriceObservation.observed_at)
    ).scalars()
    return list(rows)


def computed_flags(
    db: Session, instrument, *, today: dt.date | None = None, price: Decimal | None = None
) -> list[Flag]:
    """The four checklist answers that are measured rather than judged.

    ⚠ Flags 6 and 10 are specified to OVERRIDE a model's verdict when it later has one. A
    measurable thing should never be a matter of opinion, and these two are the ones most
    likely to be argued away by a persuasive narrative.
    """
    today = today or dt.date.today()
    periods = fundamentals.by_period(db, instrument.id, limit=6)
    years = _annual(periods)
    out: list[Flag] = []

    # --- 2: returns declining or below 15% ------------------------------------------------
    values = [(p, _roe(periods, p)) for p in years[:5]]
    known = [(p, v) for p, v in values if v is not None]
    if not known:
        out.append(
            Flag(
                2,
                "Is ROE or ROCE consistently declining or below 15%?",
                "UNKNOWN",
                "no year's return on equity could be computed",
            )
        )
    else:
        below = [p for p, v in known if v < 15]
        declining = len(known) >= 3 and all(
            known[i][1] < known[i + 1][1] for i in range(len(known) - 1)
        )
        verdict = "YES" if len(below) > len(known) / 2 or declining else "NO"
        out.append(
            Flag(
                2,
                "Is ROE or ROCE consistently declining or below 15%?",
                verdict,
                f"below 15% in {len(below)} of {len(known)} year(s) read"
                + ("; and falling every year" if declining else ""),
            )
        )

    # --- 8: margins deteriorating while revenue scales -------------------------------------
    if len(years) >= 2:
        newer, older = years[0], years[1]
        rev_new, rev_old = _get(periods, newer, "revenue"), _get(periods, older, "revenue")
        pbt_new, pbt_old = _get(periods, newer, "pbt"), _get(periods, older, "pbt")
        if None in (rev_new, rev_old, pbt_new, pbt_old) or not rev_new or not rev_old:
            out.append(
                Flag(
                    8,
                    "Are margins deteriorating even as revenue scales?",
                    "UNKNOWN",
                    "two years of revenue and profit are needed",
                )
            )
        else:
            grew = rev_new > rev_old
            margin_new, margin_old = pbt_new / rev_new, pbt_old / rev_old
            slipped = (margin_old - margin_new) > Decimal("0.01")
            out.append(
                Flag(
                    8,
                    "Are margins deteriorating even as revenue scales?",
                    "YES" if grew and slipped else "NO",
                    f"revenue {'grew' if grew else 'fell'}, margin "
                    f"{margin_old * 100:.1f}% → {margin_new * 100:.1f}%",
                )
            )
    else:
        out.append(
            Flag(
                8,
                "Are margins deteriorating even as revenue scales?",
                "UNKNOWN",
                "fewer than two years have been read",
            )
        )

    # --- 6: multiple expanded faster than earnings ------------------------------------------
    out.append(_flag_six(db, instrument, periods, years, today, price))

    # --- 10: the market's tone shifted sharply ------------------------------------------------
    closes = _closes(db, instrument.id, today - dt.timedelta(days=365))
    if len(closes) < 30:
        out.append(
            Flag(
                10,
                "Has the market's tone shifted sharply in 12–18 months?",
                "UNKNOWN",
                f"only {len(closes)} closing prices in the last year",
            )
        )
    else:
        low, high = min(closes), max(closes)
        span = (high - low) / low if low else ZERO
        out.append(
            Flag(
                10,
                "Has the market's tone shifted sharply in 12–18 months?",
                "YES" if span > Decimal("0.60") else "NO",
                f"52-week range is {span * 100:.0f}% of its low",
            )
        )
    return out


def _flag_six(db, instrument, periods, years, today, price) -> Flag:
    """Did the multiple expand faster than the earnings underneath it?

    ⚠ Direction-agnostic on purpose. A multiple that doubles while profit rises a tenth is the
    classic reflexive signature, and it reads identically whether the story is told in
    excitement or in relief.
    """
    question = "Has the valuation multiple expanded far faster than earnings?"
    if price is None or len(years) < 2:
        return Flag(6, question, "UNKNOWN", "needs a price and two years of earnings")

    shares = _shares(periods, years[0])
    pat_new, pat_old = _get(periods, years[0], "pat"), _get(periods, years[1], "pat")
    if shares is None or not pat_new or not pat_old or pat_old <= 0:
        return Flag(6, question, "UNKNOWN", "share count or prior-year profit unknown")

    year_ago = _closes(db, instrument.id, today - dt.timedelta(days=400))
    if len(year_ago) < 30:
        return Flag(6, question, "UNKNOWN", "not enough price history for a year-on-year multiple")

    then, now = year_ago[0], price
    pe_now = (now * shares) / pat_new
    pe_then = (then * shares) / pat_old
    if pe_then <= 0:
        return Flag(6, question, "UNKNOWN", "the earlier multiple does not compute")

    multiple_growth = (pe_now / pe_then) - 1
    earnings_growth = (pat_new / pat_old) - 1
    if earnings_growth <= 0:
        verdict = "YES" if multiple_growth > 0 else "NO"
        return Flag(
            6,
            question,
            verdict,
            f"multiple {multiple_growth * 100:+.0f}% while earnings {earnings_growth * 100:+.0f}%",
        )
    ratio = multiple_growth / earnings_growth
    return Flag(
        6,
        question,
        "YES" if ratio > 2 else "NO",
        f"multiple {multiple_growth * 100:+.0f}% against earnings "
        f"{earnings_growth * 100:+.0f}% ({ratio:.1f}×)",
    )


def _shares(periods: dict[str, dict], period: str | None) -> Decimal | None:
    """Shares outstanding, from paid-up capital ÷ face value. Neither is filed directly."""
    if period is None:
        return None
    paid_up = _get(periods, period, "paid_up_capital")
    face = _get(periods, period, "face_value")
    if paid_up is None or not face:
        return None
    return paid_up / face


def quadrant(quality: QualityScore, reflexivity_high: bool) -> str:
    """Which of the four boxes a company sits in.

    They are kept apart from any single number because the most valuable thing these
    frameworks produce is *structurally essential, genuinely excellent, and still a bad
    purchase today* — which is precisely the finding an average destroys.
    """
    ratio = quality.ratio
    if ratio is None:
        return "UNKNOWN"
    # ⚠ Refuse a verdict on a thin reading. Q2 and Q4 hard-block a purchase, and a company
    # blocked because its filings have not been read yet is indistinguishable from one blocked
    # because it deserves to be. Price is half the question, so a missing margin of safety
    # alone is enough to withhold the verdict.
    if (
        quality.available < MIN_AVAILABLE_FOR_VERDICT
        or "margin_of_safety" in quality.unknown
        or len(quality.unknown) > 2
    ):
        return "BORDERLINE"
    if abs(ratio - Decimal("0.60")) <= Decimal("0.05"):
        return "BORDERLINE"
    good = ratio >= Decimal("0.60")
    if good and reflexivity_high:
        return "Q1"  # supercharged compounder
    if not good and reflexivity_high:
        return "Q2"  # reflexive bubble — never a buy
    if good:
        return "Q3"  # ignored compounder
    return "Q4"  # structural value trap — never a buy
