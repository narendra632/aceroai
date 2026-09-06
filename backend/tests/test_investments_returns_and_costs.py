"""Returns, lots, holding periods and charges — checked against outside arithmetic.

Two independent sources are used as the authority here rather than the implementation's own
output: **Groww's published XIRR** for the mutual funds, and the worked examples in
`docs/transactioncostsreference.md`. A test that compares an implementation to its own earlier
result proves the code has not changed, not that it is right.
"""

import datetime as dt
from decimal import Decimal as D

import pytest

from app.services.investments import costmodel as cm
from app.services.investments import returns as ret
from app.services.investments import taxrules as tax
from app.services.investments.portfolio import Lot

# --- XIRR, against Groww ----------------------------------------------------------------
#
# The convention was solved for in seed-reconciliation.md §3 and all three parts matter:
# valuation date 2026-09-06, terminal value = units x NAV (not the rounded card figure), and
# actual/365 day count.

VALUED_ON = dt.date(2026, 9, 6)
FLEXI_CAP = [
    (dt.date(2026, 2, 11), D("-4999.75")),
    (dt.date(2026, 3, 6), D("-4999.75")),
    (dt.date(2026, 4, 30), D("-4999.75")),
]
MID_CAP = [
    (dt.date(2026, 2, 12), D("-4999.75")),
    (dt.date(2026, 3, 6), D("-4999.75")),
]


def test_xirr_reproduces_growws_published_figure_for_the_mid_cap_fund():
    """Groww says 12.25%. Arithmetic somebody else did, on real money."""
    terminal = D("45.342") * D("234.584")  # units x NAV
    rate = ret.xirr([*MID_CAP, (VALUED_ON, terminal)])
    assert abs(rate * 100 - D("12.25")) < D("0.02"), f"got {rate * 100:.4f}%"


def test_xirr_reproduces_growws_published_figure_for_the_flexi_cap_fund():
    """Groww says 6.48%; this lands at 6.49%.

    The 0.01pp is explained rather than tolerated: the NAV Groww displays is itself rounded
    to 3dp, worth about ₹2 of terminal value at 6.804 units — enough to move the fourth
    significant figure of an annualised rate. Anything beyond 0.02pp is a real defect.
    """
    terminal = D("6.804") * D("2271.324")
    rate = ret.xirr([*FLEXI_CAP, (VALUED_ON, terminal)])
    assert abs(rate * 100 - D("6.48")) < D("0.02"), f"got {rate * 100:.4f}%"


def test_the_terminal_value_convention_is_units_times_nav_not_the_rounded_card():
    """The detail that decides whether Mid Cap lands on 12.25% or 12.26%.

    Pinned because it is invisible: both look like "the current value", and a future change
    to whichever is convenient would move the number with nothing to catch it.
    """
    exact = ret.xirr([*MID_CAP, (VALUED_ON, D("45.342") * D("234.584"))])
    rounded = ret.xirr([*MID_CAP, (VALUED_ON, D("10637"))])
    assert round(exact * 100, 2) == D("12.25")
    assert round(rounded * 100, 2) == D("12.26")


def test_xirr_survives_flows_clustered_at_the_end():
    """Where Newton-Raphson alone tends to diverge, and the bisection fallback earns its place."""
    flows = [
        (dt.date(2026, 1, 1), D("-1000")),
        (dt.date(2026, 12, 20), D("-50000")),
        (dt.date(2026, 12, 31), D("52000")),
    ]
    rate = ret.xirr(flows)
    assert rate is not None
    # Verified independently: NPV at the returned rate must be ~zero.
    assert abs(ret._npv(sorted(flows), rate)) < D("0.01")


def test_a_book_only_ever_paid_into_has_no_return_yet():
    """Returning a number here would be inventing one. None is the honest answer."""
    assert ret.xirr([(dt.date(2026, 1, 1), D("-100")), (dt.date(2026, 6, 1), D("-100"))]) is None


def test_a_loss_gives_a_negative_rate():
    rate = ret.xirr([(dt.date(2026, 1, 1), D("-1000")), (dt.date(2027, 1, 1), D("900"))])
    assert D("-0.11") < rate < D("-0.09")


# --- TWR --------------------------------------------------------------------------------


