"""Proposals: what the rules refuse, and what a refusal costs.

The tests that matter here are about **rules that hold on the day you would rather they did
not**. A gate a persuasive argument can talk its way past is a preference, and the entire
reason for writing rules down before there is anything at stake is that they bind later.

So: every gate is exercised against a case it must refuse, every refusal is checked to be
recorded rather than discarded, and the append-only guarantees are checked at the database
rather than taken on trust.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import (
    AgentRun,
    Claim,
    CorporateAction,
    Decision,
    Fundamental,
    InvalidationTrigger,
    Portfolio,
    PriceObservation,
    Proposal,
    ShadowEntry,
    SourceItem,
    Transaction,
)
from app.services.errors import Invalid
from app.services.investments import frameworks, gates, proposals, scoring
from app.services.marketdata import nse_xbrl
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def spec():
    from app.services.investments import framework_data

    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    row = frameworks.install(db, spec, notes="pytest", approved=True)
    db.commit()
    return row


@pytest.fixture
def real(db, user):
    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(book)
    db.commit()
    return book


def _company(db, symbol="PROPCO", sector="EMS_ELECTRONICS"):
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


def _accounts(db, inst, period, **metrics):
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


def _priced(db, inst, price, days_ago=0):
    db.add(
        PriceObservation(
            instrument_id=inst.id,
            observed_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
            source=TEST_SOURCE,
            kind="LAST",
            price=D(str(price)),
            currency="INR",
        )
    )
    db.commit()


def _excellent(db, inst, *, price=D(100)):
    """A company good enough that only the rules can stop it."""
    for period in ("FY26", "FY25"):
        _accounts(
            db,
            inst,
            period,
            pat=D(300),
            equity=D(1000),
            pbt=D(400),
            finance_costs=D(10),
            ocf=D(320),
            dep_amort=D(20),
            cash=D(50),
            borrowings_current=D(0),
            borrowings_noncurrent=D(0),
            paid_up_capital=D(100),
            face_value=D(10),
        )
    _priced(db, inst, price)


def _agreed(db, inst, spec, version, bottleneck="B1.1"):
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck=bottleneck, spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, mapping)
    db.commit()
    return mapping


def _candidate(db, inst, spec, mapping, **over):
    quality = scoring.quality_score(db, inst, spec, market_cap=D(2000))
    base = {
        "instrument": inst,
        "action": "INITIATE",
        "mapping": mapping,
        "ab_score": frameworks.ab_score(mapping, spec),
        "quality": quality,
        "quadrant": scoring.quadrant(quality, False),
        "confidence": D("0.75"),
        "horizon_days": 270,
        "triggers": [
            {
                "metric_key": "roce",
                "comparator": "LT",
                "threshold": D(12),
                "window_until": TODAY,
            },
            {
                "metric_key": "price",
                "comparator": "LT",
                "threshold": D(75),
                "window_until": TODAY,
            },
        ],
        "target_amount_inr": D(7500),
        "off_framework": False,
    }
    base.update(over)
    return gates.Candidate(**base)


# --- the gates ----------------------------------------------------------------------------


def test_a_company_whose_place_is_not_agreed_cannot_be_bought(db, real, spec, version):
    """⚠ The guard the structural score rests on, reaching the purchase decision."""
    inst = _company(db)
    _excellent(db, inst)
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    verdict = gates.evaluate(db, real.id, _candidate(db, inst, spec, mapping))
    assert verdict.blocked_by == "G1_framework"
    assert "not agreed" in verdict.as_dict()["G1_framework"]["detail"]


def test_a_story_without_a_business_is_refused_outright(db, real, spec, version):
    """⚠ No override, by design. A gate that yields to a strong enough thesis yields exactly
    when the thesis is most persuasive, which is when it is most dangerous."""
    inst = _company(db, symbol="PROPBUBBLE")
    for period in ("FY26", "FY25"):
        _accounts(
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
    _priced(db, inst, D(100))
    mapping = _agreed(db, inst, spec, version)

    quality = scoring.quality_score(db, inst, spec, market_cap=D(90000))
    verdict = gates.evaluate(
        db,
        real.id,
        _candidate(
            db, inst, spec, mapping, quality=quality, quadrant=scoring.quadrant(quality, True)
        ),
    )
    assert verdict.blocked_by == "G2_quadrant"
    assert "story without a business" in verdict.as_dict()["G2_quadrant"]["detail"]


def test_a_reading_too_thin_to_judge_does_not_become_a_purchase(db, real, spec, version):
    inst = _company(db, symbol="PROPTHIN")
    _accounts(db, inst, "FY26", pat=D(300), equity=D(1000))
    _priced(db, inst, D(100))
    mapping = _agreed(db, inst, spec, version)

    quality = scoring.quality_score(db, inst, spec)
    verdict = gates.evaluate(
        db,
        real.id,
        _candidate(
            db, inst, spec, mapping, quality=quality, quadrant=scoring.quadrant(quality, False)
        ),
    )
    assert verdict.blocked_by == "G2_quadrant"
    assert "too little" in verdict.as_dict()["G2_quadrant"]["detail"]


def test_paying_above_a_defensible_worth_is_refused(db, real, spec, version):
    """⚠ The case the whole framework turns on: essential, excellent, and far too expensive."""
    inst = _company(db, symbol="PROPDEAR")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)

    dear = scoring.quality_score(db, inst, spec, market_cap=D(500000))
    verdict = gates.evaluate(
        db,
        real.id,
        _candidate(db, inst, spec, mapping, quality=dear, quadrant=scoring.quadrant(dear, False)),
    )
    blocked = verdict.blocked_by
    assert blocked in ("G2_quadrant", "G3_margin_of_safety")


def test_two_checkable_invalidation_conditions_are_required(db, real, spec, version):
    """⚠ 'If the story changes' cannot be checked, so a position carrying it can never be
    shown to be wrong — which is the same as carrying no condition at all."""
    inst = _company(db, symbol="PROPNOTRIG")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)

    prose = [{"description": "if the story changes"}]
    verdict = gates.evaluate(db, real.id, _candidate(db, inst, spec, mapping, triggers=prose))
    assert verdict.blocked_by == "G4_invalidation"


def test_a_name_just_turned_down_is_not_raised_again(db, real, user, spec, version):
    inst = _company(db, symbol="PROPREJECT")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)
    mirror = proposals.mirror(db, user.id)

    earlier = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=mirror.id,
        instrument_id=inst.id,
        action="INITIATE",
        horizon_days=270,
        thesis="earlier",
        confidence=D("0.7"),
        framework_version_id=version.id,
        price_snapshot={"price": "100"},
        input_refs={},
        gate_results={},
        status="PENDING",
    )
    db.add(earlier)
    db.flush()
    db.add(
        Decision(
            id=uuid.uuid4(),
            proposal_id=earlier.id,
            decided_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2),
            outcome="REJECT",
            reason_text="not now",
            decided_via="WEB",
        )
    )
    db.commit()

    verdict = gates.evaluate(db, mirror.id, _candidate(db, inst, spec, mapping))
    assert verdict.blocked_by == "G6_cooling_off"


def test_nothing_is_proposed_while_a_split_is_outstanding(db, real, spec, version):
    """⚠ Until the ledger knows, the price and the quantity count different things, so every
    figure a proposal would rest on is arithmetic over a disagreement."""
    inst = _company(db, symbol="PROPSPLIT")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)
    db.add(
        CorporateAction(
            id=uuid.uuid4(),
            instrument_id=inst.id,
            action_type="BONUS",
            ex_date=TODAY,
            ratio_num=2,
            ratio_den=1,
            announced_at=dt.datetime.now(dt.UTC),
            source="NSE",
            purpose="BONUS 1:1",
            dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
            status="PENDING",
        )
    )
    db.commit()

    verdict = gates.evaluate(db, real.id, _candidate(db, inst, spec, mapping))
    assert verdict.blocked_by == "G7_corporate_action"


def test_a_stale_price_is_not_a_basis_for_a_suggestion(db, real, spec, version):
    inst = _company(db, symbol="PROPSTALE")
    for period in ("FY26", "FY25"):
        _accounts(db, inst, period, pat=D(300), equity=D(1000), dep_amort=D(20))
    _priced(db, inst, D(100), days_ago=40)
    mapping = _agreed(db, inst, spec, version)

    verdict = gates.evaluate(db, real.id, _candidate(db, inst, spec, mapping))
    assert verdict.blocked_by in ("G2_quadrant", "G8_price_age")


def test_a_full_evening_stops_suggesting(db, real, spec, version):
    inst = _company(db, symbol="PROPCAP")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)

    verdict = gates.evaluate(
        db, real.id, _candidate(db, inst, spec, mapping, in_batch=gates.MAX_PER_BATCH)
    )
    assert verdict.blocked_by == "G9_volume"


def test_low_confidence_is_a_note_rather_than_a_suggestion(db, real, spec, version):
    inst = _company(db, symbol="PROPMEH")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)

    verdict = gates.evaluate(db, real.id, _candidate(db, inst, spec, mapping, confidence=D("0.2")))
    assert verdict.blocked_by == "G11_confidence"


def test_a_sell_is_not_asked_the_buying_questions(db, real, spec, version):
    """⚠ Not-applicable is distinct from passing. A review counting the two together would
    overstate how much was actually checked."""
    inst = _company(db, symbol="PROPSELL")
    _excellent(db, inst)
    mapping = _agreed(db, inst, spec, version)

    verdict = gates.evaluate(
        db, real.id, _candidate(db, inst, spec, mapping, action="EXIT", triggers=[])
    )
    results = verdict.as_dict()
    assert results["G4_invalidation"]["not_applicable"] is True
    assert results["G2_quadrant"]["not_applicable"] is True


def test_the_off_framework_ceiling_counts_equities_only(db, real, user, spec, version):
    """⚠ Found live: counting crypto and mutual funds — which have no mapping because the
    framework was never about them — put the off-framework share at 39.8%, eight times its
    ceiling, and blocked every equity outside the framework by a rule about something else."""
    equity = _company(db, symbol="PROPEQ")
    coin = make_instrument(
        db,
        symbol="PROPCOIN",
        exchange="CRYPTO",
        name="Testcoin",
        asset_class="CRYPTO",
        currency="INR",
    )
    db.add(coin)
    db.flush()
    for inst, qty, price in ((equity, D(10), D(100)), (coin, D(1000), D(50))):
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=real.id,
                instrument_id=inst.id,
                txn_type="BUY",
                trade_date=TODAY - dt.timedelta(days=30),
                quantity=qty,
                price=price,
                currency="INR",
                fx_rate_inr=D(1),
                entry_source="IMPORT",
            )
        )
    _agreed(db, equity, spec, version)
    db.commit()

    share = proposals._off_framework_share(db, real.id, spec)
    assert share == D(0), "the only equity is inside the framework; the coin is not counted"


# --- what happens to a refusal -----------------------------------------------------------------


def test_a_blocked_suggestion_is_still_written_and_shadowed(db, real, user, spec, version):
    """⚠ A rule whose cost is invisible is a rule nobody can evaluate. The shadow book holding
    what the rules refused is the only way to ever ask whether they protect or obstruct."""
    inst = _company(db, symbol="PROPBLOCK")
    _excellent(db, inst)
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    mirror = proposals.mirror(db, user.id)
    draft = proposals.draft_for(db, mirror, inst, spec, set())
    verdict = gates.evaluate(db, mirror.id, _candidate(db, inst, spec, mapping))
    row = proposals.write(
        db,
        book_row=mirror,
        user_id=user.id,
        draft=draft,
        verdict=verdict,
        batch_id=uuid.uuid4(),
        framework_version_id=version.id,
    )
    db.commit()

    assert row.status == "BLOCKED"
    assert row.blocked_by == "G1_framework"
    entry = db.execute(sa.select(ShadowEntry).where(ShadowEntry.proposal_id == row.id)).scalar_one()
    assert entry.reason == "GATE_BLOCKED"
    # A blocked suggestion was never offered, so it carries no conditions to watch.
    assert (
        db.execute(
            sa.select(sa.func.count())
            .select_from(InvalidationTrigger)
            .where(InvalidationTrigger.proposal_id == row.id)
        ).scalar_one()
        == 0
    )


# --- deciding ------------------------------------------------------------------------------------


@pytest.fixture
def offered(db, real, user, spec, version):
    """One suggestion that survived every rule."""
    inst = _company(db, symbol="PROPGOOD")
    _excellent(db, inst)
    _agreed(db, inst, spec, version)
    mirror = proposals.mirror(db, user.id)
    draft = proposals.draft_for(db, mirror, inst, spec, set())
    verdict = gates.Verdict([gates.GateResult("G1_framework", True, False, "fine")])
    row = proposals.write(
        db,
        book_row=mirror,
        user_id=user.id,
        draft=draft,
        verdict=verdict,
        batch_id=uuid.uuid4(),
        framework_version_id=version.id,
    )
    db.commit()
    return row


def test_a_suggestion_carries_what_would_prove_it_wrong(db, offered):
    triggers = list(
        db.execute(
            sa.select(InvalidationTrigger).where(InvalidationTrigger.proposal_id == offered.id)
        ).scalars()
    )
    assert len(triggers) >= 2
    for t in triggers:
        assert t.metric_key and t.comparator and t.threshold is not None and t.window_until
        assert t.description, "a condition a person cannot read is a condition nobody checks"


def test_a_suggestion_carries_falsifiable_claims(db, offered):
    """⚠ Where measurement becomes possible in months rather than decades."""
    claims = list(db.execute(sa.select(Claim).where(Claim.proposal_id == offered.id)).scalars())
    assert claims
    assert all(c.due_by > TODAY for c in claims)
    assert all(c.status == "OPEN" for c in claims)


def test_what_the_system_saw_is_frozen_onto_the_suggestion(db, offered):
    """A review that recomputes the inputs is reconstructing a decision, not examining one."""
    assert offered.price_snapshot.get("price")
    assert offered.gate_results
    assert offered.input_refs.get("years_read") is not None
    assert offered.framework_version_id is not None


def test_a_decision_needs_a_reason(db, offered, user):
    with pytest.raises(Invalid):
        proposals.decide(db, offered, user_id=user.id, outcome="APPROVE", reason="   ")


def test_approving_is_recorded_and_cannot_be_repeated(db, offered, user):
    proposals.decide(db, offered, user_id=user.id, outcome="APPROVE", reason="agreed, transmission")
    db.commit()
    assert proposals.effective_status(db, offered) == "APPROVED"
    with pytest.raises(Invalid):
        proposals.decide(db, offered, user_id=user.id, outcome="REJECT", reason="changed mind")


def test_rejecting_puts_it_in_the_book_of_what_was_turned_down(db, offered, user):
    proposals.decide(db, offered, user_id=user.id, outcome="REJECT", reason="too expensive for me")
    db.commit()

    entry = db.execute(
        sa.select(ShadowEntry).where(
            ShadowEntry.proposal_id == offered.id, ShadowEntry.reason == "VETOED"
        )
    ).scalar_one()
    assert entry.entry_price > 0
    assert proposals.effective_status(db, offered) == "REJECTED"


def test_a_lapsed_suggestion_cannot_be_acted_on(db, offered, user):
    """⚠ A suggestion was made at a price. A month later that price is history, and acting on
    it is acting on a judgement about a world that has moved."""
    later = TODAY + dt.timedelta(days=proposals.PROPOSAL_VALID_DAYS + 1)
    assert proposals.effective_status(db, offered, today=later) == "EXPIRED"
    with pytest.raises(Invalid):
        proposals.decide(
            db, offered, user_id=user.id, outcome="APPROVE", reason="late", today=later
        )


def test_the_status_is_derived_so_it_cannot_disagree_with_the_record(db, offered, user):
    """⚠ An editable status on an append-only table would drift out of step with the decision
    record, and nothing could say which of the two was right."""
    assert offered.status == "PENDING", "the row holds only what the SYSTEM decided"
    proposals.decide(db, offered, user_id=user.id, outcome="APPROVE", reason="yes")
    db.commit()
    db.refresh(offered)
    assert offered.status == "PENDING", "the stored column is untouched"
    assert proposals.effective_status(db, offered) == "APPROVED"


def test_the_record_cannot_be_rewritten(db, offered):
    """A thesis revisable after the outcome is known is worth nothing for judging yourself."""
    from sqlalchemy.exc import DatabaseError

    offered.thesis = "actually I always thought so"
    with pytest.raises(DatabaseError):
        db.flush()
    db.rollback()


# --- the evening run ---------------------------------------------------------------------


def test_an_evening_that_suggests_nothing_is_still_recorded(db, real, user, spec, version):
    """⚠ A system that only leaves a trace on the days it acted can never be measured against
    the days it should have acted and did not."""
    _company(db, symbol="PROPQUIET")
    db.commit()

    batch = proposals.synthesise(db, user.id, occurrence_key="test-quiet")
    db.commit()

    run = db.execute(
        sa.select(AgentRun).where(AgentRun.occurrence_key == "test-quiet")
    ).scalar_one()
    assert run.status == "OK"
    assert run.proposals_emitted == len(batch.proposed)
    assert run.finished_at is not None


def test_the_same_evening_cannot_run_twice(db, real, user, spec, version):
    """⚠ A duplicated proposal is a duplicated decision to make."""
    from sqlalchemy.exc import IntegrityError

    proposals.synthesise(db, user.id, occurrence_key="test-once")
    db.commit()
    with pytest.raises(IntegrityError):
        proposals.synthesise(db, user.id, occurrence_key="test-once")
        db.commit()
    db.rollback()
