"""Splits and bonuses: what is read from the feed, and what is done to the ledger.

The assertions worth reading twice are the **refusals**. It is easy to write a parser that
always produces a ratio, and a parser that always produces a ratio will one day multiply a
holding by ten in the wrong direction — a larger fiction than the one it was fixing. So most
of what follows checks that an ambiguous announcement produces no number at all.
"""

import datetime as dt
import uuid
from decimal import Decimal as D
from fractions import Fraction

import pytest

from app.db.models import CorporateAction, Portfolio, Transaction
from app.services.errors import Invalid
from app.services.investments import corpactions, entry, overview
from app.services.investments import portfolio as pf
from app.services.marketdata import nse
from tests.conftest import make_instrument

TODAY = dt.date.today()


def _day(offset: int) -> dt.date:
    return TODAY - dt.timedelta(days=offset)


# --- reading the feed ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("BONUS 1:1", Fraction(2)),
        ("Bonus issue 2:1", Fraction(3)),
        ("BONUS 1:2", Fraction(3, 2)),
        ("FACE VALUE SPLIT FROM RS.10/- TO RE.1/-", Fraction(10)),
        ("FACE VALUE SPLIT FROM RS 10/- TO RS 2/-", Fraction(5)),
        ("SUB-DIVISION OF EQUITY SHARES FROM RS.10/- TO RS.5/-", Fraction(2)),
        # A consolidation is a split the other way, and shrinks the holding.
        ("CONSOLIDATION OF SHARES FROM RE.1/- TO RS.10/-", Fraction(1, 10)),
    ],
)
def test_an_unambiguous_announcement_yields_its_multiplier(purpose, expected):
    parsed = corpactions.parse(purpose)
    assert parsed is not None
    assert parsed.ratio == expected, purpose


@pytest.mark.parametrize(
    "purpose",
    [
        # ⚠ The case the whole design turns on. `1:10` does not say which side is the old
        # face value, and the two readings differ by a factor of a hundred.
        "STOCK SPLIT 1:10",
        "FACE VALUE SPLIT",
        "BONUS ISSUE",
        # Both in one announcement: the order they compose in is not stated.
        "BONUS 1:1 AND FACE VALUE SPLIT FROM RS.10/- TO RS.1/-",
    ],
)
def test_an_ambiguous_announcement_yields_no_number(purpose):
    parsed = corpactions.parse(purpose)
    assert parsed is not None
    assert parsed.ratio is None
    assert parsed.unparsed_because, "a refusal must carry the sentence a person reads"


def test_a_dividend_changes_no_share_count_and_is_not_an_action():
    assert corpactions.parse("DIVIDEND - RS 12 PER SHARE") is None
    assert corpactions.parse("ANNUAL GENERAL MEETING") is None


def test_a_preposterous_ratio_is_refused_rather_than_applied():
    """A parse that produces a 100× change is a misreading, not a corporate action."""
    parsed = corpactions.parse("FACE VALUE SPLIT FROM RS.10000/- TO RE.1/-")
    assert parsed is not None and parsed.ratio is None
    assert "too large" in (parsed.unparsed_because or "")


# --- the book --------------------------------------------------------------------------


@pytest.fixture
def book(db, user):
    """One NSE holding, bought in two lots at different prices.

    Two lots matter: a bonus must leave each lot's own cost per share intact, and a single
    lot cannot tell a correct implementation from one that averages them together.
    """
    inst = make_instrument(
        db,
        symbol="CORPA",
        exchange="NSE",
        name="Corpaction Test Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(inst)
    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-corpactions", kind="REAL")
    db.add(portfolio)
    db.flush()

    for days_ago, qty, price in ((60, "10", "100.00"), (30, "10", "200.00")):
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=portfolio.id,
                instrument_id=inst.id,
                txn_type="BUY",
                trade_date=_day(days_ago),
                quantity=D(qty),
                price=D(price),
                currency="INR",
                fx_rate_inr=D(1),
                entry_source="IMPORT",
            )
        )
    db.commit()
    portfolio.instrument = inst
    return portfolio


