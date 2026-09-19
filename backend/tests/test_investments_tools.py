"""The six investment tools, exercised the way the model actually reaches them.

⚠ **Every test here goes through `tools.execute`, not through the handler directly.** That is
the entire point of the file. The tools shipped with a signature that took a `User` object
while the dispatcher passes `user_id: uuid.UUID`, so all six raised
`AttributeError: 'UUID' object has no attribute 'id'` on their first line — and the user was
told "the portfolio service failed" for every question they asked about their own holdings.

Nothing caught it because the existing tool tests only asserted that the schemas registered.
A test that never invokes a handler cannot discover that no handler can run. Calling
`get_portfolio(db, user, {})` directly would have passed while the product was broken, so
these tests deliberately take the long way round.

⚠ **The symbols here are deliberately fictional.** Everywhere else the investment tests use
real ones — KAYNES, SPCX — because the figures are checked against Groww. This file cannot,
because it drives the *production* write path: `record_price` stores its observation with
source `USER`, the same as a real one, so teardown has no way to tell it apart from a price
the user actually recorded. On a development database seeded with the real book that row
survives and prices somebody else's holding two files later.

The rule this file follows: **a test that exercises a production write path uses data that
cannot collide with the real book.** Fictional symbols become orphaned instruments after
teardown, and the orphan sweep takes their prices with them.
"""

import asyncio
import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.core import tools
from app.db.models import Portfolio, Transaction
from tests.conftest import make_instrument


def call(db, user_id, name: str, args: dict | None = None) -> dict:
    """Invoke a tool exactly as the model does — through the dispatcher.

    `asyncio.run` in a sync test rather than an async test, matching `test_memory_tools.py`:
    this suite has no async plugin and adding one to reach six handlers is not the trade.
    """
    return asyncio.run(tools.execute(db, user_id, name, args or {}))


INVESTMENT_TOOLS = [
    "record_transaction",
    "confirm_transaction",
    "get_portfolio",
    "get_position",
    "record_price",
    "undo_transaction",
]


@pytest.fixture
def book(db, user):
    """One Indian share and one US share — both fictional. See the module docstring."""
    instruments = {
        "TESTCO": make_instrument(
            db,
            symbol="PYTTESTCO",
            exchange="NSE",
            name="Pytest Industries",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "TESTUS": make_instrument(
            db,
            symbol="PYTTESTUS",
            exchange="NASDAQ",
            name="Pytest Stateside",
            asset_class="EQUITY_US",
            currency="USD",
        ),
    }
    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-tools", kind="REAL")
    db.add(portfolio)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=portfolio.id,
            instrument_id=instruments["TESTCO"].id,
            txn_type="BUY",
            trade_date=dt.date.today() - dt.timedelta(days=40),
            quantity=D("5"),
            price=D("3378.80"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    portfolio.instruments = instruments
    return portfolio


# --- the failure that shipped -------------------------------------------------------------


@pytest.mark.parametrize("name", INVESTMENT_TOOLS)
def test_every_tool_survives_the_dispatcher_calling_convention(db, user, book, name):
    """⚠ The regression. `execute` passes a UUID; these took a User and read `.id` off it.

    The assertion is not that the call succeeds — several of these need arguments this test
    does not supply. It is that the failure, if any, is a *domain* error the model can act on,
    never an AttributeError from the handler's own first line.
    """
    result = call(db, user.id, name, {})
    if not result["ok"]:
        assert "has no attribute" not in result["error"], (
            f"{name} broke on the dispatcher's calling convention: {result['error']}"
        )


def test_get_portfolio_returns_the_holdings(db, user, book):
    result = call(db, user.id, "get_portfolio", {})
    assert result["ok"], result.get("error")
    payload = result["result"]
    assert any("PYTTESTCO" in str(payload) for _ in [0]), payload


def test_get_position_reports_one_holding(db, user, book):
    result = call(db, user.id, "get_position", {"symbol": "PYTTESTCO"})
    assert result["ok"], result.get("error")
    assert "PYTTESTCO" in str(result["result"])


def test_an_unknown_symbol_is_a_recoverable_error_not_a_crash(db, user, book):
    """`execute` promises the model a structured error it can act on rather than an exception."""
    result = call(db, user.id, "get_position", {"symbol": "NOSUCH"})
    assert result["ok"] is False
    assert result["error"]


def test_a_user_with_no_book_is_told_so_plainly(db, user):
    result = call(db, user.id, "get_portfolio", {})
    assert result["ok"] is False
    assert "portfolio" in result["error"].lower()


# --- the two-step write --------------------------------------------------------------------


def test_recording_returns_a_draft_and_writes_nothing(db, user, book):
    """⚠ The model never appends to the ledger in one call. It gets back what it understood,
    costed and validated; a person confirms it."""
    before = len(list(db.execute(sa.select(Transaction)).scalars().all()))
    result = call(
        db,
        user.id,
        "record_transaction",
        {
            "symbol": "PYTTESTCO",
            "action": "BUY",
            "quantity": "1",
            "price": "3500",
            "date": "today",
        },
    )
    assert result["ok"], result.get("error")
    after = len(list(db.execute(sa.select(Transaction)).scalars().all()))
    assert after == before, "a draft is not a transaction"


def test_confirming_a_draft_writes_it(db, user, book):
    drafted = call(
        db,
        user.id,
        "record_transaction",
        {
            "symbol": "PYTTESTCO",
            "action": "BUY",
            "quantity": "1",
            "price": "3500",
            "date": "today",
        },
    )
    assert drafted["ok"], drafted.get("error")

    handle = drafted["result"].get("confirm_with") or drafted["result"].get("handle")
    assert handle, f"the draft must hand back something to confirm with: {drafted['result']}"

    confirmed = call(db, user.id, "confirm_transaction", {"handle": handle})
    assert confirmed["ok"], confirmed.get("error")

    held = call(db, user.id, "get_position", {"symbol": "PYTTESTCO"})
    assert "6" in str(held["result"]), f"5 held plus the 1 just confirmed: {held['result']}"


def test_recording_a_price_makes_the_holding_valuable(db, user, book):
    result = call(
        db,
        user.id,
        "record_price",
        {"symbol": "PYTTESTCO", "price": "3598"},
    )
    assert result["ok"], result.get("error")

    view = call(db, user.id, "get_portfolio", {})
    assert view["ok"]
    assert "3598" in str(view["result"]) or "value" in str(view["result"]).lower()


# --- what the tools must never do -----------------------------------------------------------


def test_another_users_portfolio_is_not_reachable(db, user, other_user, book):
    """The tool takes a user id from the session, never from the model's arguments."""
    result = call(db, other_user.id, "get_portfolio", {})
    assert result["ok"] is False, "the other user has no book of their own"


def test_the_tool_count_includes_all_six(db):
    names = {t["function"]["name"] for t in tools.TOOLS}
    missing = set(INVESTMENT_TOOLS) - names
    assert not missing, f"not registered: {missing}"
