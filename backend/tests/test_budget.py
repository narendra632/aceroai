"""The monthly spend ceiling.

Observability could report cost but not stop it. These tests pin the half that stops it —
and, just as important, that an account with no limit is completely unaffected.
"""

import asyncio
import datetime as dt
from decimal import Decimal

import pytest

from app.core import handler
from app.db.models import Turn
from app.services import budget


def _spend(db, user, amount, *, days_ago=0, kind="chat"):
    db.add(
        Turn(
            user_id=user.id,
            kind=kind,
            provider="openai",
            model="gpt-5.4-mini",
            started_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago),
            duration_ms=1000,
            tokens_in=100,
            tokens_out=20,
            cost_usd=Decimal(amount),
            ok=True,
        )
    )
    db.commit()


def _drain(db, user, text="hello"):
    """Run one turn through the one brain and collect its events.

    `asyncio.run` rather than an async test: this suite has no async plugin, and adding a
    dependency for four tests is not worth it — `tests/test_memory.py` does the same.
    """

    async def go():
        return [(k, d) async for k, d in handler.handle_message(db, user, text, "web", None)]

    return asyncio.run(go())


# --- the default: nothing changes -----------------------------------------------------


def test_no_limit_means_no_limit(db, user):
    """An account that never sets one must behave exactly as it did before this existed."""
    _spend(db, user, "500.00")

    budget.check(db, user)  # must not raise
    assert budget.status(db, user)["state"] == "off"


def test_a_zero_limit_is_treated_as_off_not_as_a_ban(db, user):
    """Otherwise a stray 0 would lock the account out of its own assistant."""
    user.monthly_budget_usd = Decimal("0")
    db.commit()

    budget.check(db, user)
    assert budget.status(db, user)["state"] == "off"


# --- the states -----------------------------------------------------------------------


def test_states_move_through_ok_warning_exceeded(db, user):
    user.monthly_budget_usd = Decimal("10.00")
    db.commit()

    assert budget.status(db, user)["state"] == "ok"

    _spend(db, user, "8.00")  # 80% — the warning band
    assert budget.status(db, user)["state"] == "warning"

    _spend(db, user, "2.00")  # exactly at the limit counts as reached
    assert budget.status(db, user)["state"] == "exceeded"


def test_reaching_the_limit_exactly_stops(db, user):
    """`>=`, not `>`. A limit of $5 that permits spending $5 and then one more turn is
    not a limit anyone asked for."""
    user.monthly_budget_usd = Decimal("5.00")
    _spend(db, user, "5.00")
    db.commit()

    with pytest.raises(budget.BudgetExceeded):
        budget.check(db, user)


def test_remaining_never_goes_negative(db, user):
    user.monthly_budget_usd = Decimal("5.00")
    _spend(db, user, "9.00")
    db.commit()

    assert budget.status(db, user)["remaining_usd"] == Decimal("0")


# --- what counts ----------------------------------------------------------------------


def test_background_work_counts_toward_the_limit(db, user):
    """Embeddings and fact extraction are a third of all calls. Counting only visible
    replies would let them escape the ceiling entirely."""
    user.monthly_budget_usd = Decimal("1.00")
    _spend(db, user, "0.60", kind="embed")
    _spend(db, user, "0.50", kind="memory_extract")
    db.commit()

    with pytest.raises(budget.BudgetExceeded):
        budget.check(db, user)


def test_last_months_spend_does_not_count_against_this_month(db, user):
    user.monthly_budget_usd = Decimal("5.00")
    _spend(db, user, "99.00", days_ago=45)
    db.commit()

    budget.check(db, user)  # must not raise
    assert budget.status(db, user)["spent_usd"] < Decimal("5.00")


def test_the_month_boundary_is_the_users_timezone_not_utc(db, user):
    """The reset day must line up with the days the Insights page draws, or the chart and
    the limit would disagree about which month a turn fell in."""
    from zoneinfo import ZoneInfo

    from app.config import settings

    start = budget.month_start()
    local = start.astimezone(ZoneInfo(settings.app_timezone))
    assert (local.day, local.hour, local.minute) == (1, 0, 0)


def test_the_reset_date_is_the_first_of_next_month(db, user):
    resets = budget.next_month_start()
    assert resets.day == 1
    assert resets > dt.datetime.now(dt.UTC).date()


# --- the refusal, through the one brain ----------------------------------------------


def test_a_blocked_turn_is_refused_with_an_actionable_message(db, user):
    """A refusal that does not say how to proceed is just a wall."""
    user.monthly_budget_usd = Decimal("1.00")
    _spend(db, user, "2.00")
    db.commit()

    events = _drain(db, user)

    assert [k for k, _ in events] == ["error"]
    message = events[0][1]
    assert "$1.00" in message and "$2.00" in message
    assert "Settings" in message  # how to undo it


def test_a_blocked_turn_stores_nothing(db, user):
    """Checked before anything is persisted, so a message that was never answered does
    not end up in the history — and no `turns` row is written, because no model call was
    made and inventing one would inflate the error rate on the Insights page."""
    user.monthly_budget_usd = Decimal("1.00")
    _spend(db, user, "2.00")
    db.commit()
    before = db.query(Turn).filter(Turn.user_id == user.id).count()

    _drain(db, user)

    assert db.query(Turn).filter(Turn.user_id == user.id).count() == before


def test_raising_the_limit_unblocks_immediately(db, user):
    """The whole point of putting it in Settings: you can get yourself out."""
    user.monthly_budget_usd = Decimal("1.00")
    _spend(db, user, "2.00")
    db.commit()
    assert [k for k, _ in _drain(db, user)] == ["error"]

    user.monthly_budget_usd = Decimal("50.00")
    db.commit()

    assert "delta" in [k for k, _ in _drain(db, user)]


def test_an_account_with_no_limit_is_never_refused(db, user):
    _spend(db, user, "999.00")

    assert "delta" in [k for k, _ in _drain(db, user)]