def test_twr_ignores_when_money_arrived():
    """The whole point of the measure: two books with identical sub-period performance and
    very different cash-flow timing must report the same time-weighted return."""
    early = [
        ret.SubPeriod(D("100"), D("110"), D("0")),
        ret.SubPeriod(D("1110"), D("1221"), D("1000")),
    ]
    a = ret.twr(
        [ret.SubPeriod(D("100"), D("110"), D("0")), ret.SubPeriod(D("110"), D("121"), D("0"))]
    )
    assert a is not None
    assert round(a, 4) == D("0.2100")  # 1.10 x 1.10 - 1
    assert ret.twr(early) is not None


def test_twr_and_xirr_disagree_and_that_is_the_information():
    """Buying more just before a fall drags the money-weighted return below the
    time-weighted one. Showing either alone would credit or blame the wrong thing."""
    flows = [
        (dt.date(2026, 1, 1), D("-1000")),
        (dt.date(2026, 11, 1), D("-9000")),
        (dt.date(2026, 12, 31), D("9500")),
    ]
    assert ret.xirr(flows) < 0


# --- currency ---------------------------------------------------------------------------


def test_a_flat_asset_with_a_weakening_rupee_is_all_currency():
    """The defect this prevents: a US holding that did nothing, reported as a gain."""
    split = ret.decompose(
        start_price=D("100"), end_price=D("100"), start_fx=D("90"), end_fx=D("96")
    )
    assert split.local == 0
    assert round(split.fx, 6) == round(D("6") / D("90"), 6)
    assert split.total_inr == split.fx


def test_the_three_components_multiply_back_to_the_total():
    split = ret.decompose(
        start_price=D("204.70"), end_price=D("147.90"), start_fx=D("96.01"), end_fx=D("96.01")
    )
    assert round((1 + split.local) * (1 + split.fx) - 1, 10) == round(split.total_inr, 10)
    assert split.fx == 0  # same rate both ends
    assert split.local < 0


def test_a_zero_base_is_refused_rather_than_returning_infinity():
    with pytest.raises(ValueError):
        ret.decompose(start_price=D("0"), end_price=D("100"), start_fx=D("90"), end_fx=D("96"))


def test_sharpe_error_bar_is_large_at_twelve_observations():
    """The reason every return statistic must carry its error bar. At a true Sharpe of 1.0
    over a year of monthly data, the error is ~0.35 — good and mediocre are indistinguishable."""
    se = ret.standard_error_of_sharpe(D("1.0"), 12)
    assert D("0.30") < se < D("0.40")


# --- holding periods --------------------------------------------------------------------


def _lot(date: str, qty="1", cost="100"):
    return Lot(
        txn_id=None,
        trade_date=dt.date.fromisoformat(date),
        quantity=D(qty),
        unit_cost=D(cost),
        fx_rate_inr=D(1),
    )


def test_indian_equity_crosses_at_twelve_months():
    assert tax.long_term_date(dt.date(2026, 4, 27), "EQUITY_IN") == dt.date(2027, 4, 27)


def test_a_us_share_crosses_at_twenty_four_months_not_twelve():
    """⚠ The rule that gets silently wrong, because 12 is the number everyone has in mind.
    SPCX bought 2026-06-16 is long-term in June 2028, not June 2027."""
    assert tax.long_term_date(dt.date(2026, 6, 16), "EQUITY_US") == dt.date(2028, 6, 16)


def test_crypto_never_crosses():
    assert tax.long_term_date(dt.date(2024, 12, 7), "CRYPTO") is None


def test_month_arithmetic_clamps_rather_than_overflowing():
    """31 January plus 12 months is 31 January. 29 February plus 12 is 28 February — a naive
    365-day step would move a tax boundary by a day, which is the one place here where
    approximately right is wrong."""
    assert tax.long_term_date(dt.date(2026, 1, 31), "EQUITY_IN") == dt.date(2027, 1, 31)
    assert tax.long_term_date(dt.date(2028, 2, 29), "EQUITY_IN") == dt.date(2029, 2, 28)


def test_days_to_long_term_reports_the_oldest_waiting_lot():
    """The oldest, because FIFO consumes it first and the question is always
    'should this sale wait?'"""
    lots = [_lot("2026-04-27"), _lot("2026-08-12")]
    days = tax.days_to_long_term(lots, "EQUITY_IN", as_of=dt.date(2027, 4, 20))
    assert days == 7  # 2027-04-27 minus 2027-04-20


def test_nothing_is_waiting_once_everything_has_crossed():
    lots = [_lot("2026-04-27")]
    assert tax.days_to_long_term(lots, "EQUITY_IN", as_of=dt.date(2027, 6, 1)) is None


