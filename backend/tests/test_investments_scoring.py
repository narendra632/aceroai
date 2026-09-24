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


def test_one_year_is_scored_at_half_weight_rather_than_refused(db, company, spec):
    """⚠ The rule is 'at or above 15% in three of the last five years', and one year cannot
    satisfy it. Refusing to answer is the wrong repair: it is unsatisfiable rather than
    strict, so a recently-listed company stayed beyond judgement no matter how good it was.
    One year is scored, at half weight, and says which."""
    inst = company()
    _file(db, inst, "FY26", pat=D(300), equity=D(1000), pbt=D(400), finance_costs=D(10))

    score = scoring.quality_score(db, inst, spec)
    roe = _part(score, "roe")
    assert roe.points == D(1), "a 30% return on one year earns half of two, not nothing"
    assert "1 of 1 year(s) read" in roe.detail
    assert "snapshot" in roe.detail, "the reader must not mistake one year for a record"
    assert score.years_read == 1


def test_a_single_year_never_reaches_a_box_that_blocks_or_blesses(db, company, spec):
    """Scoring one year is not the same as trusting it. The score is published; the verdict
    waits for a second year, and arrives by itself when one lands."""
    inst = company()
    _file(
        db,
        inst,
        "FY26",
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
    score = scoring.quality_score(db, inst, spec, market_cap=D(1000))
    assert score.available >= D(6), "the reading itself is not thin — every component computed"
    assert scoring.quadrant(score, reflexivity_high=False) == "BORDERLINE"


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


def _bank_year(db, bank, period, **overrides):
    figures = dict(
        interest_earned=D(300000),
        interest_expended=D(170000),
        revenue=D(360000),
        operating_profit=D(110000),
        pbt=D(86000),
        pat=D(67000),
        share_capital=D(765),
        other_equity=D(400000),
    )
    figures.update(overrides)
    return _file(db, bank, period, **figures)


def test_a_bank_is_not_failed_on_arithmetic_about_things_it_does_not_have(db, company, spec):
    """⚠ Without this the portfolio's anchor holding classes as a value trap and the gates
    block adding to it for ever. Borrowings are a bank's raw material, not its leverage."""
    bank = company(symbol="SCOREBANK", sector="PRIVATE_BANK")
    for period in ("FY26", "FY25"):
        _bank_year(db, bank, period)

    score = scoring.quality_score(db, bank, spec)
    for name in ("roce", "cash_conversion", "balance_sheet"):
        part = _part(score, name)
        assert part.points is None, f"{name} must be unmeasured for a bank, not zero"
        assert "bank" in part.detail.lower()
    assert _part(score, "roe").points is not None, "return on equity DOES describe a bank"


def test_what_cannot_apply_to_a_bank_is_not_a_hole_in_the_reading(db, company, spec):
    """⚠ The defect that made the largest holding in the book permanently unjudgeable. Three
    tests that could never apply to a lender were counted as three gaps, and it was the gap
    count that withheld the verdict — so a complete reading and an absent one looked alike."""
    bank = company(symbol="SCOREBANK2", sector="PRIVATE_BANK")
    for period in ("FY26", "FY25"):
        _bank_year(db, bank, period)

    score = scoring.quality_score(db, bank, spec)
    assert set(score.not_applicable) == {"roce", "cash_conversion", "balance_sheet"}
    for name in score.not_applicable:
        assert name not in score.unknown, f"{name} does not apply; it is not missing"
    assert score.possible == D(10), (
        "a bank's ten points are not an industrial's ten — same denominator, different "
        "components — so depth must be measured against the set that applies"
    )
    assert {p.name for p in score.parts if p.applicable} == {
        "roe",
        "retained_earnings",
        "margin_of_safety",
        "cost_to_income",
        "credit_cost",
        "funding_spread",
    }


def test_a_bank_is_measured_on_what_a_bank_actually_does(db, company, spec):
    """The three tests that replace the three that do not apply. All three come out of tags
    the exchange already publishes — no new provider, no scraping, no estimate."""
    bank = company(symbol="SCOREBANK3", sector="PRIVATE_BANK")
    for period in ("FY26", "FY25"):
        _bank_year(db, bank, period)

    score = scoring.quality_score(db, bank, spec, market_cap=D(1200000))

    # (360000 − 170000 − 110000) ÷ (360000 − 170000) = 42%, under the 45% bar.
    assert _part(score, "cost_to_income").points == D(2)
    # (110000 − 86000) ÷ 110000 = 22%, under the 25% bar.
    assert _part(score, "credit_cost").points == D(2)
    # (300000 − 170000) ÷ 300000 = 43%, over the 40% bar.
    assert _part(score, "funding_spread").points == D(1)
    assert "low-cost deposits" in _part(score, "funding_spread").detail, (
        "it is a stand-in for the deposit mix and must never be called the net interest margin"
    )

    assert scoring.quadrant(score, reflexivity_high=False) != "UNKNOWN", (
        "a fully-read bank must reach a verdict, which is the whole point of the repair"
    )


def test_a_bank_that_lends_badly_is_scored_badly_rather_than_excused(db, company, spec):
    """The counterpart. Making a bank judgeable is only useful if the judgement can be bad."""
    bank = company(symbol="SCOREBANK4", sector="PRIVATE_BANK")
    for period in ("FY26", "FY25"):
        # Provisions eat four fifths of pre-provision profit, and costs run away.
        _bank_year(db, bank, period, operating_profit=D(50000), pbt=D(10000))

    score = scoring.quality_score(db, bank, spec)
    assert _part(score, "credit_cost").points == D(0), "80% of profit to provisions is not fine"
    assert _part(score, "cost_to_income").points == D(0), "costs at 74% of net income are not"


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
    assert score.coverage < scoring.MIN_COVERAGE_FOR_VERDICT, (
        "depth is a share of what this company's own test offers, not a count of points"
    )
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


# --- a company cannot be asked for a history it could not have -------------------------------


def _listed(db, symbol, on):
    from app.db.models import ListedCompany

    db.add(
        ListedCompany(
            symbol=symbol,
            exchange="NSE",
            name=f"{symbol} Industries",
            series="EQ",
            isin=None,
            listed_on=on,
            refreshed_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()


def test_full_years_counts_only_years_that_began_after_listing(db):
    """A December listing has a March filing covering eight private months and three public
    ones. The filing exists; the year as a public company does not."""
    assert scoring._full_years_since(dt.date(2024, 12, 11), dt.date(2026, 9, 24)) == 1
    assert scoring._full_years_since(dt.date(2022, 11, 22), dt.date(2026, 9, 24)) == 3
    assert scoring._full_years_since(dt.date(2010, 1, 1), dt.date(2026, 9, 24)) == 16


def test_a_thin_reading_says_whether_the_company_or_the_exchange_is_the_limit(db, company, spec):
    """⚠ Two different facts produce the same thin reading, and a reader shown only '1 year
    read' cannot tell them apart. One resolves with time and nothing can hurry it; the other
    may resolve with a fetch."""
    young = company(symbol="YOUNGCO")
    _listed(db, "YOUNGCO", dt.date(2024, 12, 11))
    _file(db, young, "FY26", pat=D(300), equity=D(1000))

    old = company(symbol="OLDCO")
    _listed(db, "OLDCO", dt.date(2010, 1, 1))
    _file(db, old, "FY26", pat=D(300), equity=D(1000))

    young_history = scoring.quality_score(db, young, spec).history
    assert young_history.limit == "AGE"
    assert "listed too recently" in young_history.why()
    assert "everything it could have filed has been read" in young_history.why()

    old_history = scoring.quality_score(db, old, spec).history
    assert old_history.limit == "SOURCE"
    assert "do not reach further back" in old_history.why()


def test_a_company_with_no_listing_date_is_not_assumed_to_be_old(db, company, spec):
    """Funds, coins and BSE-only companies are absent from the exchange's equity list. Absent
    is reported as absent, never as 'listed long ago'."""
    inst = company(symbol="NOLISTING")
    _file(db, inst, "FY26", pat=D(300), equity=D(1000))
    history = scoring.quality_score(db, inst, spec).history
    assert history.years_listed is None
    assert history.obtainable == scoring.HISTORY_YEARS
