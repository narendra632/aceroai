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

⚠ **A bank is measured differently, because most of this does not apply to one** — and it is
measured, not merely excused. Depreciation and capital expenditure are immaterial to a bank,
borrowings are its raw material rather than its leverage, and operating cash flow swings with
deposit flows rather than with trading performance, so those three components do not apply.
An earlier version stopped there, reporting them unknown; the effect was that the portfolio's
largest holding had four *gaps* in its reading and was therefore permanently unjudgeable —
the same outcome as failing it, arrived at politely. A component that cannot apply is not a
gap, and a bank now gets the three tests that DO describe one: cost-to-income, the share of
pre-provision profit consumed by provisions, and how much of the interest it earns it keeps.
All three come out of the banking taxonomy the exchange already publishes.

⚠ **Nothing here demands a history a company could not have.** A multi-year rule used to
refuse to answer below two years, which is strict against an old company and unsatisfiable
against a young one — and the two are indistinguishable from the outside. A company listed
eighteen months ago was not judged harshly, it was placed beyond judgement for ever. So the
rules now scale: "three of the last five years" is held as a *share*, one year is scored at
half weight and says so, and the verdict — not the score — is withheld until a second year
exists. See `MIN_YEARS_FOR_TREND` and `History`.

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

from app.db.models import ListedCompany, PriceObservation
from app.services.investments import frameworks, fundamentals
from app.services.marketdata import nse_xbrl

ZERO = Decimal(0)
HUNDRED = Decimal(100)

#: How many years a multi-year test needs before it answers at FULL weight.
#:
#: ⚠ This was a gate and is now a cap, and the difference matters more than it looks. As a
#: gate it read "fewer than two years and the component is unknown", which is not strictness —
#: it is unsatisfiability. A company listed eighteen months ago cannot have two years. Neither
#: can one whose exchange filings only became machine-readable with FY25. Such a company was
#: not scored badly; it was placed permanently beyond scoring, and no further reading would
#: ever have moved it. That is the single defect that made three of eleven holdings unjudgeable.
#:
#: So one year is now scored, at half weight, and the detail says which. A single year can
#: show promise and cannot show consistency, and the arithmetic now states exactly that
#: instead of pretending the question was unanswerable.
#:
#: Two, not three, remains the full-weight threshold, and the reason is a property of the
#: source rather than a preference. The exchange publishes a full-year profit and loss only
#: from the Integrated Filing framework onward, which begins with FY25; every March filing
#: before that tags its year as a fourth quarter and carries a balance sheet with no revenue
#: beside it. Two years is what exists in machine-readable form today.
MIN_YEARS_FOR_TREND = 2
MIN_YEARS_FOR_CASH = 2

#: Below this many annual periods the BOX is withheld — the score is not.
#:
#: ⚠ The distinction is the entire repair. `quadrant` returning BORDERLINE on one year means
#: "neither blessed nor blocked". It does NOT mean the company could not be read: every
#: component, every ratio, every citation is computed and shown, and the verdict arrives by
#: itself on the day a second annual filing lands. What used to happen instead was an UNKNOWN
#: with two points behind it and nothing on screen to look at.
MIN_YEARS_FOR_VERDICT = 2

#: The share of read years that must clear a bar for full marks on a trend component.
#:
#: ⚠ "At or above 15% in three of the last five years" IS 0.6, and holding it as a share is
#: what lets one rule survive a company that has not existed for five years. Three of five and
#: two of three are the same standard; three of five and three of three are not.
STRONG_SHARE_FULL = Decimal("0.6")
STRONG_SHARE_HALF = Decimal("0.4")

#: What share of the points THIS COMPANY'S OWN test offers must be computed before a box is
#: called.
#:
#: ⚠ Relative, not absolute, because the test itself differs by company — half a bank's
#: components are not an industrial's. The two happen to sum to the same ten points, which
#: keeps the scores comparable, but that is a property of the weights and not something to
#: rely on: a future taxonomy with a different component set must still be measured against
#: its own denominator. The absolute rule is what left a fully-read bank permanently short of
#: the bar, because three of the ten points it was counted against described machinery it
#: does not own.
MIN_COVERAGE_FOR_VERDICT = Decimal("0.6")

#: …and never on fewer points than this, whatever the coverage says. A backstop, not the rule.
MIN_AVAILABLE_FOR_VERDICT = Decimal(4)