def _announce(purpose: str, *, ex_days_ago: int | None = 1) -> nse.CorporateAction:
    return nse.CorporateAction(
        company="Corpaction Test Industries Limited",
        purpose=purpose,
        ex_date=_day(ex_days_ago) if ex_days_ago is not None else None,
    )


def test_an_announcement_is_recorded_once_however_many_evenings_it_is_read(db, book):
    """The feed repeats itself nightly. The row, not a notification, is what remembers."""
    found = [(book.instrument, _announce("BONUS 1:1"))]

    first = corpactions.ingest(db, found)
    second = corpactions.ingest(db, found)
    db.commit()

    assert len(first) == 1
    assert second == [], "a second reading of the same announcement must write nothing"
    assert first[0].status == "PENDING"
    assert corpactions.multiplier(first[0]) == Fraction(2)


def test_an_unreadable_announcement_is_recorded_for_review_not_dropped(db, book):
    """⚠ Silence would be the worst outcome: the price still halves on the ex-date."""
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("STOCK SPLIT 1:10"))])
    db.commit()

    assert action.status == "NEEDS_REVIEW"
    assert action.ratio_num is None
    assert action.note, "the reason must be stored, because a person has to act on it"


def test_applying_a_bonus_conserves_cost_basis_and_each_lot_keeps_its_own_price(db, book):
    """The whole point. More units, same money — per lot, not averaged across them."""
    before = pf.position(db, book.id, book.instrument.id)
    assert before.quantity == D(20)
    assert before.cost_basis == D(3000)
    lot_costs_before = sorted(lot.unit_cost for lot in before.lots)

    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()
    assert corpactions.quantity_change(db, book.id, action) == D(20)

    corpactions.apply(db, book.id, action)
    db.commit()

    after = pf.position(db, book.id, book.instrument.id)
    assert after.quantity == D(40), "a 1:1 bonus doubles the count"
    assert after.cost_basis == D(3000), "and changes the money not at all"
    # ⚠ Each lot halves. Flattening both to the book average conserves the total and reports
    # the wrong realised gain on every FIFO disposal afterwards.
    assert sorted(lot.unit_cost for lot in after.lots) == [c / 2 for c in lot_costs_before]
    assert action.status == "APPLIED" and action.applied_txn_id is not None


def test_applying_a_split_writes_a_visible_ledger_entry(db, book):
    (action,) = corpactions.ingest(
        db, [(book.instrument, _announce("FACE VALUE SPLIT FROM RS.10/- TO RS.2/-"))]
    )
    db.commit()
    txn = corpactions.apply(db, book.id, action)
    db.commit()

    assert txn is not None
    assert txn.txn_type == "SPLIT"
    assert txn.quantity == D(80), "20 held at 5× becomes 100, so 80 are added"
    assert txn.trade_date == action.ex_date, "the change belongs on the day it happened"
    assert txn.entry_source == "CORP_ACTION"
    assert txn.price == D(0), "nothing was paid, and a market price here would be misread"
    assert "SPLIT" in (txn.note or "").upper(), "the feed's own words are the provenance"


def test_a_consolidation_removes_units(db, book):
    (action,) = corpactions.ingest(
        db, [(book.instrument, _announce("CONSOLIDATION OF SHARES FROM RE.1/- TO RS.10/-"))]
    )
    db.commit()
    corpactions.apply(db, book.id, action)
    db.commit()

    after = pf.position(db, book.id, book.instrument.id)
    assert after.quantity == D(2)
    assert after.cost_basis == D(3000)


def test_an_action_on_something_not_held_is_closed_rather_than_left_flagging(db, book, user):
    """Otherwise the holding carries an unresolvable warning for ever."""
    other = make_instrument(
        db,
        symbol="NOTHELD",
        exchange="NSE",
        name="Not Held Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(other)
    db.flush()
    (action,) = corpactions.ingest(db, [(other, _announce("BONUS 1:1"))])
    db.commit()

    assert corpactions.apply(db, book.id, action) is None
    db.commit()
    assert action.status == "IGNORED"


def test_an_unreadable_action_cannot_be_applied(db, book):
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("STOCK SPLIT 1:10"))])
    db.commit()
    with pytest.raises(Invalid):
        corpactions.apply(db, book.id, action)


