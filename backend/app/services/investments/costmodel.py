"""What a transaction actually costs, from a dated schedule.

Every rate here comes from `docs/transactioncostsreference.md`, verified 2026-09-06 with
sources. It exists because the module spec originally modelled **Zerodha's** charge sheet and
called it "most discount brokers". It is not: Groww charges `min(₹20, 0.1%)` floored at ₹5 on
**both legs** of a delivery trade where the spec assumed zero, and its DP charge is ₹23.60
against Zerodha's ₹15.34.

That matters more than it sounds. A ₹13,422 buy and a ₹15,000 sell costs **₹88.64 round trip
— a 0.66% break-even move, and 5.6% of a ₹1,578 gain.** A paper book that ignores it
systematically overstates returns and can never be compared with the real one.

**Rates are read from `charge_schedules` by effective date and the schedule id is frozen onto
the transaction**, exactly as `core/pricing.py` freezes model prices. Recomputing March's
charges at October's rates would silently rewrite March's return.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import ChargeSchedule

PAISA = Decimal("0.01")
ZERO = Decimal(0)

#: The schedule this application ships with, keyed by venue. Written into the database by the
#: seeding script rather than read from here at runtime — this constant is the *source*, and
#: `charge_schedules` is the versioned record of what was in force when.
#:
#: ⚠ `brokerage_rate` is the one figure two of Groww's own pages agree on (0.1%) while two
#: aggregators claim 0.05%. Modelled at 0.1% because it is official AND because overstating
#: cost is the safe direction for a paper book. Settle it from a contract note between
#: ₹20,000 and ₹40,000 turnover: exactly ₹20 means 0.1%, less means 0.05%.
DEFAULT_SCHEDULES: dict[str, dict] = {
    "GROWW_EQUITY": {
        "brokerage_rate": "0.001",
        "brokerage_cap": "20",
        "brokerage_floor": "5",
        "stt_rate": "0.001",
        "exchange_rate_nse": "0.0000307",
        "exchange_rate_bse": "0.0000375",
        "sebi_rate": "0.000001",
        "stamp_rate": "0.00015",
        "gst_rate": "0.18",
        "dp_cdsl": "3.50",
        "dp_broker_markup": "16.50",
        "dp_markup_min_value": "100",
    },
    "GROWW_MF": {
        "stamp_rate": "0.00005",
        "exit_load_rate": "0.01",
        "exit_load_months": 12,
        #: ⚠ Units held in demat are debited from CDSL on redemption, so a DP charge applies
        #: where SOA units incur none. Narendra's are demat (folio 40754072). Whether Groww
        #: adds its ₹16.50 markup to a mutual-fund debit is UNVERIFIED, so the certain part is
        #: modelled and the unknown part is flagged rather than assumed either way.
        "dp_cdsl": "3.25",
        "dp_broker_markup_unverified": True,
        "gst_rate": "0.18",
    },
    "COINSWITCH": {
        "trading_fee_rate": "0.004",
        "gst_rate": "0.18",
        #: Withheld tax, NOT a cost — see `prepaid_tax`. Sell side only, above an annual
        #: threshold of ₹50,000 for a person with no business income.
        "tds_rate": "0.01",
        "tds_threshold_inr": "50000",
        "provisional": True,
    },
    "INDMONEY_US": {
        "brokerage_rate": "0.0025",
        "brokerage_cap_usd": "25",
        "gst_rate": "0.18",
        #: Charged on the REMITTANCE, not per trade — conversion happens once when rupees
        #: become dollars. Calibrated from the real remittance: ₹14,955 at 96.01.
        "fx_markup_note": "on remittance, calibrate from the received rate",
        "tcs_rate": "0.20",
        "tcs_threshold_inr": "1000000",
    },
}


@dataclass
class Charges:
    """What a transaction cost, itemised so a contract note can be reconciled line by line."""

    brokerage: Decimal = ZERO
    stt: Decimal = ZERO
    exchange: Decimal = ZERO
    sebi: Decimal = ZERO
    stamp: Decimal = ZERO
    dp: Decimal = ZERO
    gst: Decimal = ZERO
    exit_load: Decimal = ZERO
    #: ⚠ Deliberately NOT part of `total`. Withheld against a future liability, creditable and
    #: refundable — booking it as expense would understate the return AND double-count against
    #: the flat 30% VDA rate.
    prepaid_tax: Decimal = ZERO
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        """Everything that is genuinely a cost. Prepaid tax is not."""
        return (
            self.brokerage
            + self.stt
            + self.exchange
            + self.sebi
            + self.stamp
            + self.dp
            + self.gst
            + self.exit_load
        ).quantize(PAISA, ROUND_HALF_UP)


def schedule_for(db: Session, venue: str, on: dt.date) -> ChargeSchedule | None:
    """The schedule in force at a date — the newest whose `effective_from` has passed."""
    return db.execute(
        sa.select(ChargeSchedule)
        .where(ChargeSchedule.venue == venue, ChargeSchedule.effective_from <= on)
        .order_by(ChargeSchedule.effective_from.desc())
        .limit(1)
    ).scalar_one_or_none()


def equity_charges(
    turnover: Decimal, side: str, spec: dict, *, exchange: str = "NSE", scrips: int = 1
) -> Charges:
    """Indian equity delivery, on Groww.

    `scrips` because the DP charge is **per ISIN per day**, not per trade: selling one holding
    in four tranches on one day incurs it once, selling four holdings incurs it four times.
    That asymmetry is a real incentive to consolidate exits, and the decision engine should
    eventually surface it.
    """
    c = Charges()
    rate = Decimal(spec["brokerage_rate"])
    cap = Decimal(spec["brokerage_cap"])
    floor = Decimal(spec["brokerage_floor"])

    c.brokerage = min(cap, turnover * rate)
    if c.brokerage < floor:
        # SEBI caps brokerage at 2.5% of turnover, which binds before the floor on a very
        # small trade — otherwise a ₹100 trade would carry a ₹5 charge.
        c.brokerage = min(floor, turnover * Decimal("0.025"))

    c.stt = turnover * Decimal(spec["stt_rate"])  # both legs, delivery
    exch_rate = spec["exchange_rate_nse"] if exchange == "NSE" else spec["exchange_rate_bse"]
    c.exchange = turnover * Decimal(exch_rate)
    c.sebi = turnover * Decimal(spec["sebi_rate"])

    if side == "BUY":
        c.stamp = turnover * Decimal(spec["stamp_rate"])
    else:
        dp = Decimal(spec["dp_cdsl"])
        if turnover >= Decimal(spec["dp_markup_min_value"]):
            dp += Decimal(spec["dp_broker_markup"])
        c.dp = dp * scrips

    # ⚠ GST applies to services, never to taxes: brokerage, exchange, SEBI and the FULL DP
    # charge including the depository's own portion. NOT to STT or stamp duty — you do not
    # pay tax on tax.
    c.gst = (c.brokerage + c.exchange + c.sebi + c.dp) * Decimal(spec["gst_rate"])
    return c


def mutual_fund_charges(
    amount: Decimal,
    side: str,
    spec: dict,
    *,
    months_held: int | None = None,
    held_in_demat: bool = False,
) -> Charges:
    """Indian mutual funds, direct plans. Zero commission; the costs are elsewhere.

    Exit load is 1% within a year **of each lot's own allotment**, so it is a per-lot
    calculation and reuses `taxrules.match_fifo` rather than getting a second matcher — the
    rule is identical to holding-period matching and duplicating it would let the two drift.
    """
    c = Charges()
    if side == "BUY":
        c.stamp = amount * Decimal(spec["stamp_rate"])
        return c

    if months_held is not None and months_held < int(spec["exit_load_months"]):
        c.exit_load = amount * Decimal(spec["exit_load_rate"])
        c.notes.append(f"exit load: redeemed {months_held} months in, under the 12-month bar")

    if held_in_demat:
        c.dp = Decimal(spec["dp_cdsl"])
        c.gst = c.dp * Decimal(spec["gst_rate"])
        if spec.get("dp_broker_markup_unverified"):
            c.notes.append(
                "demat redemption: CDSL's charge is modelled; whether Groww adds its markup "
                "to a mutual-fund debit is unverified. SOA-held units incur neither."
            )
    return c


def crypto_charges(consideration: Decimal, side: str, spec: dict, *, fy_sold: Decimal) -> Charges:
    """CoinSwitch. The fee is provisional; the TDS is not a fee at all.

    ⚠ `trading_fee_rate` is third-party sourced and CoinSwitch may be moving to zero-fee —
    modelled at the top of the published tier, which is the right assumption for an account
    with no volume history and the safe direction for a paper book.

    The **spread** is the one unmeasured cost in this whole model. CoinSwitch routes across
    liquidity sources and publishes nothing, so the only way to know it is to log the
    mid-market price at order time and compare to the fill. Worth doing from day one.
    """
    c = Charges()
    c.brokerage = consideration * Decimal(spec["trading_fee_rate"])
    c.gst = c.brokerage * Decimal(spec["gst_rate"])
    if spec.get("provisional"):
        c.notes.append("trading fee is provisional; spread is unmeasured — log fills to learn it")

    if side == "SELL" and fy_sold > Decimal(spec["tds_threshold_inr"]):
        # Prepaid, creditable, refundable. Kept out of `total` on purpose.
        c.prepaid_tax = consideration * Decimal(spec["tds_rate"])
        c.notes.append("1% TDS withheld — prepaid tax, creditable, not a cost")
    return c


def us_equity_charges(trade_value_usd: Decimal, spec: dict) -> Charges:
    """INDmoney. Brokerage is small; the FX markup is the real cost and sits elsewhere.

    ⚠ The markup is charged on the **remittance**, not the trade, because conversion happens
    once when rupees become dollars. Modelling it per trade would both misplace it and
    multiply it. It is calibrated from the rate actually received rather than assumed: the
    real remittance converted ₹14,955 at 96.01, and the $0.46 left after three purchases is
    exactly this brokerage plus GST — which is how this figure was confirmed.
    """
    c = Charges()
    c.brokerage = min(
        Decimal(spec["brokerage_cap_usd"]), trade_value_usd * Decimal(spec["brokerage_rate"])
    )
    c.gst = c.brokerage * Decimal(spec["gst_rate"])
    return c