#: The window every multi-year rule is written against.
HISTORY_YEARS = fundamentals.HISTORY_YEARS


@dataclass(frozen=True)
class Part:
    """One component of the score. `points is None` means the inputs were not there."""

    name: str
    points: Decimal | None
    available: Decimal
    detail: str
    #: The figures this rested on, so every number can be traced back to a filing.
    cites: list[uuid.UUID] = field(default_factory=list)
    #: False where this component does not describe this KIND of company at all — return on
    #: capital employed for a bank, say.
    #:
    #: ⚠ Not the same thing as unmeasured, and treating them alike is what made the largest
    #: holding in the book permanently unjudgeable. Four tests that could never apply to a
    #: lender were counted as four holes in the reading, and it was the hole count that
    #: withheld the verdict. A hole can be filled by fetching another filing; this cannot,
    #: because there is nothing missing.
    applicable: bool = True

    @property
    def is_known(self) -> bool:
        return self.points is not None


@dataclass(frozen=True)
class History:
    """How much of a company's life is readable at all, and which limit is the binding one.

    ⚠ Two entirely different facts produce the same thin reading, and telling them apart is the
    difference between *this company is too young to have a record* and *the exchange has not
    published one*. The first resolves with time and nothing can hurry it; the second may
    resolve with a fetch. A reader shown only "1 year read" cannot tell which they are looking
    at, and will draw the wrong conclusion about half the time.
    """

    #: Annual periods actually ingested.
    years_read: int
    #: Full financial years completed since the company listed. None when the listing date is
    #: not known — the exchange's equity list is the source, and it does not cover funds.
    years_listed: int | None
    listed_on: dt.date | None

    @property
    def obtainable(self) -> int:
        """Full financial years that could exist for this company, capped at the window."""
        if self.years_listed is None:
            return HISTORY_YEARS
        return max(0, min(HISTORY_YEARS, self.years_listed))

    @property
    def is_young(self) -> bool:
        """Listed too recently to have the full window, whatever anyone fetches."""
        return self.years_listed is not None and self.years_listed < HISTORY_YEARS

    @property
    def limit(self) -> str:
        """Which constraint is binding: the company's age, the source, or neither."""
        if self.years_read >= HISTORY_YEARS:
            return "NONE"
        if self.years_read >= self.obtainable and self.is_young:
            return "AGE"
        return "SOURCE"

    def why(self) -> str:
        """One clause a person can read, or empty where the reading is not thin."""
        if self.limit == "NONE":
            return ""
        if self.limit == "AGE":
            when = f" ({self.listed_on:%b %Y})" if self.listed_on else ""
            return (
                f"listed too recently{when} for more than {self.obtainable} full year(s) to "
                "exist — everything it could have filed has been read"
            )
        return (
            f"{self.years_read} of {self.obtainable} possible year(s) read; the exchange's "
            "machine-readable filings do not reach further back"
        )


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
    #: Components whose inputs were missing, named so the interface can say which. ⚠ Gaps in
    #: the reading only. A test that does not apply to this kind of company is not a gap.
    unknown: list[str]
    #: Components that do not describe this kind of company. Rendered "—", never "0", and
    #: never counted against the reading.
    not_applicable: list[str] = field(default_factory=list)
    #: The points this company's own test would offer if every filing had been read. ⚠ Ten for
    #: an industrial, and ten for a bank from an entirely different set of components — which
    #: is why `coverage` against this, and not `available` against a constant, decides.
    possible: Decimal = ZERO
    #: Annual periods actually read, so thinness is visible rather than inferred from a ratio.
    years_read: int = 0
    #: Why the reading is as deep as it is.
    history: History | None = None

    @property
    def ratio(self) -> Decimal | None:
        """Earned over available — what the quadrant is decided on. None when nothing is known."""
        return (self.earned / self.available) if self.available else None

    @property
    def coverage(self) -> Decimal | None:
        """How much of this company's own test was answered. None when it offers nothing."""
        return (self.available / self.possible) if self.possible else None

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


def _full_years_since(listed_on: dt.date, today: dt.date) -> int:
    """Financial years (to 31 March) that both began after listing and have since ended.

    ⚠ Begun after listing, not merely ended after it. A company that listed in December 2024
    has a March 2025 filing, but it covers eight months during which it was private and three
    during which it was not — the filing exists, the year as a public company does not.
    """
    count, year = 0, listed_on.year
    while True:
        year_end = dt.date(year, 3, 31)
        if year_end > today:
            return count
        if dt.date(year - 1, 4, 1) >= listed_on:
            count += 1
        year += 1


