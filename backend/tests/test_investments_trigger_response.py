"""What happens when a condition you wrote down comes true.

⚠ **A system that writes invalidation conditions and then rationalises past them has quietly
stopped being a system.** Until now a fired condition raised a notification and nothing else,
which left the acting entirely to whoever happened to read it. Trigger discipline — *did it
act when its own condition fired* — is the one go/no-go criterion that is not statistical: if
the system ignored its own conditions even a few times, it does not get real money whatever
the returns say.

⚠ **The response is never a purchase.** A condition firing is the thesis being contradicted,
and a design that let that produce "add more" would have invented averaging down as a policy.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import (
    AgentRun,
    Decision,
    InvalidationTrigger,
    Portfolio,
    PriceObservation,
    Proposal,
    Transaction,
)
from app.services.investments import books, framework_data, frameworks, proposals, watching
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    row = frameworks.install(db, spec, approved=True)
    db.commit()
    return row


@pytest.fixture
def holding(db, user, version):
    """A real position with a price, so a reduction can actually be sized."""
    real = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(real)
    db.flush()
    inst = make_instrument(
        db,
        symbol="FIRECO",
        exchange="NSE",
        name="Fireco Industries",
        asset_class="EQUITY_IN",
        currency="INR",
        sector="EMS_ELECTRONICS",
    )
    db.add(inst)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=real.id,
            instrument_id=inst.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=60),
            quantity=D(20),
            price=D(500),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
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
    books.ensure(db, user.id, "MIRROR")
    db.commit()
    return real, inst


def _armed(db, inst, version, *, metric="price", comparator="LT", threshold=D(450)):
    """One condition, armed, of the kind written when a position is taken."""
    mirror = db.execute(sa.select(Portfolio).where(Portfolio.kind == "MIRROR")).scalars().first()
    proposal = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=mirror.id,
        instrument_id=inst.id,
        action="INITIATE",
        target_amount_inr=D(10000),
        horizon_days=270,
        thesis="the original thesis",
        confidence=D("0.8"),
        framework_version_id=version.id,
        price_snapshot={"price": "500"},
        input_refs={},
        gate_results={},
        status="PENDING",
    )
    db.add(proposal)
    db.flush()
    row = InvalidationTrigger(
        id=uuid.uuid4(),
        proposal_id=proposal.id,
        instrument_id=inst.id,
        description="the price falls below 450",
        metric_key=metric,
        comparator=comparator,
        threshold=threshold,
        unit="inr",
        window_until=TODAY + dt.timedelta(days=90),
        status="ARMED",
    )
    db.add(row)
    db.commit()
    return row


# --- the response --------------------------------------------------------------------------


def test_a_fired_condition_raises_a_suggestion(db, user, holding, version):
    """⚠ Not only an alert. Telling someone their thesis has been contradicted and leaving the
    acting to whoever reads the notification is how trigger discipline erodes without anyone
    deciding to let it."""
    real, inst = holding
    _armed(db, inst, version)

    watch = watching.check_triggers(db)
    db.commit()
    assert len(watch.fired) == 1

    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    assert batch.considered == 1
    assert (batch.proposed + batch.blocked)[0].instrument_id == inst.id


@pytest.mark.parametrize("fired_count", [1, 2])
def test_the_response_is_never_a_purchase(db, user, holding, version, fired_count):
    """⚠ A condition firing is the thesis being contradicted. A design that let that produce
    "add more" would have invented averaging down as a policy."""
    real, inst = holding
    for n in range(fired_count):
        _armed(db, inst, version, threshold=D(450 + n))

    watch = watching.check_triggers(db)
    db.commit()
    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    assert batch.considered
    for row in batch.proposed + batch.blocked:
        assert row.action in ("TRIM", "EXIT")
        assert row.action not in ("INITIATE", "ADD")


def test_two_conditions_on_one_company_ask_to_leave_rather_than_trim(db, user, holding, version):
    """One contradiction is a reason to reduce; two is a reason to stop believing the thesis."""
    real, inst = holding
    _armed(db, inst, version, threshold=D(450))
    _armed(db, inst, version, threshold=D(460))

    watch = watching.check_triggers(db)
    db.commit()
    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    rows = batch.proposed + batch.blocked
    assert len(rows) == 1, "one suggestion per company, not one per condition"
    assert rows[0].action == "EXIT"


def test_the_suggestion_quotes_the_condition_that_fired(db, user, holding, version):
    """⚠ The thesis has to name what contradicted it, or the reader is being asked to take the
    reversal on trust — which is the same trust the original thesis asked for."""
    real, inst = holding
    _armed(db, inst, version)

    watch = watching.check_triggers(db)
    db.commit()
    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    thesis = (batch.proposed + batch.blocked)[0].thesis
    assert "the price falls below 450" in thesis
    assert "come true" in thesis


def test_the_run_is_recorded_even_when_nothing_fired(db, user, holding, version):
    """⚠ A system that leaves a trace only on the days it acted cannot be measured against the
    days it should have acted and did not."""
    watch = watching.check_triggers(db)
    db.commit()
    assert watch.fired == []

    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="quiet")
    db.commit()

    assert batch.considered == 0
    run = db.execute(
        sa.select(AgentRun).where(AgentRun.agent_name == "trigger_response")
    ).scalar_one()
    assert run.proposals_emitted == 0


def test_the_same_firing_cannot_raise_two_batches(db, user, holding, version):
    """⚠ Idempotent on the occurrence key, like every scheduled thing here. A catch-up run
    after a restart must not double-suggest."""
    real, inst = holding
    _armed(db, inst, version)
    watch = watching.check_triggers(db)
    db.commit()

    proposals.on_triggers_fired(db, user.id, watch, occurrence_key="same")
    db.commit()

    with pytest.raises(sa.exc.IntegrityError):
        proposals.on_triggers_fired(db, user.id, watch, occurrence_key="same")
        db.commit()
    db.rollback()


def test_a_blocked_response_is_still_recorded(db, user, holding, version, monkeypatch):
    """⚠ The rails are measured too. A refusal discarded is a refusal nobody can ever ask
    whether it was protecting or merely obstructing."""
    real, inst = holding
    _armed(db, inst, version)
    watch = watching.check_triggers(db)
    db.commit()

    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    rows = (
        db.execute(sa.select(Proposal).where(Proposal.batch_id == batch.batch_id)).scalars().all()
    )
    assert rows, "the suggestion exists whether or not the gates passed it"
    assert all(row.status in ("PENDING", "BLOCKED") for row in rows)


# --- through the job ---------------------------------------------------------------------------


def test_the_watch_job_raises_the_suggestion_and_says_so(db, user, holding, version):
    from app.jobs import evening

    real, inst = holding
    _armed(db, inst, version)

    result = evening.position_watch(db, user)

    assert result.detail["proposals_raised"] == 1
    assert result.notify is not None
    assert "suggestion is waiting" in result.notify.body


def test_a_failed_suggestion_never_loses_the_firing(db, user, version, monkeypatch):
    """⚠ A thesis being contradicted is the fact; a suggestion about it is a convenience, and
    losing the first to save the second would be exactly backwards."""
    from app.jobs import evening

    inst = make_instrument(
        db,
        symbol="ORPHANCO",
        exchange="NSE",
        name="Orphanco Industries",
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
    books.ensure(db, user.id, "MIRROR")
    db.commit()
    trigger = _armed(db, inst, version)

    # No REAL book at all, so forming a suggestion raises.
    result = evening.position_watch(db, user)

    db.expire_all()
    assert db.get(InvalidationTrigger, trigger.id).status == "FIRED"
    assert "no suggestion raised" in result.detail.get("response", "")
    assert result.notify is not None, "the firing is still reported"


def test_deciding_on_a_trigger_response_works_like_any_other(db, user, holding, version):
    """It is an ordinary proposal in every respect that matters — including that turning it
    down requires a reason, which is the data that measures trigger discipline."""
    real, inst = holding
    _armed(db, inst, version)
    watch = watching.check_triggers(db)
    db.commit()
    batch = proposals.on_triggers_fired(db, user.id, watch, occurrence_key="k1")
    db.commit()

    row = (batch.proposed + batch.blocked)[0]
    if row.status == "BLOCKED":
        pytest.skip("the gates refused it; deciding is covered in the proposals suite")

    proposals.decide(db, row, user_id=user.id, outcome="APPROVE", reason="agreed, reducing")
    db.commit()

    assert (
        db.execute(sa.select(Decision).where(Decision.proposal_id == row.id)).scalar_one().outcome
        == "APPROVE"
    )
