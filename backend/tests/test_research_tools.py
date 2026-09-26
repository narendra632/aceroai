"""The research tools, exercised the way the model actually reaches them.

⚠ **Every test goes through `tools.execute`, never the handler directly** — the lesson
`test_investments_tools.py` was written to record. Six investment tools once shipped with a
signature that took a `User` while the dispatcher passes a `uuid.UUID`, so every one of them
raised on its first line and the user was told "the portfolio service failed" for every
question about their own money. A test that calls the handler directly would have passed
throughout. So these take the long way round, on purpose.

⚠ **The point of most of these is what they return when there is nothing to return.** A read
tool that only works on a populated database is a tool that breaks on the day it is most
needed, and an empty portfolio is the state every new install starts in.
"""

import asyncio
import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.core import tools
from app.core.tools import research
from app.db.models import Fundamental, PriceObservation, SourceItem
from app.services.investments import framework_data, frameworks, gates, proposals
from app.services.marketdata import nse_xbrl
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


def call(db, user_id, name: str, args: dict | None = None) -> dict:
    """Invoke a tool exactly as the model does — through the dispatcher.

    The envelope is unwrapped on success so a test reads the payload the model reads, and
    left intact on failure so `{"ok": False, "error": ...}` can still be asserted on.
    """
    reply = asyncio.run(tools.execute(db, user_id, name, args or {}))
    return reply["result"] if reply.get("ok") else reply


READ_ONLY = [
    "get_suggestions",
    "get_research_queue",
    "get_reading",
    "get_predictions",
    "get_benchmarks",
    "get_verdict",
]


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    return frameworks.install(db, spec)


def _company(db, symbol="RSCHCO"):
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


def _accounts(db, inst, period, **metrics):
    end = dt.date(int(period[2:4]) + 2000, 3, 31)
    source = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=inst.id,
        source=nse_xbrl.PROVIDER,
        external_id=f"{inst.symbol}-{period}-{uuid.uuid4().hex[:6]}",
        url="https://x/f.xml",
        title=f"{inst.symbol} {period}",
        published_at=dt.datetime.combine(end, dt.time(0, 0), dt.UTC),
        fetched_at=dt.datetime.now(dt.UTC),
        content_hash=uuid.uuid4().hex,
        excerpt="<x:Tag>1</x:Tag>",
    )
    db.add(source)
    db.flush()
    for key, value in metrics.items():
        db.add(
            Fundamental(
                instrument_id=inst.id,
                fiscal_period=period,
                metric_key=key,
                source_item_id=source.id,
                value=D(str(value)),
                unit="inr",
                period_end=end,
                consolidated=True,
                taxonomy="INDAS",
            )
        )
    db.commit()


def _excellent(db, inst, price=D(100)):
    for period in ("FY26", "FY25"):
        _accounts(
            db,
            inst,
            period,
            pat=D(300),
            pat_owners=D(300),
            equity=D(1000),
            pbt=D(400),
            revenue=D(2000),
            finance_costs=D(10),
            ocf=D(300),
            dep_amort=D(20),
            cash=D(50),
            borrowings_current=D(0),
            borrowings_noncurrent=D(0),
            paid_up_capital=D(100),
            face_value=D(1),
        )
    db.add(
        PriceObservation(
            instrument_id=inst.id,
            observed_at=dt.datetime.now(dt.UTC),
            source=TEST_SOURCE,
            kind="CLOSE",
            price=price,
            currency="INR",
        )
    )
    db.commit()


# --- they answer on an empty book ---------------------------------------------------------


@pytest.mark.parametrize("name", READ_ONLY)
def test_every_read_tool_answers_on_an_empty_book(db, user, name):
    """⚠ Every new install starts here. A tool that needs a populated database is a tool that
    fails on the first day anybody uses it."""
    result = call(db, user.id, name)
    assert result.get("ok") is not False, result


def test_asking_about_a_company_nobody_tracks_says_so(db, user):
    result = call(db, user.id, "explain_company", {"symbol": "NOTREAL"})
    assert result["ok"] is False
    assert "NOTREAL" in result["error"]


# --- what they actually say ------------------------------------------------------------------


def test_a_company_explains_itself_component_by_component(db, user, spec, version):
    inst = _company(db)
    _excellent(db, inst)
    result = call(db, user.id, "explain_company", {"symbol": "RSCHCO"})

    assert result["symbol"] == "RSCHCO"
    names = {c["name"] for c in result["components"]}
    assert {"roe", "roce", "cash_conversion", "margin_of_safety"} <= names
    assert all(c["why"] for c in result["components"]), "a score with no reason is a number"
    assert result["years_read"] == 2


def test_a_component_that_cannot_apply_reads_differently_from_one_not_read(db, user, spec, version):
    """⚠ Three facts, three renderings. The model must never flatten 'does not apply' into
    'not read' when it speaks — one is a gap somebody can fill and the other never is."""
    bank = make_instrument(
        db,
        symbol="RSCHBANK",
        exchange="NSE",
        name="Rsch Bank",
        asset_class="EQUITY_IN",
        currency="INR",
        sector="PRIVATE_BANK",
    )
    db.add(bank)
    db.flush()
    for period in ("FY26", "FY25"):
        _accounts(
            db,
            bank,
            period,
            interest_earned=D(300000),
            interest_expended=D(170000),
            revenue=D(360000),
            operating_profit=D(110000),
            pbt=D(86000),
            pat=D(67000),
            share_capital=D(765),
            other_equity=D(400000),
        )

    result = call(db, user.id, "explain_company", {"symbol": "RSCHBANK"})
    by_name = {c["name"]: c["points"] for c in result["components"]}
    assert by_name["roce"] == "does not apply"
    assert by_name["cost_to_income"].startswith(("0", "1", "2"))
    assert "not read" not in by_name["roce"]


