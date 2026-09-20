"""The quality score: what it answers, and the far more important question of what it won't.

A test suite for a scorer naturally checks that good companies score well. That is the easy
half and not the half that matters. The failure this module is built against is a **pipeline
problem wearing a judgement's clothes** — a company marked poor because its filings had not
been read, which from the outside is indistinguishable from a company that is actually poor.

So most of what follows asserts that thin data produces *unknown*, that unknown is not zero,
and that a verdict strong enough to block a purchase is refused on a partial reading.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import Fundamental, PriceObservation, SourceItem
from app.services.investments import framework_data, scoring
from app.services.marketdata import nse_xbrl
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def company(db):
    def make(symbol="SCORECO", sector="EMS_ELECTRONICS"):
        inst = make_instrument(
            db,
            symbol=symbol,
            exchange="NSE",
            name=f"{symbol} Industries",
            asset_class="EQUITY_IN",
            currency="INR",
            sector=sector,
        )
        db.add(inst)
        db.flush()
        return inst

    return make


def _file(db, instrument, period: str, **metrics):
    """Store one year's figures as though a filing had been read."""
    end = dt.date(int(period[2:4]) + 2000, 3, 31)
    source = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=instrument.id,
        source=nse_xbrl.PROVIDER,
        external_id=f"{instrument.symbol}-{period}-{uuid.uuid4().hex[:6]}",
        url="https://x/f.xml",
        title=f"{instrument.symbol} {period}",
        published_at=dt.datetime.combine(end, dt.time(0, 0), dt.UTC),
        fetched_at=dt.datetime.now(dt.UTC),
        content_hash=uuid.uuid4().hex,
        excerpt="<x:Tag>1</x:Tag>",
    )
    db.add(source)
    db.flush()
    for metric, value in metrics.items():
        db.add(
            Fundamental(
                instrument_id=instrument.id,
                fiscal_period=period,
                metric_key=metric,
                source_item_id=source.id,
                value=D(str(value)),
                unit="inr",
                period_end=end,
                consolidated=True,
                taxonomy="INDAS",
            )
        )
    db.commit()
    return source


def _price(db, instrument, value, days_ago=0):
    db.add(
        PriceObservation(
            instrument_id=instrument.id,
            observed_at=dt.datetime.combine(
                TODAY - dt.timedelta(days=days_ago), dt.time(10, 0), dt.UTC
            ),
            source=TEST_SOURCE,
            kind="CLOSE",
            price=D(str(value)),
            currency="INR",
        )
    )
    db.commit()


def _part(score, name):
    return next(p for p in score.parts if p.name == name)


# --- the refusals ------------------------------------------------------------------------


def test_a_company_with_no_filings_scores_nothing_rather_than_badly(db, company, spec):
    """⚠ The failure this module exists to prevent. Zero here is indistinguishable from a
    company that genuinely earns nothing, and nothing in the interface could tell them apart."""
    score = scoring.quality_score(db, company(), spec)
    assert score.earned == D(0)
    assert score.available == D(0), "nothing was measurable, so nothing was available"
    assert score.ratio is None
    assert set(score.unknown) >= {"roe", "roce", "cash_conversion", "margin_of_safety"}


def test_one_year_is_a_snapshot_and_does_not_answer_a_five_year_question(db, company, spec):
    """⚠ The rule is 'at or above 15% in three of the last five years'. With one year read it
    cannot be satisfied, so scoring zero is arithmetically right and epistemically wrong."""
    inst = company()
    _file(db, inst, "FY26", pat=D(300), equity=D(1000), pbt=D(400), finance_costs=D(10))

    score = scoring.quality_score(db, inst, spec)
    roe = _part(score, "roe")
    assert roe.points is None
    assert "1 year(s)" in roe.detail


def test_two_years_of_a_strong_return_is_evidence_and_is_scored(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(300), equity=D(1000), pbt=D(400), finance_costs=D(10))

    roe = _part(scoring.quality_score(db, inst, spec), "roe")
    assert roe.points is not None
    assert "2 of 2 year(s)" in roe.detail
    assert "fewer than five years" in roe.detail, "the reader must not mistake it for five"


def test_the_score_names_what_it_could_not_measure(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(300), equity=D(1000))

    score = scoring.quality_score(db, inst, spec)
    assert "cash_conversion" in score.unknown
    assert not score.is_complete
    assert score.available < D(10), "unmeasured components are not in the denominator"


# --- a bank is a different animal -----------------------------------------------------------


def test_a_bank_is_not_failed_on_arithmetic_about_things_it_does_not_have(db, company, spec):
    """⚠ Without this the portfolio's anchor holding classes as a value trap and the gates
    block adding to it for ever. Borrowings are a bank's raw material, not its leverage."""
    bank = company(symbol="SCOREBANK", sector="PRIVATE_BANK")
    for period in ("FY26", "FY25"):
        _file(db, bank, period, pat=D(760), share_capital=D(15), other_equity=D(5800))

    score = scoring.quality_score(db, bank, spec)
    for name in ("roce", "cash_conversion", "balance_sheet"):
        part = _part(score, name)
        assert part.points is None, f"{name} must be unmeasured for a bank, not zero"
        assert "bank" in part.detail.lower()
    assert _part(score, "roe").points is not None, "return on equity DOES describe a bank"