def test_an_undated_announcement_is_never_applied_on_a_schedule(db, book):
    """The day a quantity changed is a fact. Applying one on the day it was READ would put
    the change on the wrong date and distort every figure derived from the ledger's dates."""
    corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1", ex_days_ago=None))])
    db.commit()
    assert corpactions.due(db) == []


def test_an_action_whose_ex_date_has_not_arrived_is_not_yet_due(db, book):
    corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1", ex_days_ago=-5))])
    db.commit()
    assert corpactions.due(db) == []
    assert corpactions.due(db, today=TODAY + dt.timedelta(days=5)), "due once the date arrives"


# --- gate G7: what the page is told ------------------------------------------------------


def test_an_outstanding_action_flags_the_holding_and_applying_it_clears_the_flag(db, book, user):
    """While the two disagree, the price and the quantity are counting different things."""
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()

    flagged = overview.summary(db, book.id, user.id)
    (holding,) = [h for h in flagged.holdings if h.symbol == "CORPA"]
    assert holding.open_action is not None
    assert holding.open_action.quantity_before == D(20)
    assert holding.open_action.quantity_after == D(40)
    assert holding.open_action.ratio_text == "1:1 bonus"

    corpactions.apply(db, book.id, action)
    db.commit()

    cleared = overview.summary(db, book.id, user.id)
    (holding,) = [h for h in cleared.holdings if h.symbol == "CORPA"]
    assert holding.open_action is None
    assert any(a.status == "APPLIED" for a in cleared.corporate_actions)


def test_dismissing_an_action_clears_the_flag_without_touching_the_ledger(db, book, user):
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("STOCK SPLIT 1:10"))])
    db.commit()

    corpactions.dismiss(db, action, note="not my company")
    db.commit()

    assert pf.position(db, book.id, book.instrument.id).quantity == D(20)
    view = overview.summary(db, book.id, user.id)
    assert all(h.open_action is None for h in view.holdings)


def test_an_applied_action_cannot_be_dismissed(db, book):
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()
    corpactions.apply(db, book.id, action)
    db.commit()
    with pytest.raises(Invalid):
        corpactions.dismiss(db, action)


def test_an_applied_action_is_undone_by_the_ordinary_correction_path(db, book):
    """Applying must be reversible by the mechanism that already exists, not a second one."""
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()
    txn = corpactions.apply(db, book.id, action)
    db.commit()
    assert pf.position(db, book.id, book.instrument.id).quantity == D(40)

    entry.reverse(db, txn.id, note="the exchange match was wrong")
    db.commit()

    assert pf.position(db, book.id, book.instrument.id).quantity == D(20)
    # ⚠ Both rows survive. The record shows that it was applied and then withdrawn.
    assert db.get(Transaction, txn.id) is not None


def test_the_record_of_an_action_cannot_be_deleted_by_deleting_the_holding(db, book):
    """A foreign key, not a convention: an applied action points at what it wrote."""
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()
    corpactions.apply(db, book.id, action)
    db.commit()

    stored = db.get(CorporateAction, action.id)
    assert stored.applied_txn_id is not None
    assert db.get(Transaction, stored.applied_txn_id) is not None


# --- NSE's actual wording ---------------------------------------------------------------
#
# ⚠ The live feed carries no split or bonus most weeks — checked on 20 Sep 2026: 101 items,
# every one a dividend, and none of them falsely matched. So the forms below stand in for the
# real thing, and each is a wording NSE actually publishes rather than one invented here.


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("FACE VALUE SPLIT (SUB-DIVISION) - FROM RS.10/- TO RS.1/-", Fraction(10)),
        ("FACE VALUE SPLIT FROM RS.2/- TO RE.1/-", Fraction(2)),
        ("BONUS ISSUE 1:1", Fraction(2)),
        ("BONUS 3:5", Fraction(8, 5)),
    ],
)
def test_nse_wordings_that_carry_a_ratio_are_read(purpose, expected):
    parsed = corpactions.parse(purpose)
    assert parsed is not None and parsed.ratio == expected, purpose


