"""Every model call the Investments module makes is recorded, and stopped by the budget.

⚠ Found in review: five call sites spent money and none of them said so. The reading poll is
not an AI job — its main work, the exchange's filings, is free and must keep flowing — so the
runner never checked the budget for it, and nothing anywhere recorded what its model calls
cost. The Insights page under-reported spend and the monthly ceiling was a ceiling on chat.
"""

import asyncio

import pytest
import sqlalchemy as sa

from app.core import telemetry
from app.db.models import Turn
from app.services import budget
from app.services.investments import billing, spoken


@pytest.fixture
def priced_llm(monkeypatch):
    """A model that reports usage, as the real providers do."""
    calls = []

    async def fake(messages, model=None, effort=None, provider=None, usage=None):
        calls.append(messages)
        if usage is not None:
            usage["tokens_in"] = 1200
            usage["tokens_out"] = 80
        return '{"companies": []}'

    monkeypatch.setattr("app.core.llm.complete", fake)
    return calls


def _turns(db, user_id):
    db.expire_all()
    return (
        db.execute(sa.select(Turn).where(Turn.user_id == user_id, Turn.kind == "job"))
        .scalars()
        .all()
    )


def test_a_model_call_inside_a_job_is_recorded_as_spend(db, user, priced_llm):
    with telemetry.billing(user.id):
        asyncio.run(
            billing.complete([{"role": "user", "content": "x"}], effort="low", purpose="stance")
        )

    turns = _turns(db, user.id)
    assert len(turns) == 1, "the call must appear where spend is counted"
    assert turns[0].tokens_in == 1200 and turns[0].tokens_out == 80


def test_the_budget_is_checked_before_the_money_moves(db, user, priced_llm, monkeypatch):
    """⚠ Checked per call, not per job. The job that reads filings must keep running with the
    budget spent — a budget is a limit on spending, not on reading — so the refusal has to
    happen at the one line that spends."""

    def refuse(db, user):
        raise budget.BudgetExceeded("spent")

    monkeypatch.setattr(budget, "check", refuse)
    with telemetry.billing(user.id), pytest.raises(budget.BudgetExceeded):
        asyncio.run(
            billing.complete([{"role": "user", "content": "x"}], effort="low", purpose="stance")
        )
    assert priced_llm == [], "nothing may be sent once the month's allowance is gone"


def test_over_budget_a_transcript_degrades_to_no_names_rather_than_failing(
    db, user, priced_llm, monkeypatch
):
    """The honest degraded state already existed: a failed read returns no names, and the
    video is still recorded as published. Over budget is just one more way to fail."""

    def refuse(db, user):
        raise budget.BudgetExceeded("spent")

    monkeypatch.setattr(budget, "check", refuse)
    with telemetry.billing(user.id):
        assert spoken.names_in("कायन्स टेक्नोलॉजी के बारे में बात करेंगे") == []
    assert priced_llm == []


def test_a_call_with_no_one_to_bill_is_not_billed_to_a_guess(db, user, other_user, priced_llm):
    """With two users and nobody named, the call is not attributed rather than attributed to
    the wrong person."""
    asyncio.run(
        billing.complete([{"role": "user", "content": "x"}], effort="low", purpose="stance")
    )
    assert _turns(db, user.id) == [] and _turns(db, other_user.id) == []
    assert len(priced_llm) == 1, "the call itself still happens"


def test_every_investment_model_call_goes_through_the_billed_path():
    """A tripwire. A sixth call site added straight to the model would be invisible to the
    budget again, and the first sign would be a bill."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "investments"
    offenders = [
        path.name
        for path in root.glob("*.py")
        if path.name != "billing.py" and "llm.complete(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"call the model through billing.complete: {offenders}"