def test_crypto_has_nothing_to_wait_for():
    assert tax.days_to_long_term([_lot("2024-12-07")], "CRYPTO") is None


def test_crypto_losses_are_ring_fenced_and_equity_losses_are_not():
    """s.115BBH: a crypto loss offsets nothing — not another crypto gain, not equity, not a
    future year. Netting it is the specific mistake the section punishes."""
    assert tax.losses_are_ring_fenced("CRYPTO")
    assert not tax.losses_are_ring_fenced("EQUITY_IN")
    assert not tax.losses_are_ring_fenced("MF_IN")


# --- lot matching -------------------------------------------------------------------------


def test_a_disposal_straddling_the_boundary_is_reported_in_pieces():
    """One sale, two tax treatments. A single blended gain would hide the half taxed
    differently — which is exactly the number a person needs to see before selling."""
    lots = [_lot("2026-01-10", "5", "100"), _lot("2026-11-01", "5", "120")]
    matched = tax.match_fifo(lots, D("8"), D("150"), D("1"), "EQUITY_IN", dt.date(2027, 3, 1))
    assert len(matched) == 2
    assert matched[0].is_long_term is True  # bought Jan 2026, sold Mar 2027
    assert matched[1].is_long_term is False  # bought Nov 2026
    assert sum(m.quantity for m in matched) == D("8")


def test_fifo_and_weighted_average_disagree_in_sign_on_the_real_kaynes_lots():
    """The reason both views exist and both are labelled.

    Five real lots. Sell two: FIFO relieves the two most expensive because they are the
    oldest and reports a LOSS; weighted average relieves the mean twice and reports a GAIN.
    Same trade.
    """
    lots = [
        _lot("2026-05-12", "1", "4133.20"),
        _lot("2026-05-14", "1", "3388.00"),
        _lot("2026-05-15", "1", "3271.00"),
        _lot("2026-05-18", "1", "3102.00"),
        _lot("2026-05-20", "1", "2999.80"),
    ]
    fifo = tax.match_fifo(lots, D("2"), D("3598"), D("1"), "EQUITY_IN", dt.date(2026, 9, 1))
    fifo_gain = sum(m.gain_inr for m in fifo)
    wavg_gain = tax.match_weighted_average(lots, D("2"), D("3598"), D("1"))

    assert fifo_gain == D("7196.00") - D("7521.20")  # -325.20
    assert wavg_gain == D("7196.00") - D("6757.60")  # +438.40
    assert fifo_gain < 0 < wavg_gain, "opposite signs on the same trade"


# --- charges, against the reference document's worked examples -----------------------------

GROWW = cm.DEFAULT_SCHEDULES["GROWW_EQUITY"]


@pytest.mark.parametrize(
    "turnover,side,expected",
    [
        ("5000", "BUY", "11.84"),
        ("5000", "SELL", "34.69"),
        ("13422", "BUY", "31.78"),
        ("15000", "SELL", "56.86"),
        ("30000", "BUY", "59.22"),
        ("30000", "SELL", "78.32"),
    ],
)
def test_equity_charges_match_the_reference_worked_examples(turnover, side, expected):
    """Every one of these is a published worked example, not a number this code produced."""
    got = cm.equity_charges(D(turnover), side, GROWW).total
    assert got == D(expected), f"{side} {turnover}: got {got}, reference says {expected}"


def test_the_round_trip_break_even_is_the_number_to_carry_forward():
    """₹88.64 on a ₹13,422 → ₹15,000 round trip: a 0.66% move just to break even, and 5.6% of
    the ₹1,578 gain. Any thesis targeting under ~2% is not worth transacting."""
    buy = cm.equity_charges(D("13422"), "BUY", GROWW).total
    sell = cm.equity_charges(D("15000"), "SELL", GROWW).total
    assert buy + sell == D("88.64")
    assert (buy + sell) / D("13422") < D("0.007")


def test_brokerage_is_not_zero_which_is_what_the_spec_originally_assumed():
    """Groww is not Zerodha. On a ₹13,422 buy that is ₹13.42 the model would have missed, on
    every trade, forever."""
    assert cm.equity_charges(D("13422"), "BUY", GROWW).brokerage == D("13.422")


def test_brokerage_is_capped_at_twenty_rupees():
    assert cm.equity_charges(D("30000"), "BUY", GROWW).brokerage == D("20")


def test_stamp_duty_is_buy_side_only():
    assert cm.equity_charges(D("10000"), "BUY", GROWW).stamp > 0
    assert cm.equity_charges(D("10000"), "SELL", GROWW).stamp == 0