def history_for(
    db: Session, instrument, *, years_read: int, today: dt.date | None = None
) -> History:
    """How deep a reading of this company is even possible.

    The listing date comes from the exchange's own equity list, which the reading layer keeps
    in `listed_companies`. ⚠ Absent for anything not on that list — a fund, a coin, a company
    listed only on BSE — and absent is reported as absent rather than as "listed long ago".
    """
    today = today or dt.date.today()
    listed_on = db.execute(
        sa.select(ListedCompany.listed_on)
        .where(
            ListedCompany.symbol == instrument.symbol,
            ListedCompany.exchange == instrument.exchange,
            ListedCompany.listed_on.is_not(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    return History(
        years_read=years_read,
        years_listed=_full_years_since(listed_on, today) if listed_on else None,
        listed_on=listed_on,
    )


def _consistency(strong: int, read: int, cap: Decimal) -> tuple[Decimal, str]:
    """Points for how often a test was passed, over however many years there are to test.

    ⚠ One year is scored, never refused — at half weight, because a single year can show
    promise and cannot show consistency. This is what replaced a hard floor of two years that
    no recently-listed company could ever clear, and under which such a company stayed
    unjudgeable no matter how good it was or how long anyone waited.
    """
    if read <= 0:
        return ZERO, ""
    if read < MIN_YEARS_FOR_TREND:
        return (
            (cap / 2 if strong else ZERO),
            "; one year is a snapshot, so this earns half at most",
        )
    share = Decimal(strong) / Decimal(read)
    if share >= STRONG_SHARE_FULL:
        return cap, ""
    if share >= STRONG_SHARE_HALF:
        return cap / 2, ""
    return ZERO, ""


def _thin(points: Decimal, read: int, cap: Decimal) -> tuple[Decimal, str]:
    """The same half-weight cap, for a component scored off an average rather than a count."""
    if read >= MIN_YEARS_FOR_TREND:
        return points, ""
    return min(points, cap / 2), "; one year is a snapshot, so this earns half at most"


# --- what a bank is measured on instead ------------------------------------------------------


def _cost_to_income(periods: dict[str, dict], period: str) -> Decimal | None:
    """Operating expenses as a share of net total income — the cleanest measure of a bank.

    ⚠ Operating expenses are not filed under a tag of their own. The banking taxonomy carries
    operating profit BEFORE provisions, which is total income less interest expended less
    operating expenses, so the expenses fall out by subtraction exactly. Nothing is estimated.
    """
    income = _get(periods, period, "revenue")
    interest = _get(periods, period, "interest_expended")
    operating = _get(periods, period, "operating_profit")
    if income is None or interest is None or operating is None:
        return None
    net_income = income - interest
    if net_income <= 0:
        return None
    return (net_income - operating) / net_income * HUNDRED


def _credit_cost(periods: dict[str, dict], period: str) -> Decimal | None:
    """What share of a year's pre-provision profit was consumed by provisions.

    ⚠ The nearest asset-quality reading the filed tags allow, and it is a stand-in rather than
    the thing itself. Gross non-performing assets are disclosed in the results but not under a
    tag this reader collects. Provisioning is the number the profit actually bears: a bank
    whose lending goes bad provisions for it, and provisions are what shareholders lose.
    """
    operating = _get(periods, period, "operating_profit")
    pbt = _get(periods, period, "pbt")
    if operating is None or pbt is None or operating <= 0:
        return None
    return (operating - pbt) / operating * HUNDRED


def _funding_spread(periods: dict[str, dict], period: str) -> Decimal | None:
    """How much of the interest it earned a bank keeps after paying for its deposits.

    ⚠ **Not the net interest margin.** That divides by average earning assets, which the
    banking taxonomy does not carry, and calling this by that name would invite comparison
    against published margins it is not comparable to. It is a stand-in for the low-cost
    deposit share — disclosed in a presentation, never in a filing — and it moves with the
    same thing: a bank funded by current and savings accounts keeps more of what it earns.
    """
    earned = _get(periods, period, "interest_earned")
    expended = _get(periods, period, "interest_expended")
    if earned is None or expended is None or earned <= 0:
        return None
    return (earned - expended) / earned * HUNDRED


#: Bands for the three bank tests, calibrated against large Indian lenders. ⚠ Crude on
#: purpose, and identical every month — a rough number computed the same way is comparable
#: across months, and a sophisticated one computed differently each time is not.
COST_TO_INCOME_GOOD = Decimal(45)
CREDIT_COST_GOOD = Decimal(25)
FUNDING_SPREAD_GOOD = Decimal(40)


def _bank_parts(periods: dict[str, dict], years: list[str]) -> list[Part]:
    """The three tests that describe a lender, in place of the three that describe a factory."""
    usable = years[:5]
    out = []

    ratios = [(p, v) for p in usable if (v := _cost_to_income(periods, p)) is not None]
    if not ratios:
        out.append(
            Part("cost_to_income", None, Decimal(2), "total income or operating profit not filed")
        )
    else:
        strong = [p for p, v in ratios if v <= COST_TO_INCOME_GOOD]
        points, caveat = _consistency(len(strong), len(ratios), Decimal(2))
        mean = _mean([v for _, v in ratios])
        out.append(
            Part(
                "cost_to_income",
                points,
                Decimal(2),
                f"costs are {mean:.0f}% of net income, at or under "
                f"{COST_TO_INCOME_GOOD:.0f}% in {len(strong)} of {len(ratios)} year(s) read"
                + caveat,
                _cites(periods, [p for p, _ in ratios]),
            )
        )

    costs = [(p, v) for p in usable if (v := _credit_cost(periods, p)) is not None]
    if not costs:
        out.append(
            Part(
                "credit_cost", None, Decimal(2), "pre-provision profit or pre-tax profit not filed"
            )
        )
    else:
        strong = [p for p, v in costs if v <= CREDIT_COST_GOOD]
        points, caveat = _consistency(len(strong), len(costs), Decimal(2))
        mean = _mean([v for _, v in costs])
        out.append(
            Part(
                "credit_cost",
                points,
                Decimal(2),
                f"provisions took {mean:.0f}% of pre-provision profit, at or under "
                f"{CREDIT_COST_GOOD:.0f}% in {len(strong)} of {len(costs)} year(s) read" + caveat,
                _cites(periods, [p for p, _ in costs]),
            )
        )

    spreads = [(p, v) for p in usable if (v := _funding_spread(periods, p)) is not None]
    if not spreads:
        out.append(
            Part("funding_spread", None, Decimal(1), "interest earned or expended not filed")
        )
    else:
        strong = [p for p, v in spreads if v >= FUNDING_SPREAD_GOOD]
        points, caveat = _consistency(len(strong), len(spreads), Decimal(1))
        mean = _mean([v for _, v in spreads])
        out.append(
            Part(
                "funding_spread",
                points,
                Decimal(1),
                f"keeps {mean:.0f}% of the interest it earns (a stand-in for low-cost deposits), "
                f"at or above {FUNDING_SPREAD_GOOD:.0f}% in {len(strong)} of "
                f"{len(spreads)} year(s) read" + caveat,
                _cites(periods, [p for p, _ in spreads]),
            )
        )
    return out


def _lends(periods: dict[str, dict]) -> bool:
    """Whether this company filed as a lender, by its own declaration to the exchange.

    ⚠ **A sector list is the wrong instrument for this question, and was.** It said
    `PRIVATE_BANK` and nothing else, so the first NBFC or insurer added to the book would have
    been measured on capital expenditure and cash conversion and would have failed on
    arithmetic about machinery it does not own — silently, and in exactly the way that took
    four attempts to notice on the one bank already held.

    The exchange makes companies file under a taxonomy, and a lender files under the banking
    one. That is the company saying what kind of business it is, to a regulator, in a
    document. It cannot go stale, it needs no maintenance, and it is right for a company
    nobody has classified yet. The sector list is still honoured on top of it, for anything
    whose filings have not been read.
    """
    return any(row.get("_taxonomy") == nse_xbrl.BANKING for row in periods.values())


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
    is_bank = _lends(periods) or frameworks.values_on_earnings(spec, instrument.sector)
    parts: list[Part] = []

    # --- return on equity ---------------------------------------------------------------
    roes = [(p, _roe(periods, p)) for p in years[:5]]
    known_roe = [(p, v) for p, v in roes if v is not None]
    if not known_roe:
        parts.append(Part("roe", None, Decimal(2), "no year's return on equity could be computed"))
    else:
        strong = [p for p, v in known_roe if v >= 15]
        points, caveat = _consistency(len(strong), len(known_roe), Decimal(2))
        parts.append(
            Part(
                "roe",
                points,
                Decimal(2),
                f"at or above 15% in {len(strong)} of {len(known_roe)} year(s) read"
                + ("; fewer than five years are on file" if len(known_roe) < 5 else "")
                + caveat,
                _cites(periods, [p for p, _ in known_roe]),
            )
        )

    # --- return on capital ---------------------------------------------------------------
    if is_bank:
        # ⚠ A bank's borrowings ARE its business. Return on capital employed treats debt as
        # funding for operations, which describes an industrial and not a lender. Marked
        # inapplicable rather than unknown, so it leaves the denominator instead of counting
        # as a hole in the reading — see `Part.applicable`.
        parts.append(
            Part(
                "roce",
                None,
                Decimal(2),
                "return on capital does not describe a bank",
                applicable=False,
            )
        )
    else:
        roces = [v for p in years[:5] if (v := _roce(periods, p)) is not None]
        average = _mean(roces)
        if average is None:
            parts.append(
                Part("roce", None, Decimal(2), "no year's return on capital could be computed")
            )
        else:
            raw = Decimal(2) if average >= 15 else Decimal(1) if average >= 12 else ZERO
            points, caveat = _thin(raw, len(roces), Decimal(2))
            parts.append(
                Part(
                    "roce",
                    points,
                    Decimal(2),
                    f"{average:.1f}% average over {len(roces)} year(s) read" + caveat,
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
                applicable=False,
            )
        )
    else:
        ratios = []
        for period in years[:3]:
            ocf, pat = _get(periods, period, "ocf"), _get(periods, period, "pat")
            if ocf is not None and pat:
                ratios.append(ocf / pat)
        mean = _mean(ratios)
        if mean is None:
            parts.append(
                Part(
                    "cash_conversion",
                    None,
                    Decimal(2),
                    "no year carries both operating cash flow and profit",
                )
            )
        else:
            raw = (
                Decimal(2)
                if mean >= Decimal("0.8")
                else Decimal(1)
                if mean >= Decimal("0.6")
                else ZERO
            )
            # ⚠ One year of working capital is a swing rather than a habit, so it earns half.
            # It used to earn nothing at all, which read identically to cash never arriving.
            points, caveat = _thin(raw, len(ratios), Decimal(2))
            parts.append(
                Part(
                    "cash_conversion",
                    points,
                    Decimal(2),
                    f"{mean:.2f} of profit arrived as cash, averaged over {len(ratios)} year(s)"
                    + caveat,
                    _cites(periods, years[: len(ratios)]),
                )
            )

    # --- balance sheet ------------------------------------------------------------------------
    if is_bank:
        parts.append(
            Part(
                "balance_sheet",
                None,
                Decimal(1),
                "borrowings are a bank's raw material",
                applicable=False,
            )
        )
        # …and in their place, the three tests that DO describe a lender.
        parts.extend(_bank_parts(periods, years))
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
    # ⚠ What this company's OWN test could offer, over its own components.
    # `coverage` divides by this rather than by a constant, which is what stops a fully-read
    # bank from looking like a half-read factory.
    possible = sum((p.available for p in parts if p.applicable), ZERO)
    return QualityScore(
        earned=earned,
        available=available,
        parts=parts,
        unknown=[p.name for p in parts if p.points is None and p.applicable],
        not_applicable=[p.name for p in parts if not p.applicable],
        possible=possible,
        years_read=len(years),
        history=history_for(db, instrument, years_read=len(years)),
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
    #
    # ⚠ The depth test is a SHARE of what this company's own test offers, not a count of
    # points. Under the old absolute rule a bank could be read completely and still fall one
    # point short of the bar for ever, because three of its ten points describe machinery it
    # does not own. What is withheld here is the box alone — every component and every figure
    # behind it is computed and returned regardless.
    coverage = quality.coverage
    if (
        coverage is None
        or coverage < MIN_COVERAGE_FOR_VERDICT
        or quality.available < MIN_AVAILABLE_FOR_VERDICT
        or "margin_of_safety" in quality.unknown
    ):
        return "BORDERLINE"
    # A single year can show promise and cannot show consistency. The half-weight cap already
    # keeps such a company away from a strong ratio; this keeps it away from a hard block too,
    # in both directions, rather than only the flattering one.
    if quality.years_read < MIN_YEARS_FOR_VERDICT:
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
