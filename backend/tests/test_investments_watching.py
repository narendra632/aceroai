"""Checking a thesis: what fires, what settles, and what refuses to produce a number.

Three refusals carry most of the weight here, and each of them is the difference between a
measurement and a comforting figure:

  * a condition that **cannot** be evaluated is not a condition that passed,
  * a claim that cannot be checked is **unverifiable**, never false,
  * a measure over too few observations reports **nothing at all**.

The third matters most. A precision computed over six outcomes reads exactly like one computed
over six hundred, and nothing in the interface could tell the reader which they were seeing.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import (
    Claim,
    Decision,
    Fundamental,
    InvalidationTrigger,
    Portfolio,
    PriceObservation,
    Proposal,
    SourceItem,
)
from app.services.investments import watching
from app.services.marketdata import nse_xbrl
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def book(db, user):
    row = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-watch", kind="MIRROR")
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def version(db):
    from app.services.investments import framework_data, frameworks

    row = frameworks.install(db, framework_data.spec(), approved=True)
    db.commit()
    return row


def _company(db, symbol="WATCHCO"):
    inst = make_instrument(
        db,
        symbol=symbol,
        exchange="NSE",
        name=f"{symbol} Industries",
        asset_class="EQUITY_IN",
        currency="INR",
        sector="EMS_ELECTRONICS",
    )
    db.add(inst)
    db.flush()
    return inst


def _accounts(db, inst, period="FY26", **metrics):
    end = dt.date(int(period[2:4]) + 2000, 3, 31)
    source = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=inst.id,
        source=nse_xbrl.PROVIDER,
        external_id=f"{inst.symbol}-{period}-{uuid.uuid4().hex[:8]}",
        url="https://x/f.xml",
        title=f"{inst.symbol} {period}",
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
                instrument_id=inst.id,
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


def _proposal(db, book, version, inst, *, confidence="0.8") -> Proposal:
    row = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=book.id,
        instrument_id=inst.id,
        action="INITIATE",
        horizon_days=270,
        thesis="a thesis",
        confidence=D(confidence),
        framework_version_id=version.id,
        price_snapshot={"price": "100"},
        input_refs={},
        gate_results={},
        status="PENDING",
    )
    db.add(row)
    db.flush()
    return row


def _trigger(db, proposal, inst, *, metric="price", comparator="LT", threshold="75", days=30):
    row = InvalidationTrigger(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        instrument_id=inst.id,
        metric_key=metric,
        comparator=comparator,
        threshold=D(threshold),
        unit="inr",
        window_until=TODAY + dt.timedelta(days=days),
        description=f"{metric} falls below {threshold}",
        status="ARMED",
    )
    db.add(row)
    db.commit()
    return row


def _claim(db, proposal, *, metric="roce", comparator="GTE", threshold="15", due_days=-1):
    row = Claim(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        claim_text=f"{metric} stays at or above {threshold}",
        metric_key=metric,
        comparator=comparator,
        threshold=D(threshold),
        due_by=TODAY + dt.timedelta(days=due_days),
        status="OPEN",
    )
    db.add(row)
    db.commit()
    return row


def _price(db, inst, value, days_ago=0):
    db.add(
        PriceObservation(
            instrument_id=inst.id,
            observed_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
            source=TEST_SOURCE,
            kind="LAST",
            price=D(str(value)),
            currency="INR",
        )
    )
    db.commit()


# --- conditions that fire ------------------------------------------------------------------


def test_a_condition_that_comes_true_fires_with_its_evidence(db, book, version):
    inst = _company(db)
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, threshold="75")
    _price(db, inst, 60)

    watch = watching.check_triggers(db)
    db.commit()

    assert len(watch.fired) == 1
    db.refresh(trigger)
    assert trigger.status == "FIRED"
    assert trigger.fired_at is not None
    assert trigger.fired_evidence["value"] == "60.000000"


def test_a_condition_that_has_not_come_true_stays_armed(db, book, version):
    inst = _company(db, symbol="WATCHOK")
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, threshold="75")
    _price(db, inst, 120)

    watching.check_triggers(db)
    db.commit()
    db.refresh(trigger)
    assert trigger.status == "ARMED"


def test_a_condition_nothing_can_evaluate_is_not_treated_as_passed(db, book, version):
    """⚠ An unevaluable condition is unevaluated. Counting it as satisfied would report a
    clean bill of health that nothing ever checked."""
    inst = _company(db, symbol="WATCHBLIND")
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, metric="roce", threshold="12")

    watch = watching.check_triggers(db)
    db.commit()

    assert watch.unevaluable == 1
    assert watch.fired == []
    db.refresh(trigger)
    assert trigger.status == "ARMED", "still watched, not quietly satisfied"


def test_a_condition_past_its_window_expires_rather_than_lingering(db, book, version):
    """⚠ Left armed for ever it would fire years later on an unrelated movement and be read as
    the original thesis failing — a worse error than losing the condition."""
    inst = _company(db, symbol="WATCHOLD")
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, threshold="10", days=-1)
    _price(db, inst, 120)

    watch = watching.check_triggers(db)
    db.commit()

    assert watch.expired == 1
    db.refresh(trigger)
    assert trigger.status == "EXPIRED"


def test_a_condition_on_a_filed_figure_fires_from_the_accounts(db, book, version):
    inst = _company(db, symbol="WATCHROCE")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(50),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, metric="roce", comparator="LT", threshold="12")

    watching.check_triggers(db)
    db.commit()
    db.refresh(trigger)
    assert trigger.status == "FIRED", "5% return on capital is below the 12% floor"


# --- claims that settle -----------------------------------------------------------------------


def test_a_claim_that_held_resolves_true(db, book, version):
    inst = _company(db, symbol="WATCHTRUE")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(200),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")

    report = watching.resolve_claims(db)
    db.commit()

    assert report.true == 1
    db.refresh(claim)
    assert claim.status == "TRUE"
    assert claim.resolved_evidence["value"].startswith("20")


def test_a_claim_that_failed_resolves_false(db, book, version):
    inst = _company(db, symbol="WATCHFALSE")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(50),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")

    report = watching.resolve_claims(db)
    db.commit()

    assert report.false == 1
    db.refresh(claim)
    assert claim.status == "FALSE"


def test_a_claim_nothing_can_check_is_unverifiable_and_never_false(db, book, version):
    """⚠ Counting an unmeasurable claim against the system makes its accuracy a measure of
    data coverage rather than of judgement, and the two become impossible to tell apart."""
    inst = _company(db, symbol="WATCHUNK")
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")

    report = watching.resolve_claims(db)
    db.commit()

    assert report.unverifiable == 1 and report.false == 0
    db.refresh(claim)
    assert claim.status == "UNVERIFIABLE"


def test_a_claim_not_yet_due_is_left_alone(db, book, version):
    inst = _company(db, symbol="WATCHSOON")
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal, due_days=30)

    watching.resolve_claims(db)
    db.commit()
    db.refresh(claim)
    assert claim.status == "OPEN"


# --- measures that refuse to be computed on too little -------------------------------------------


def test_claim_accuracy_refuses_a_figure_on_a_handful(db, book, version):
    """⚠ A precision over six outcomes reads exactly like one over six hundred."""
    inst = _company(db, symbol="WATCHFEW")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(200),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    for _ in range(3):
        proposal = _proposal(db, book, version, inst)
        _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")
    watching.resolve_claims(db)
    db.commit()

    measure = watching.claim_accuracy(db)
    assert measure.value is None
    assert measure.n == 3
    assert "needed before this means anything" in measure.detail


def test_claim_accuracy_reports_once_there_is_enough(db, book, version):
    inst = _company(db, symbol="WATCHMANY")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(200),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    for _ in range(watching.MIN_OBSERVATIONS + 2):
        proposal = _proposal(db, book, version, inst)
        _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")
    watching.resolve_claims(db)
    db.commit()

    measure = watching.claim_accuracy(db)
    assert measure.value == D(1), "every claim held"
    assert measure.n >= watching.MIN_OBSERVATIONS


def test_calibration_refuses_a_curve_on_too_few_theses(db, book, version):
    inst = _company(db, symbol="WATCHCAL")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(200),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    proposal = _proposal(db, book, version, inst, confidence="0.9")
    _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")
    watching.resolve_claims(db)
    db.commit()

    measure = watching.calibration(db)
    assert measure.value is None
    assert "says more about the sample" in measure.detail


def test_calibration_punishes_confidence_that_did_not_pay_off(db, book, version):
    """⚠ Overconfidence is the most common and most correctable failure of a system like this,
    and this is where it shows up first."""
    inst = _company(db, symbol="WATCHOVER")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(50),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    for _ in range(watching.MIN_OBSERVATIONS + 1):
        proposal = _proposal(db, book, version, inst, confidence="0.95")
        _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")
    watching.resolve_claims(db)
    db.commit()

    measure = watching.calibration(db)
    assert measure.value is not None
    assert measure.value > D("0.8"), "95% confident and wrong every time scores terribly"
    assert "lower is better" in measure.detail


def test_trigger_discipline_says_nothing_until_a_condition_has_fired(db):
    measure = watching.trigger_discipline(db)
    assert measure.value is None and measure.n == 0


def test_an_ignored_firing_is_visible_rather_than_averaged_away(db, book, version):
    """⚠ The one measure here that is NOT statistical. A single ignored firing is a finding,
    so it reports from the first one rather than waiting for a sample."""
    inst = _company(db, symbol="WATCHIGNORE")
    proposal = _proposal(db, book, version, inst)
    trigger = _trigger(db, proposal, inst, threshold="75")
    _price(db, inst, 60)
    watching.check_triggers(db)
    trigger.fired_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=watching.RESPONSE_DAYS + 1)
    db.commit()

    measure = watching.trigger_discipline(db)
    assert measure.n == 1
    assert measure.value == D(0), "nothing was proposed in response"
    assert "below all of them is a problem" in measure.detail


def test_the_decision_record_is_described_rather_than_scored(db, book, version):
    """⚠ Not framed as accuracy. A high agreement rate could equally mean the system is good
    or that it has learned to suggest only what will be accepted."""
    inst = _company(db, symbol="WATCHDEC")
    for outcome in ("APPROVE", "REJECT"):
        proposal = _proposal(db, book, version, inst)
        db.add(
            Decision(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                decided_at=dt.datetime.now(dt.UTC),
                outcome=outcome,
                reason_text="because",
                decided_via="WEB",
            )
        )
    db.commit()

    measure = watching.decision_record(db)
    assert measure.n == 2
    assert measure.value == D("0.5")


def test_every_measure_carries_its_sample_size(db):
    """A figure without its n is a figure that will be over-read."""
    for measure in watching.measures(db):
        assert isinstance(measure.n, int)
        assert measure.detail
        if measure.value is None:
            assert not measure.is_reportable


# --- the job ----------------------------------------------------------------------------------


def test_the_job_is_silent_when_nothing_has_gone_wrong(db, user, book, version):
    from app.jobs import evening

    inst = _company(db, symbol="WATCHJOBOK")
    proposal = _proposal(db, book, version, inst)
    _trigger(db, proposal, inst, threshold="10")
    _price(db, inst, 120)

    result = evening.position_watch(db, user)
    assert result.silent
    assert result.detail["fired"] == 0


def test_a_firing_always_notifies(db, user, book, version):
    """⚠ The one thing here that cannot wait for the evening. A thesis the user is holding
    money against has been contradicted, and being told is the whole reason it was written."""
    from app.jobs import evening

    inst = _company(db, symbol="WATCHJOBFIRE")
    proposal = _proposal(db, book, version, inst)
    _trigger(db, proposal, inst, threshold="75")
    _price(db, inst, 50)

    result = evening.position_watch(db, user)
    assert result.notify is not None
    assert "WATCHJOBFIRE" in result.notify.title
    assert "written down before" in result.notify.body
    assert result.detail["fired"] == 1


def test_a_settled_claim_cannot_have_its_prediction_rewritten(db, book, version):
    """⚠ The narrowed guard from migration 021. Recording an outcome is allowed; changing what
    was predicted is not — a prediction revisable once the outcome is known is worth nothing
    for judging yourself, and hindsight is not resisted by intending to."""
    from sqlalchemy.exc import DatabaseError

    inst = _company(db, symbol="WATCHFROZEN")
    _accounts(
        db,
        inst,
        "FY26",
        pbt=D(200),
        finance_costs=D(0),
        equity=D(1000),
        borrowings_current=D(0),
        borrowings_noncurrent=D(0),
    )
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal, metric="roce", comparator="GTE", threshold="15")

    watching.resolve_claims(db)
    db.commit()
    db.refresh(claim)
    assert claim.status == "TRUE", "recording the outcome is allowed"

    claim.threshold = D(5)
    with pytest.raises(DatabaseError):
        db.flush()
    db.rollback()


def test_a_prediction_cannot_be_deleted_after_the_fact(db, book, version):
    """A claim that can be removed is a claim that never has to be counted."""
    from sqlalchemy.exc import DatabaseError

    inst = _company(db, symbol="WATCHNODEL")
    proposal = _proposal(db, book, version, inst)
    claim = _claim(db, proposal)

    db.delete(claim)
    with pytest.raises(DatabaseError):
        db.flush()
    db.rollback()