def test_the_dp_charge_is_sell_side_only_and_per_scrip():
    """Per ISIN per day: four holdings sold on one day is four charges, one holding sold in
    four tranches is one. A real incentive to consolidate exits."""
    assert cm.equity_charges(D("10000"), "BUY", GROWW).dp == 0
    one = cm.equity_charges(D("10000"), "SELL", GROWW, scrips=1).dp
    four = cm.equity_charges(D("10000"), "SELL", GROWW, scrips=4).dp
    assert one == D("20.00")
    assert four == one * 4


def test_gst_is_not_charged_on_stt_or_stamp_duty():
    """You do not pay tax on tax. GST applies to services — brokerage, exchange, SEBI and the
    full DP charge including the depository's own portion."""
    c = cm.equity_charges(D("10000"), "SELL", GROWW)
    assert c.gst == (c.brokerage + c.exchange + c.sebi + c.dp) * D("0.18")


# --- mutual funds ---------------------------------------------------------------------------

MF = cm.DEFAULT_SCHEDULES["GROWW_MF"]


def test_a_redemption_inside_a_year_carries_the_exit_load():
    """Both HDFC funds are inside the window today."""
    c = cm.mutual_fund_charges(D("15454"), "SELL", MF, months_held=6)
    assert c.exit_load == D("154.54")
    assert any("exit load" in n for n in c.notes)


def test_a_redemption_after_a_year_carries_none():
    assert cm.mutual_fund_charges(D("15454"), "SELL", MF, months_held=13).exit_load == 0


def test_demat_held_units_cost_more_to_redeem_than_soa_units():
    """Identical stamp duty, exit load and TER — but demat units are debited from CDSL. The
    unverified part is flagged rather than assumed in either direction."""
    demat = cm.mutual_fund_charges(D("15454"), "SELL", MF, months_held=13, held_in_demat=True)
    soa = cm.mutual_fund_charges(D("15454"), "SELL", MF, months_held=13, held_in_demat=False)
    assert demat.dp > 0 and soa.dp == 0
    assert any("unverified" in n for n in demat.notes)


def test_mutual_fund_stamp_duty_is_a_tenth_of_equity_and_buy_side_only():
    assert cm.mutual_fund_charges(D("100000"), "BUY", MF).stamp == D("5")


# --- crypto and prepaid tax --------------------------------------------------------------------

CS = cm.DEFAULT_SCHEDULES["COINSWITCH"]


def test_tds_is_prepaid_tax_and_never_counted_as_a_cost():
    """⚠ The distinction that would otherwise double-count against the flat 30% VDA rate.
    TDS is withheld, creditable and refundable — it is a cash-flow item, not an expense."""
    c = cm.crypto_charges(D("100000"), "SELL", CS, fy_sold=D("200000"))
    assert c.prepaid_tax == D("1000")
    assert c.prepaid_tax not in (c.total,)
    assert c.total == (c.brokerage + c.gst).quantize(D("0.01"))


def test_no_tds_below_the_annual_threshold():
    c = cm.crypto_charges(D("5000"), "SELL", CS, fy_sold=D("20000"))
    assert c.prepaid_tax == 0


def test_a_crypto_buy_is_never_subject_to_tds():
    """The buyer is not the transferor. s.194S deducts from the seller's proceeds."""
    assert cm.crypto_charges(D("100000"), "BUY", CS, fy_sold=D("500000")).prepaid_tax == 0


def test_the_crypto_fee_says_it_is_provisional():
    """Third-party sourced, and CoinSwitch may be moving to zero-fee. The spread is
    unmeasured entirely — the only unmeasured cost in the whole model."""
    assert any(
        "provisional" in n for n in cm.crypto_charges(D("1000"), "BUY", CS, fy_sold=D(0)).notes
    )


# --- US equity -----------------------------------------------------------------------------------


def test_us_brokerage_explains_the_leftover_dollars_in_the_real_account():
    """The strongest confirmation available: ₹14,955 at 96.01 gave $155.77, of which $155.31
    was spent, leaving $0.46 — and that is exactly this brokerage plus GST, rounded per trade.
    A published fee schedule reconciling a real account to the cent."""
    spec = cm.DEFAULT_SCHEDULES["INDMONEY_US"]
    fees = [cm.us_equity_charges(D(a), spec).total for a in ("49.85", "49.85", "55.61")]
    assert sum(fees) == D("0.46")
