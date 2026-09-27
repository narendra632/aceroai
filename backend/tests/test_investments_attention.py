"""What the page owes a reader: what is waiting on them, and a way to act on all of it.

⚠ Both halves were found by using the page rather than by reading the code. "1 company needs
your agreement" lived in the third tab and "1 channel waiting for you" inside a collapsed panel
at the bottom of it, with nothing on the tab bar to say either existed. And the company in
question — followed straight from the research queue before anything read it — had no place in
the framework at all, so the button offered to review it opened a list it was not in. No
control anywhere could give it one.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import InvalidationTrigger, Portfolio, Proposal, Turn
from app.services import budget
from app.services.errors import Invalid
from app.services.investments import framework_data, frameworks, reading, scoring, watching
from tests.conftest import make_instrument


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, user, spec):
    """The framework in force, and the real book the page is always read against."""
    db.add(Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL"))
    row = frameworks.install(db, spec, notes="pytest", approved=True)
    db.commit()
    return row


def _company(db, symbol="ATTNONE", name="Attention Telecom"):
    inst = make_instrument(
        db,
        symbol=symbol,
        exchange="NSE",
        name=name,
        asset_class="EQUITY_IN",
        currency="INR",
        sector="TELECOM",
    )
    db.flush()
    return inst


def _live(db, inst):
    db.expire_all()
    return frameworks.live_mapping(db, inst.id)


# --- placing a company that has no place ----------------------------------------------------


def test_a_followed_company_with_no_place_can_be_placed_by_hand(db, version, spec):
    inst = _company(db)
    assert frameworks.live_mapping(db, inst.id) is None

    mapping = frameworks.place(
        db, inst, spec=spec, framework_version_id=version.id, b_bottleneck="B1.1"
    )

    assert mapping.b_bottleneck == "B1.1"
    assert mapping.proposed_by == "USER"
    assert mapping.approved_at is None, "a placement by hand is still a claim to be agreed with"


def test_placing_a_company_that_already_has_a_place_is_refused(db, version, spec):
    """⚠ A correction must go through `remap`, which supersedes and says so. Letting a first
    placement write over an existing one would make a correction look like a fresh start."""
    inst = _company(db)
    frameworks.place(db, inst, spec=spec, framework_version_id=version.id, b_bottleneck="B1.1")

    with pytest.raises(Invalid):
        frameworks.place(db, inst, spec=spec, framework_version_id=version.id, b_bottleneck="B2.1")


def test_a_company_can_be_placed_outside_the_framework(db, version, spec):
    inst = _company(db)
    mapping = frameworks.place(
        db,
        inst,
        spec=spec,
        framework_version_id=version.id,
        b_bottleneck="B1.1",  # ignored: outside the framework names no bottleneck
        off_framework=True,
    )
    assert mapping.off_framework is True and mapping.b_bottleneck is None


def test_placing_over_the_wire_leaves_it_waiting_for_agreement(auth_client, db, version):
    inst = _company(db)
    db.commit()

    out = auth_client.post(
        f"/api/investments/framework/instruments/{inst.id}/place",
        json={"b_bottleneck": "B1.1"},
    )

    assert out.status_code == 200
    body = out.json()
    assert body["approved_at"] is None
    assert D(body["score"]["total"]) == D(0), "nothing scores until it is agreed with"
    kinds = {
        (w["symbol"], w["kind"])
        for w in auth_client.get("/api/investments/attention").json()["items"]
    }
    assert ("ATTNONE", "UNAPPROVED") in kinds and ("ATTNONE", "UNMAPPED") not in kinds


def _model_says(monkeypatch, answer: str, calls: list | None = None):
    async def fake(messages, model=None, effort=None, provider=None, usage=None):
        if calls is not None:
            calls.append(messages)
        if usage is not None:
            usage["tokens_in"] = 900
            usage["tokens_out"] = 40
        return answer

    monkeypatch.setattr("app.core.llm.complete", fake)


def test_asking_for_a_place_proposes_one_unapproved(auth_client, db, user, version, monkeypatch):
    inst = _company(db)
    db.commit()
    _model_says(monkeypatch, '{"id": "B1.1", "confidence": 0.8, "why": "builds towers"}')

    out = auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest").json()

    assert out == {
        "placed": True,
        "bottleneck": "B1.1",
        "confidence": 0.8,
        "why": "builds towers",
    }
    mapping = _live(db, inst)
    assert mapping.proposed_by == "AGENT"
    assert mapping.approved_at is None


def test_a_suggestion_is_billed_to_the_person_who_asked(
    auth_client, db, user, version, monkeypatch
):
    """A model call from the page is spend like any other. Unrecorded, it would be invisible
    to the monthly ceiling — the defect fixed across the module a change ago."""
    inst = _company(db)
    db.commit()
    _model_says(monkeypatch, '{"id": "B1.1", "confidence": 0.8, "why": "x"}')

    auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest")

    db.expire_all()
    spent = (
        db.execute(sa.select(Turn).where(Turn.user_id == user.id, Turn.kind == "job"))
        .scalars()
        .all()
    )
    assert len(spent) == 1 and spent[0].tokens_in == 900


def test_a_bottleneck_the_framework_does_not_have_leaves_it_unplaced(
    auth_client, db, version, monkeypatch
):
    inst = _company(db)
    db.commit()
    _model_says(monkeypatch, '{"id": "B99.9", "confidence": 0.95, "why": "invented"}')

    out = auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest").json()

    assert out["placed"] is False and out["bottleneck"] is None
    assert "not in the framework" in out["why"]
    assert _live(db, inst) is None


def test_an_unsure_answer_leaves_it_unplaced(auth_client, db, version, monkeypatch):
    inst = _company(db)
    db.commit()
    _model_says(monkeypatch, '{"id": "B1.1", "confidence": 0.2, "why": "maybe"}')

    out = auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest").json()

    assert out["placed"] is False
    assert _live(db, inst) is None


def test_a_spent_budget_is_named_rather_than_blamed_on_the_model(
    auth_client, db, version, monkeypatch
):
    """⚠ "The model could not be reached" sends a person to try again tomorrow and be refused
    again. The two need different fixes, so they get different words."""
    inst = _company(db)
    db.commit()
    calls: list = []
    _model_says(monkeypatch, '{"id": "B1.1", "confidence": 0.9, "why": "x"}', calls)

    def refuse(db, user):
        raise budget.BudgetExceeded("spent")

    monkeypatch.setattr(budget, "check", refuse)
    out = auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest").json()

    assert out["placed"] is False
    assert "budget" in out["why"]
    assert calls == [], "nothing may be sent once the month's allowance is gone"


def test_asking_for_a_company_that_already_has_a_place_is_refused(
    auth_client, db, version, spec, monkeypatch
):
    inst = _company(db)
    frameworks.place(db, inst, spec=spec, framework_version_id=version.id, b_bottleneck="B1.1")
    db.commit()
    calls: list = []
    _model_says(monkeypatch, '{"id": "B2.1", "confidence": 0.9, "why": "x"}', calls)

    out = auth_client.post(f"/api/investments/framework/instruments/{inst.id}/suggest")

    assert out.status_code >= 400
    assert calls == [], "no money is spent answering a question that was not open"


# --- what is waiting ------------------------------------------------------------------------


def test_nothing_waiting_is_an_empty_list_rather_than_a_placeholder(auth_client, db, version):
    body = auth_client.get("/api/investments/attention").json()
    assert body == {"items": [], "counts": {}}


def test_a_company_with_no_place_is_listed_under_companies(auth_client, db, version):
    inst = _company(db)
    db.commit()

    body = auth_client.get("/api/investments/attention").json()

    item = next(w for w in body["items"] if w["symbol"] == "ATTNONE")
    assert item["tab"] == "companies"
    assert item["kind"] == "UNMAPPED"
    assert item["severity"] == "decide"
    assert item["ref"] == str(inst.id), "the page needs the instrument to place it in place"
    assert body["counts"]["companies"] == 1


def test_a_source_waiting_for_approval_is_listed_under_sources(auth_client, db, version):
    reading.register(
        db, kind="YOUTUBE", name="waiting channel", handle="UCwait00000000000000", trust_tier=3
    )
    db.commit()

    body = auth_client.get("/api/investments/attention").json()

    assert [w["tab"] for w in body["items"]] == ["sources"]
    assert "waiting channel" in body["items"][0]["text"]


def test_a_disproved_thesis_is_listed_before_anything_else(auth_client, db, user, version):
    """⚠ The order is the feature. A list that gave a fired condition and a lead the same
    weight would teach its reader to skim both."""
    reading.register(
        db, kind="YOUTUBE", name="waiting channel", handle="UCwait00000000000000", trust_tier=3
    )
    inst = _company(db, symbol="ATTFIRED", name="Fired Industries")
    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-attn", kind="MIRROR")
    db.add(book)
    db.flush()
    proposal = Proposal(
        id=uuid.uuid4(),
        portfolio_id=book.id,
        instrument_id=inst.id,
        action="INITIATE",
        status="PENDING",
        thesis="t",
        confidence=D("0.7"),
        horizon_days=365,
        framework_version_id=version.id,
        batch_id=uuid.uuid4(),
        price_snapshot={},
        input_refs={},
        gate_results={},
    )
    db.add(proposal)
    db.flush()
    db.add(
        InvalidationTrigger(
            id=uuid.uuid4(),
            proposal_id=proposal.id,
            instrument_id=inst.id,
            description="ROE falls below 12%",
            metric_key="roe",
            comparator="LT",
            threshold=D(12),
            unit="percent",
            window_until=dt.date.today() + dt.timedelta(days=200),
            status="FIRED",
            fired_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()

    items = auth_client.get("/api/investments/attention").json()["items"]

    assert items[0]["kind"] == "FIRED" and items[0]["severity"] == "urgent"
    assert items[0]["tab"] == "decisions"
    severities = [w["severity"] for w in items]
    order = {"urgent": 0, "decide": 1, "lead": 2}
    assert severities == sorted(severities, key=order.get)


# --- two figures the page draws rather than reads -------------------------------------------


def test_the_margin_of_safety_is_reported_as_a_number_beside_its_sentence(spec):
    inst = type("I", (), {"sector": "EMS_ELECTRONICS"})()
    periods = {"FY26": {"pat": D(100), "dep_amort": D(10)}}
    part = scoring._margin_of_safety(periods, ["FY26"], spec, inst, D(1000), False)
    multiple = frameworks.multiple_for(spec, "EMS_ELECTRONICS").value

    worth = D(100) * multiple
    assert part.value == ((worth - D(1000)) / worth).quantize(D("0.001"))
    assert "below a worth" in part.detail


def test_a_measure_says_how_many_observations_it_is_waiting_for(db):
    measure = watching.claim_accuracy(db)
    assert measure.value is None
    assert measure.needed == watching.MIN_OBSERVATIONS
    assert watching.decision_record(db).needed is None, "a description waits for nothing"
