"""Return measures. Pure Python and `Decimal` — no numpy, no pandas, no dependencies.

**Two numbers, always together.** XIRR is money-weighted: it is affected by *when* money went
in, so it measures the investor's timing. TWR is time-weighted: it removes cash-flow timing,
so it measures the strategy. Showing either alone invites crediting the wrong thing, and the
gap between them is itself the interesting quantity.

`quantstats`, `pyfolio` and `empyrical` were considered and rejected: pandas + numpy + scipy +
matplotlib + seaborn + yfinance on a 1 GB box, to obtain about ten formulas that come to some
150 lines. `pyfolio` is effectively unmaintained.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

DAYS_PER_YEAR = Decimal(365)

#: Newton–Raphson settings. It converges in under ten iterations on ordinary flows and can
#: shoot off to nonsense on awkward ones — flows clustered near the end, or a book briefly
#: worth less than nothing — which is what the bisection fallback exists for.
_GUESS = Decimal("0.10")
_MAX_ITERATIONS = 100
_TOLERANCE = Decimal("1e-9")
_BRACKET_LOW = Decimal("-0.9999")
_BRACKET_HIGH = Decimal(10)
_BISECTION_STEPS = 200


def _npv(flows: Sequence[tuple[dt.date, Decimal]], rate: Decimal) -> Decimal:
    """Net present value of dated flows at `rate`, discounting on actual/365.

    ⚠ The day count is part of the answer, not an implementation detail. Groww's published
    XIRR is reproduced only on actual/365 — see `seed-reconciliation.md` §3.
    """
    origin = flows[0][0]
    total = Decimal(0)
    base = Decimal(1) + rate
    for when, amount in flows:
        years = Decimal((when - origin).days) / DAYS_PER_YEAR
        total += amount / _power(base, years)
    return total


def _power(base: Decimal, exponent: Decimal) -> Decimal:
    """`base ** exponent` for a fractional exponent, staying in Decimal.

    Decimal has no fractional power, so this routes through the natural log — which is exact
    enough at 28 significant digits and keeps the whole calculation off floats. A float here
    would be invisible until it moved the fourth decimal of an annualised rate.
    """
    if base <= 0:
        raise ValueError("rate below -100% has no real discount factor")
    if exponent == 0:
        return Decimal(1)
    return (base.ln() * exponent).exp()


def xirr(flows: Sequence[tuple[dt.date, Decimal]]) -> Decimal | None:
    """Money-weighted annualised return. None when the flows cannot define one.

    Requires at least one flow of each sign: a book that has only ever been paid into has no
    return until it is marked, and returning a number there would be inventing one.
    """
    if len(flows) < 2:
        return None
    flows = sorted(flows, key=lambda f: f[0])
    signs = {amount > 0 for _, amount in flows if amount != 0}
    if len(signs) < 2:
        return None

    rate = _GUESS
    for _ in range(_MAX_ITERATIONS):
        try:
            value = _npv(flows, rate)
            nudge = Decimal("0.0000001")
            slope = (_npv(flows, rate + nudge) - value) / nudge
        except (ValueError, ArithmeticError):
            break
        if slope == 0:
            break
        step = value / slope
        rate -= step
        if abs(step) < _TOLERANCE:
            return rate
        if rate <= _BRACKET_LOW:
            break

    return _bisect(flows)


def _bisect(flows: Sequence[tuple[dt.date, Decimal]]) -> Decimal | None:
    """Bisection over a bracketed sign change. Cannot diverge, which is the whole point."""
    low, high = _BRACKET_LOW, _BRACKET_HIGH
    try:
        if _npv(flows, low) * _npv(flows, high) > 0:
            return None
    except (ValueError, ArithmeticError):
        return None
    for _ in range(_BISECTION_STEPS):
        mid = (low + high) / 2
        if _npv(flows, low) * _npv(flows, mid) <= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


@dataclass(frozen=True)
class SubPeriod:
    """One stretch between external cash flows, for chaining a time-weighted return."""

    start_value: Decimal
    end_value: Decimal
    net_flow: Decimal
    #: Weight of the flow within the period, for Modified Dietz. 0.5 when the timing inside
    #: the period is unknown, which is the honest default for a daily ledger.
    flow_weight: Decimal = Decimal("0.5")


def twr(periods: Sequence[SubPeriod]) -> Decimal | None:
    """Time-weighted return, chained across sub-periods. None when it cannot be computed.

    Where the timing of a flow inside a period is unknown, Modified Dietz weights it rather
    than pretending it landed at one end. A daily ledger genuinely does not know the hour, and
    assuming start-of-day or end-of-day biases the result in a direction nobody chose.
    """
    if not periods:
        return None
    product = Decimal(1)
    for p in periods:
        denominator = p.start_value + (p.net_flow * p.flow_weight)
        if denominator == 0:
            continue
        product *= Decimal(1) + ((p.end_value - p.start_value - p.net_flow) / denominator)
    return product - Decimal(1)


@dataclass(frozen=True)
class CurrencySplit:
    """A foreign holding's return, taken apart. All three, never just the total."""

    local: Decimal
    fx: Decimal
    total_inr: Decimal


def decompose(
    *, start_price: Decimal, end_price: Decimal, start_fx: Decimal, end_fx: Decimal
) -> CurrencySplit:
    """Separate what the asset did from what the currency did.

    `(1 + r_total) = (1 + r_local) x (1 + r_fx)`.

    ⚠ Mandatory on every non-INR holding, and not a nicety. Without it a weakening rupee
    silently credits the system with skill it does not have — the easiest way for a record
    like this to flatter itself, and one that compounds quietly across a whole year.
    """
    if start_price == 0 or start_fx == 0:
        raise ValueError("cannot decompose a return from a zero base")
    r_local = (end_price / start_price) - Decimal(1)
    r_fx = (end_fx / start_fx) - Decimal(1)
    r_total = ((Decimal(1) + r_local) * (Decimal(1) + r_fx)) - Decimal(1)
    return CurrencySplit(local=r_local, fx=r_fx, total_inr=r_total)


def standard_error_of_sharpe(sharpe: Decimal, observations: int) -> Decimal | None:
    """`SE(SR) ~ sqrt((1 + SR^2/2) / N)`. None below two observations.

    Here in Phase 1, unused until the reviews exist, because the *reason* for it belongs with
    the formula: at twelve monthly observations and a true Sharpe of 1.0 the standard error is
    about 0.35, which means a genuinely good strategy and a mediocre one are statistically
    indistinguishable over one year. Every return statistic this system displays is required
    to carry its error bar, and a number without one is how a system like this misleads.
    """
    if observations < 2:
        return None
    inner = (Decimal(1) + (sharpe * sharpe / 2)) / Decimal(observations)
    return inner.sqrt()