# --- the arithmetic --------------------------------------------------------------------------


def test_return_on_capital_adds_back_what_was_paid_to_lenders(db, company, spec):
    """Return on CAPITAL asks what the whole capital base earned, before deciding who it went
    to. Omitting finance costs measures the equity holder's slice and calls it the business."""
    inst = company()
    for period in ("FY26", "FY25"):
        _file(
            db,
            inst,
            period,
            pbt=D(160),
            finance_costs=D(40),
            equity=D(1000),
            borrowings_current=D(0),
            borrowings_noncurrent=D(0),
        )
    # (160 + 40) / 1000 = 20%
    assert "20.0%" in _part(scoring.quality_score(db, inst, spec), "roce").detail


def test_cash_that_never_arrives_is_scored_as_such(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(100), ocf=D(-165), equity=D(500))
    part = _part(scoring.quality_score(db, inst, spec), "cash_conversion")
    assert part.points == D(0)
    assert "-1.65" in part.detail


def test_a_margin_of_safety_needs_a_price_and_says_so_without_one(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(100), dep_amort=D(10), equity=D(500))
    part = _part(scoring.quality_score(db, inst, spec), "margin_of_safety")
    assert part.points is None and "market value" in part.detail


def test_a_cheap_company_earns_the_margin_of_safety_and_an_expensive_one_does_not(
    db, company, spec
):
    """⚠ Trailing reported earnings, never a forecast: no filing contains next year's profit,
    so a forecast cannot be checked against anything."""
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(100), dep_amort=D(10), equity=D(500))
    # EMS_ELECTRONICS is 25x, so a worth of 2,500 on earnings of 100.
    cheap = scoring.quality_score(db, inst, spec, market_cap=D(1000))
    dear = scoring.quality_score(db, inst, spec, market_cap=D(5000))

    assert _part(cheap, "margin_of_safety").points == D(2)
    assert _part(dear, "margin_of_safety").points == D(0)
    assert "ABOVE" in _part(dear, "margin_of_safety").detail


def test_an_unpriced_sector_says_the_default_multiple_was_used(db, company, spec):
    """A margin of safety from a guessed multiple looks computed and is not."""
    odd = company(symbol="SCORESEA", sector="SEAWEED_FARMING")
    for period in ("FY26", "FY25"):
        _file(db, odd, period, pat=D(100), dep_amort=D(10), equity=D(500))
    part = _part(scoring.quality_score(db, odd, spec, market_cap=D(1000)), "margin_of_safety")
    assert "default multiple" in part.detail


def test_every_scored_component_carries_the_filings_it_rested_on(db, company, spec):
    """D3: a figure that cannot be pointed back at a filing has no business in a thesis."""
    inst = company()
    for period in ("FY26", "FY25"):
        _file(db, inst, period, pat=D(300), equity=D(1000))
    roe = _part(scoring.quality_score(db, inst, spec), "roe")
    assert len(roe.cites) == 2 and all(isinstance(c, uuid.UUID) for c in roe.cites)


# --- the quadrant refuses to convict on thin evidence --------------------------------------


def test_a_thin_reading_never_produces_a_hard_verdict(db, company, spec):
    """⚠ Two of the four quadrants hard-block a purchase. A company blocked because its
    filings have not been read is indistinguishable from one blocked because it deserves it."""
    inst = company()
    # Nothing measurable at all: not even a denominator.
    bare = scoring.quality_score(db, company(symbol="SCORENONE"), spec)
    assert scoring.quadrant(bare, reflexivity_high=False) == "UNKNOWN"

    # One measurable component and a price: still not enough to convict.
    _file(db, inst, "FY26", pat=D(1), dep_amort=D(1), equity=D(1000))
    _file(db, inst, "FY25", pat=D(1), dep_amort=D(1), equity=D(1000))
    score = scoring.quality_score(db, inst, spec, market_cap=D(90000))
    assert score.available < scoring.MIN_AVAILABLE_FOR_VERDICT
    assert scoring.quadrant(score, reflexivity_high=False) == "BORDERLINE"
    assert scoring.quadrant(score, reflexivity_high=True) not in ("Q1", "Q2", "Q3", "Q4"), (
        "neither reading may reach a box that blocks or permits a purchase"
    )


def test_a_missing_price_alone_withholds_the_verdict(db, company, spec):
    """Price is half the question a quality-and-price score answers."""
    inst = company()
    for period in ("FY26", "FY25"):
        _file(
            db,
            inst,
            period,
            pat=D(300),
            equity=D(1000),
            pbt=D(400),
            finance_costs=D(10),
            ocf=D(300),
            dep_amort=D(20),
            cash=D(50),
            borrowings_current=D(0),
            borrowings_noncurrent=D(0),
        )
    score = scoring.quality_score(db, inst, spec)
    assert "margin_of_safety" in score.unknown
    assert scoring.quadrant(score, reflexivity_high=False) == "BORDERLINE"