@pytest.mark.parametrize(
    "purpose",
    [
        "DIVIDEND - RS 2.50 PER SHARE",
        "DIVIDEND - RE 0.02 PER SHARE",
        "INTDIVIDEND - RS 160 PER SHARE",
        "ANNUAL GENERAL MEETING",
        "RIGHTS 1:4 @ PREMIUM RS.90/-",
    ],
)
def test_the_everyday_feed_produces_no_action_at_all(purpose):
    """99 of 101 live items are dividends. One false positive a week is one too many."""
    assert corpactions.parse(purpose) is None


# --- over the wire -----------------------------------------------------------------------


def test_the_routes_are_reachable_and_return_exact_money(db, auth_client, book):
    """Every figure crosses as a quoted string, like everything else in this module."""
    (action,) = corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()

    raw = auth_client.get("/api/investments/corporate-actions")
    assert raw.status_code == 200
    (item,) = [a for a in raw.json() if a["id"] == str(action.id)]
    assert item["ratio_text"] == "1:1 bonus"
    assert item["quantity_after"] == "40.00000000"
    assert isinstance(item["quantity_after"], str), "money and quantities are never JSON numbers"

    applied = auth_client.post(f"/api/investments/corporate-actions/{action.id}/apply")
    assert applied.status_code == 200
    assert applied.json()["status"] == "APPLIED"
    assert pf.position(db, book.id, book.instrument.id).quantity == D(40)


def test_an_action_on_a_holding_this_book_never_touched_is_not_found(db, auth_client, book):
    """An id is not an authorisation — the same rule the reverse route follows."""
    stranger = make_instrument(
        db,
        symbol="STRANGER",
        exchange="NSE",
        name="Stranger Industries Limited",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(stranger)
    db.flush()
    (action,) = corpactions.ingest(db, [(stranger, _announce("BONUS 1:1"))])
    db.commit()

    assert (
        auth_client.post(f"/api/investments/corporate-actions/{action.id}/apply").status_code == 404
    )


def test_the_schedule_fa_route_answers_for_a_book_with_nothing_foreign(auth_client, book):
    body = auth_client.get("/api/investments/schedule-fa").json()
    assert body["holdings"] == []
    assert body["years_available"] == []


# --- the job -----------------------------------------------------------------------------


def test_the_job_records_applies_and_says_so_once(db, user, book, monkeypatch):
    """One run: read the feed, write the row, apply what is due, notify once."""
    from app.jobs import prices

    monkeypatch.setattr(prices.nse, "corporate_actions", lambda *a, **k: [_announce("BONUS 1:1")])
    monkeypatch.setattr(
        prices.feed,
        "share_changing_actions",
        lambda *a, **k: [(book.instrument, _announce("BONUS 1:1"))],
    )

    first = prices.corporate_actions_watch(db, user)
    assert first.detail["recorded"] == 1
    assert first.detail["applied"] == 1, "the ex-date has passed, so it is applied at once"
    assert first.notify is not None and "bonus" in first.notify.title
    assert pf.position(db, book.id, book.instrument.id).quantity == D(40)

    # ⚠ The row is what remembers, not the notification. A second evening must be silent
    # even though the feed still carries the same item.
    second = prices.corporate_actions_watch(db, user)
    assert second.silent and second.detail == {"recorded": 0, "applied": 0, "needs_review": 0}
    assert pf.position(db, book.id, book.instrument.id).quantity == D(40)


def test_an_unreachable_feed_still_applies_what_is_already_recorded(db, user, book, monkeypatch):
    """An ex-date does not wait for a feed to come back."""
    from app.jobs import prices
    from app.services.marketdata.http import ProviderError

    corpactions.ingest(db, [(book.instrument, _announce("BONUS 1:1"))])
    db.commit()

    def refuse(*a, **k):
        raise ProviderError("NSE", "unreachable")

    monkeypatch.setattr(prices.nse, "corporate_actions", refuse)

    result = prices.corporate_actions_watch(db, user)
    assert result.detail["failed"] == "unreachable"
    assert result.detail["applied"] == 1
    assert pf.position(db, book.id, book.instrument.id).quantity == D(40)
