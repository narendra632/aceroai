"""The six criteria for real money.

⚠ **They were written down in advance so they cannot be softened later.** That is the whole
point of the module: committing to a standard before you know whether you will meet it is the
only version of the commitment worth anything, because afterwards every failed criterion has a
reason, and every reason is persuasive to the person who needs it to be.

The tests below are mostly about the three ways this dashboard could quietly become
encouraging: confusing *not yet tested* with *passed*, letting a good-looking year read as
evidence, and giving partial credit on the one criterion that has no sample-size defence.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import (
    Claim,
    InvalidationTrigger,
    Portfolio,
    PriceObservation,
    Proposal,
    Transaction,
)
from app.services.investments import books, framework_data, frameworks, verdict
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def version(db):
    row = frameworks.install(db, framework_data.spec(), approved=True)
    db.commit()
    return row


@pytest.fixture
def book(db, user):
    row = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(row)
    db.flush()
    books.ensure(db, user.id, "MIRROR")
    db.commit()
    return row


@pytest.fixture
def company(db):
    inst = make_instrument(
        db,
        symbol="VERDCO",
        exchange="NSE",
        name="Verdco Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(inst)
    db.flush()
    db.add(
        PriceObservation(
            instrument_id=inst.id,
            observed_at=dt.datetime.now(dt.UTC),
            source=TEST_SOURCE,
            kind="LAST",
            price=D(400),
            currency="INR",
        )
    )
    db.commit()
    return inst


def _proposal(db, user, company, version, confidence="0.8"):
    mirror = books.get(db, user.id, "MIRROR")
    row = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=mirror.id,
        instrument_id=company.id,
        action="INITIATE",
        target_amount_inr=D(8000),
        horizon_days=270,
        thesis="a thesis",
        confidence=D(confidence),
        framework_version_id=version.id,
        price_snapshot={"price": "400"},
        input_refs={},
        gate_results={},
        status="PENDING",
    )
    db.add(row)
    db.commit()
    return row


def _of(result, key):
    return next(c for c in result.criteria if c.key == key)


# --- the shape of the answer -------------------------------------------------------------------


def test_all_six_are_reported(db, user):
    result = verdict.assess(db, user.id)

    assert len(result.criteria) == 6
    assert {c.key for c in result.criteria} == {
        "operating",
        "decisions",
        "calibration",
        "claims",
        "discipline",
        "return",
    }


def test_not_yet_tested_is_not_the_same_as_failed(db, user):
    """⚠ The single most important distinction on this page. A criterion with no sample behind
    it has not been failed; it has not been tested — and an interface that rendered those the
    same way would turn "we do not know" into "we fell short"."""
    result = verdict.assess(db, user.id)

    assert _of(result, "claims").met is None
    assert _of(result, "calibration").met is None
    assert result.untested > 0
    assert not result.all_met


def test_an_empty_dashboard_does_not_read_as_encouraging(db, user):
    """⚠ The honest summary early on is that almost nothing has been tested. A headline that
    led with the one criterion already met would report progress where there is only time
    passing."""
    result = verdict.assess(db, user.id)

    assert "cannot be judged yet" in result.headline or "not met" in result.headline
    assert "on track" not in result.headline.lower()
    assert "good" not in result.headline.lower()


def test_every_criterion_states_its_target(db, user):
    """A value without the bar it is being held to is not a criterion, it is a statistic."""
    for c in verdict.assess(db, user.id).criteria:
        assert c.target
        assert c.question.endswith("?")
        assert c.detail


# --- counting the decisions --------------------------------------------------------------------


def test_decisions_are_counted_and_the_smallness_is_said_out_loud(db, user, book, company, version):
    """⚠ Forty is itself a small sample, and the criterion says so even when met. The serious
    literature wants two hundred to five hundred."""
    from app.services.investments import proposals as prop_service

    row = _proposal(db, user, company, version)
    prop_service.decide(db, row, user_id=user.id, outcome="REJECT", reason="no")
    db.commit()

    criterion = _of(verdict.assess(db, user.id), "decisions")

    assert criterion.n == 1
    assert criterion.met is False
    assert "small sample" in criterion.detail


def test_another_users_decisions_are_not_counted(db, user, other_user, book, company, version):
    from app.services.investments import proposals as prop_service

    other_real = Portfolio(id=uuid.uuid4(), user_id=other_user.id, name="theirs", kind="REAL")
    db.add(other_real)
    books.ensure(db, other_user.id, "MIRROR")
    db.commit()

    row = _proposal(db, user, company, version)
    prop_service.decide(db, row, user_id=user.id, outcome="APPROVE", reason="yes")
    db.commit()

    assert _of(verdict.assess(db, other_user.id), "decisions").n == 0


# --- the one with no defence -------------------------------------------------------------------


def test_trigger_discipline_gives_no_partial_credit(db, user, book, company, version):
    """⚠ The only criterion with no sample-size defence. A system that rationalised past its
    own invalidation conditions even once does not get real money whatever the returns say —
    so anything below 1.00 is a failure, not a "nearly"."""
    proposal = _proposal(db, user, company, version)
    for threshold in (D(500), D(600)):
        db.add(
            InvalidationTrigger(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                instrument_id=company.id,
                description=f"the price falls below {threshold}",
                metric_key="price",
                comparator="LT",
                threshold=threshold,
                unit="inr",
                window_until=TODAY + dt.timedelta(days=60),
                status="FIRED",
                fired_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=30),
            )
        )
    db.commit()

    criterion = _of(verdict.assess(db, user.id), "discipline")

    assert criterion.met is not True
    assert criterion.target == "1.00, exactly"
    assert "not statistical" in criterion.detail.lower()


def test_nothing_fired_is_untested_rather_than_perfect(db, user, book):
    """⚠ A discipline score of 1.00 over zero firings is not a pass; it is an absence of
    evidence, and recording it as a pass would let the hardest criterion be met by inaction."""
    criterion = _of(verdict.assess(db, user.id), "discipline")

    assert criterion.met is None
    assert criterion.n == 0


# --- the number that must carry its error bar --------------------------------------------------


def test_the_return_criterion_carries_its_standard_error(db, user, book, company, monkeypatch):
    """⚠ Over twelve monthly observations the spread on a return-quality estimate is about
    0.35, which means a genuinely good strategy and a mediocre one look the same. Without that
    printed, a good year reads as evidence."""
    from app.services.investments import benchmarks

    monkeypatch.setattr(
        benchmarks,
        "compare",
        lambda db_, uid, *, start, end=None: benchmarks.Comparison(
            start=start,
            end=end or TODAY,
            portfolio_pct=D("0.30"),
            lines=[],
            weights={"IN": D(1), "US": D(0)},
            blended_pct=D("0.10"),
            readable=True,
            detail="",
        ),
    )

    criterion = _of(verdict.assess(db, user.id), "return")

    assert criterion.met is True
    assert criterion.standard_error == D("0.35")
    assert "look the same" in criterion.detail


def test_the_return_criterion_is_last(db, user):
    """⚠ Deliberately last and least informative. Putting it first would invite reading the
    dashboard as a scoreboard."""
    assert verdict.assess(db, user.id).criteria[-1].key == "return"


def test_a_book_that_cannot_be_valued_says_so_rather_than_failing(db, user, book):
    criterion = _of(verdict.assess(db, user.id), "return")

    assert criterion.met is None
    assert criterion.value == "not yet"


def test_the_caveat_from_the_comparison_travels_into_the_criterion(db, user, book, monkeypatch):
    """A comparison whose two sides measure different things must not become a clean verdict."""
    from app.services.investments import benchmarks

    monkeypatch.setattr(
        benchmarks,
        "compare",
        lambda db_, uid, *, start, end=None: benchmarks.Comparison(
            start=start,
            end=end or TODAY,
            portfolio_pct=D("0.30"),
            lines=[],
            weights={"IN": D(1), "US": D(0)},
            blended_pct=D("0.10"),
            readable=True,
            detail="",
            non_equity_share=D("0.4"),
            caveat="40% of the book is crypto or funds",
        ),
    )

    assert "crypto or funds" in _of(verdict.assess(db, user.id), "return").detail


# --- how long, and through what ----------------------------------------------------------------


def test_running_time_is_measured_from_the_first_transaction(db, user, book, company):
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=company.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=400),
            quantity=D(10),
            price=D(100),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()

    criterion = _of(verdict.assess(db, user.id), "operating")

    assert criterion.n >= 13
    assert "market condition" in criterion.value


def test_a_long_run_through_one_market_does_not_pass(db, user, book, company, monkeypatch):
    """⚠ A year that was entirely one long rise proves nothing, which is the whole reason the
    second half of this criterion exists."""
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=company.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=500),
            quantity=D(10),
            price=D(100),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()
    monkeypatch.setattr(verdict, "_regimes", lambda db_, start, today: 1)

    assert _of(verdict.assess(db, user.id), "operating").met is False


def test_market_conditions_are_read_from_the_benchmark_not_the_book(db, user, book):
    """⚠ A portfolio that defined the conditions it is judged in could always claim to have
    seen enough of them."""
    import inspect

    source = inspect.getsource(verdict._regimes)
    assert "benchmarks.series" in source
    assert "NIFTY50_TRI" in source


# --- the thresholds themselves -----------------------------------------------------------------


def test_the_thresholds_match_what_was_committed_to(db):
    """⚠ Constants, not settings. A threshold editable from the interface is one that will be
    edited in the month it is nearly met."""
    assert verdict.MIN_MONTHS == 12
    assert verdict.MIN_REGIMES == 2
    assert verdict.MIN_DECISIONS == 40
    assert verdict.MAX_BRIER == D("0.20")
    assert verdict.MIN_CLAIM_ACCURACY == D("0.60")
    assert verdict.MIN_RESOLVED_CLAIMS == 150
    assert verdict.REQUIRED_TRIGGER_DISCIPLINE == D(1)


def test_a_clean_sweep_still_counsels_caution(db, user, monkeypatch):
    """⚠ Even on six out of six the sane action is a small sleeve run in parallel for another
    year, and the headline says so rather than declaring victory."""
    monkeypatch.setattr(
        verdict,
        "assess",
        lambda *a, **k: verdict.Verdict(
            criteria=[
                verdict.Criterion(
                    key=k_, question="q?", met=True, value="v", target="t", detail="d"
                )
                for k_ in (
                    "operating",
                    "decisions",
                    "calibration",
                    "claims",
                    "discipline",
                    "return",
                )
            ]
        ),
    )

    result = verdict.assess(db, user.id)

    assert result.all_met
    assert "small sleeve" in result.headline
    assert "parallel" in result.headline


# --- over the wire -----------------------------------------------------------------------------


def test_the_verdict_route_reports_all_six(auth_client, db, user):
    body = auth_client.get("/api/investments/verdict").json()

    assert len(body["criteria"]) == 6
    assert body["all_met"] is False
    assert body["headline"]
    # ⚠ null, not false. "Not yet testable" and "failed" must not render the same way.
    assert any(c["met"] is None for c in body["criteria"])


def test_a_quarterly_review_carries_the_verdict_and_a_weekly_does_not(db, user, book):
    """⚠ Quarterly only. The six move on a scale of months, and putting them in the weekly
    would invite watching them the way one watches a price."""
    from app.services.investments import reviews

    weekly, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")
    quarterly, _, _, _ = reviews.assemble(db, user.id, "QUARTERLY")

    assert "verdict" not in weekly
    assert len(quarterly["verdict"]["criteria"]) == 6


def test_a_resolved_claim_moves_the_claims_criterion(db, user, book, company, version):
    proposal = _proposal(db, user, company, version)
    db.add(
        Claim(
            id=uuid.uuid4(),
            proposal_id=proposal.id,
            claim_text="revenue grows",
            metric_key="revenue",
            comparator="GT",
            threshold=D(100),
            due_by=TODAY - dt.timedelta(days=1),
            status="TRUE",
        )
    )
    db.commit()

    criterion = _of(verdict.assess(db, user.id), "claims")

    assert criterion.n == 1
    assert "1 resolved so far" in criterion.detail