def test_a_complete_reading_does_produce_a_verdict(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(
            db,
            inst,
            period,
            pat=D(300),
            equity=D(1000),
            pbt=D(400),
            finance_costs=D(10),
            ocf=D(300),
            dep_amort=D(20),
            cash=D(50),
            borrowings_current=D(0),
            borrowings_noncurrent=D(0),
        )
    score = scoring.quality_score(db, inst, spec, market_cap=D(2000))
    assert scoring.quadrant(score, reflexivity_high=False) == "Q3"
    assert scoring.quadrant(score, reflexivity_high=True) == "Q1"


def test_a_poor_company_with_a_hot_story_is_a_different_box_from_a_quiet_one(db, company, spec):
    inst = company()
    for period in ("FY26", "FY25"):
        _file(
            db,
            inst,
            period,
            pat=D(1),
            equity=D(1000),
            pbt=D(2),
            finance_costs=D(0),
            ocf=D(-50),
            dep_amort=D(20),
            cash=D(0),
            borrowings_current=D(900),
            borrowings_noncurrent=D(900),
        )
    score = scoring.quality_score(db, inst, spec, market_cap=D(90000))
    assert scoring.quadrant(score, reflexivity_high=True) == "Q2", "a story without a business"
    assert scoring.quadrant(score, reflexivity_high=False) == "Q4", "cheap for a reason"


# --- the flags that are measured -------------------------------------------------------------


def test_a_flag_with_no_data_says_unknown_rather_than_no(db, company):
    """⚠ 'No' is a finding. 'Unknown' is the truth when nothing was read, and a checklist that
    answers NO by default reports a clean bill of health it never checked."""
    flags = {f.number: f for f in scoring.computed_flags(db, company())}
    assert flags[2].verdict == "UNKNOWN"
    assert flags[6].verdict == "UNKNOWN"
    assert flags[10].verdict == "UNKNOWN"


def test_a_falling_return_is_flagged(db, company):
    inst = company()
    _file(db, inst, "FY26", pat=D(50), equity=D(1000))
    _file(db, inst, "FY25", pat=D(100), equity=D(1000))
    _file(db, inst, "FY24", pat=D(200), equity=D(1000))
    flags = {f.number: f for f in scoring.computed_flags(db, inst)}
    assert flags[2].verdict == "YES"
    assert "below 15%" in flags[2].evidence


def test_margins_slipping_while_revenue_grows_is_flagged(db, company):
    inst = company()
    _file(db, inst, "FY26", revenue=D(2000), pbt=D(100))
    _file(db, inst, "FY25", revenue=D(1000), pbt=D(200))
    flags = {f.number: f for f in scoring.computed_flags(db, inst)}
    assert flags[8].verdict == "YES"
    assert "grew" in flags[8].evidence


def test_margins_slipping_while_revenue_also_falls_is_not_that_flag(db, company):
    """The question is specifically about deteriorating unit economics AS the business scales."""
    inst = company()
    _file(db, inst, "FY26", revenue=D(500), pbt=D(25))
    _file(db, inst, "FY25", revenue=D(1000), pbt=D(200))
    flags = {f.number: f for f in scoring.computed_flags(db, inst)}
    assert flags[8].verdict == "NO"


def test_a_wide_52_week_range_is_flagged(db, company):
    inst = company()
    for offset, price in enumerate(range(100, 200, 2)):
        _price(db, inst, price, days_ago=300 - offset)
    flags = {f.number: f for f in scoring.computed_flags(db, inst)}
    assert flags[10].verdict == "YES", "a 98% range is a market that changed its mind"
    assert "%" in flags[10].evidence


def test_a_narrow_range_is_not_flagged(db, company):
    inst = company()
    for offset in range(60):
        _price(db, inst, 100 + (offset % 5), days_ago=200 - offset)
    flags = {f.number: f for f in scoring.computed_flags(db, inst)}
    assert flags[10].verdict == "NO"


def test_a_multiple_outrunning_earnings_is_flagged(db, company):
    """The classic reflexive signature: the price re-rates far faster than the business."""
    inst = company()
    _file(db, inst, "FY26", pat=D(110), paid_up_capital=D(100), face_value=D(10))
    _file(db, inst, "FY25", pat=D(100), paid_up_capital=D(100), face_value=D(10))
    for offset in range(60):
        _price(db, inst, 100, days_ago=390 - offset)
    flags = {f.number: f for f in scoring.computed_flags(db, inst, price=D(300))}
    assert flags[6].verdict == "YES"


def test_every_flag_is_a_red_flag(db, company):
    """⚠ YES is bad, on all ten. A reader who assumes otherwise reads the checklist backwards."""
    inst = company()
    for flag in scoring.computed_flags(db, inst):
        assert flag.verdict in ("YES", "NO", "UNKNOWN")
        assert flag.question.endswith("?")
        assert flag.computed, "these four are measured, so no model verdict may overrule them"