def test_the_verdict_keeps_not_yet_apart_from_not_met(db, user):
    """⚠ The distinction the whole go/no-go rests on. A criterion nothing can test yet is not
    a criterion that failed, and reporting it as one would call the experiment early."""
    result = call(db, user.id, "get_verdict")
    states = {c["status"] for c in result["criteria"]}
    assert states <= {"met", "not met", "not yet"}
    assert "not yet" in states, "on a fresh book most of these cannot be tested at all"


def test_the_predictions_tool_shows_the_record_including_blocked_ideas(db, user, spec, version):
    """⚠ The record exists BECAUSE it includes blocked ideas — without them the system ran a
    month and wrote zero predictions. The tool says which is which, because a reader who
    thought these were all things he had bought would read far more into them than is there."""
    inst = _company(db, symbol="RSCHPRED")
    _excellent(db, inst)
    frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    mirror = proposals.mirror(db, user.id)
    draft = proposals.draft_for(db, mirror, inst, spec, set())
    verdict = gates.Verdict([gates.GateResult("G3_margin_of_safety", False, False, "too dear")])
    proposals.write(
        db,
        book_row=mirror,
        user_id=user.id,
        draft=draft,
        verdict=verdict,
        batch_id=uuid.uuid4(),
        framework_version_id=version.id,
    )
    db.commit()

    result = call(db, user.id, "get_predictions")
    assert result["open_total"] >= 1
    assert all(row["from"] == "a blocked idea" for row in result["open"])


def test_suggestions_report_the_rule_that_refused_them(db, user, spec, version):
    inst = _company(db, symbol="RSCHBLOCK")
    _excellent(db, inst)
    frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    mirror = proposals.mirror(db, user.id)
    draft = proposals.draft_for(db, mirror, inst, spec, set())
    verdict = gates.Verdict([gates.GateResult("G1_framework", False, False, "not agreed")])
    proposals.write(
        db,
        book_row=mirror,
        user_id=user.id,
        draft=draft,
        verdict=verdict,
        batch_id=uuid.uuid4(),
        framework_version_id=version.id,
    )
    db.commit()

    result = call(db, user.id, "get_suggestions")
    assert result["open"] == []
    assert result["blocked"][0]["blocked_by"] == "G1_framework"
    assert result["blocked"][0]["thesis"]


# --- the one write, and its two steps ---------------------------------------------------------


@pytest.fixture
def offered(db, user, spec, version):
    inst = _company(db, symbol="RSCHOFFER")
    _excellent(db, inst)
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, mapping)
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


def test_deciding_is_prepared_and_then_confirmed_never_in_one_step(db, user, offered):
    """⚠ A decision is the row the system is eventually graded on. A model that could approve
    in a single call would be writing its own report card, so this follows the same
    draft-then-confirm shape the ledger uses for the same reason."""
    draft = call(
        db,
        user.id,
        "decide_suggestion",
        {
            "symbol": "RSCHOFFER",
            "outcome": "REJECT",
            "reason": "I want to see another quarter first.",
        },
    )
    assert draft["handle"]
    assert draft["outcome"] == "REJECT"
    assert (
        db.execute(sa.select(sa.func.count()).select_from(sa.text("decisions"))).scalar_one() == 0
    ), "nothing may be written before confirmation"

    done = call(db, user.id, "confirm_decision", {"handle": draft["handle"]})
    assert done["recorded"] is True


def test_a_decision_without_a_reason_is_refused(db, user, offered):
    """⚠ Required by the database, not merely asked for. The reason is the only data that ever
    reveals what kinds of suggestion keep being turned down."""
    result = call(
        db,
        user.id,
        "decide_suggestion",
        {
            "symbol": "RSCHOFFER",
            "outcome": "REJECT",
            "reason": "   ",
        },
    )
    assert result["ok"] is False


def test_a_blocked_suggestion_cannot_be_decided_on(db, user, spec, version):
    """It was never offered, so there is nothing to accept or turn down."""
    inst = _company(db, symbol="RSCHNOPE")
    _excellent(db, inst)
    frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()
    mirror = proposals.mirror(db, user.id)
    draft = proposals.draft_for(db, mirror, inst, spec, set())
    proposals.write(
        db,
        book_row=mirror,
        user_id=user.id,
        draft=draft,
        verdict=gates.Verdict([gates.GateResult("G1_framework", False, False, "no")]),
        batch_id=uuid.uuid4(),
        framework_version_id=version.id,
    )
    db.commit()

    result = call(
        db,
        user.id,
        "decide_suggestion",
        {
            "symbol": "RSCHNOPE",
            "outcome": "APPROVE",
            "reason": "looks good to me",
        },
    )
    assert result["ok"] is False
    assert "no open suggestion" in result["error"]


def test_a_stale_handle_is_refused_rather_than_guessed(db, user):
    result = call(db, user.id, "confirm_decision", {"handle": "deadbe"})
    assert result["ok"] is False


def test_every_research_tool_is_registered_and_reachable():
    """A handler with no schema is unreachable; a schema with no handler is a broken promise."""
    declared = {s["function"]["name"] for s in research.SCHEMAS}
    assert declared == set(research.HANDLERS)
    registered = {s["function"]["name"] for s in tools.TOOLS}
    assert declared <= registered
