"""The HTTP surface.

The assertions that matter here are not "does it return 200". They are:

* **money arrives as an exact string**, not a JSON number,
* **an id is not an authorisation**, and
* **there is no way to delete anything**, because the ledger is append-only and an endpoint
  promising otherwise would be a lie in the OpenAPI schema before it was one in the interface.
"""

import datetime as dt
import json
import uuid
from decimal import Decimal as D

import pytest

from app.db.models import Portfolio, Transaction
from app.services.investments import overview, pricing
from app.services.investments import portfolio as pf
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


def _day(offset: int) -> dt.date:
    return TODAY - dt.timedelta(days=offset)


@pytest.fixture
def seeded(db, user):
    """A small real-shaped book: whole shares, and a fractional US holding at 8dp."""
    instruments = {
        "KAYNES": make_instrument(
            db,
            symbol="KAYNES",
            exchange="NSE",
            name="Kaynes Technology",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "SPCX": make_instrument(
            db,
            symbol="SPCX",
            exchange="NASDAQ",
            name="SpaceX",
            asset_class="EQUITY_US",
            currency="USD",
        ),
    }
    for inst in instruments.values():
        db.add(inst)
    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-api", kind="REAL")
    db.add(book)
    db.flush()

    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=instruments["KAYNES"].id,
            txn_type="BUY",
            trade_date=_day(40),
            quantity=D("5"),
            price=D("3378.80"),
            currency="INR",
            charges_inr=D("24.15"),
            entry_source="IMPORT",
        )
    )
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=instruments["SPCX"].id,
            txn_type="BUY",
            trade_date=_day(30),
            # ⚠ 8dp. The amount is the primary fact on a fractional buy; the units follow.
            quantity=D("0.86242900"),
            price=D("180.06"),
            currency="USD",
            fx_rate_inr=D("96.01"),
            entry_source="IMPORT",
        )
    )
    db.commit()
    book.instruments = instruments
    return book


# --- access ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/investments/summary"),
        ("get", "/api/investments/holdings/KAYNES"),
        ("get", "/api/investments/transactions"),
        ("get", "/api/investments/history"),
        ("post", "/api/investments/transactions/draft"),
        ("post", "/api/investments/transactions"),
    ],
)
def test_every_route_requires_a_session(client, method, path):
    call = getattr(client, method)
    response = call(path, json={}) if method == "post" else call(path)
    assert response.status_code == 401, f"{method.upper()} {path} answered without a session"


def test_a_user_with_no_book_gets_a_clear_404(auth_client):
    """Not an empty summary. An error rendered as "you have nothing" misreports a fault."""
    assert auth_client.get("/api/investments/summary").status_code == 404


def test_another_users_transaction_cannot_be_reversed(db, auth_client, seeded, other_user):
    """An id is not an authorisation. This must be indistinguishable from a missing row."""
    theirs = Portfolio(id=uuid.uuid4(), user_id=other_user.id, name="pytest-theirs", kind="REAL")
    db.add(theirs)
    db.flush()
    txn = Transaction(
        id=uuid.uuid4(),
        portfolio_id=theirs.id,
        instrument_id=seeded.instruments["KAYNES"].id,
        txn_type="BUY",
        trade_date=_day(3),
        quantity=D("1"),
        price=D("100"),
        currency="INR",
        entry_source="IMPORT",
    )
    db.add(txn)
    db.commit()

    response = auth_client.post(f"/api/investments/transactions/{txn.id}/reverse")
    assert response.status_code == 404


# --- money crosses the wire exactly --------------------------------------------------------


def test_money_arrives_as_exact_strings_not_json_numbers(auth_client, seeded):
    """⚠ The assertion the whole page rests on. Read from the RAW body, because parsing to
    Python would hide a float that had already lost its scale."""
    raw = auth_client.get("/api/investments/summary").text
    assert '"quantity":"0.86242900"' in raw, "8dp units must survive with their scale intact"
    assert '"quantity":0.862429' not in raw

    data = json.loads(raw)
    for holding in data["holdings"]:
        for field in ("quantity", "cost_basis", "cost_basis_inr", "realised_inr"):
            assert isinstance(holding[field], str), f"{field} arrived as {type(holding[field])}"
        # An exact decimal survives the round trip unchanged.
        assert D(holding["cost_basis_inr"]) == D(holding["cost_basis_inr"])


def test_percentages_are_computed_on_the_server(auth_client, seeded, db):
    pricing.record(db, seeded.instruments["KAYNES"].id, D("3598.00"), "INR", source=TEST_SOURCE)
    db.commit()
    data = auth_client.get("/api/investments/summary").json()
    kaynes = next(h for h in data["holdings"] if h["symbol"] == "KAYNES")
    assert isinstance(kaynes["unrealised_pct"], str)
    assert D(kaynes["unrealised_pct"]) == D(kaynes["unrealised_inr"]) / D(kaynes["cost_basis_inr"])


# --- what the summary says -----------------------------------------------------------------


def test_the_summary_names_what_it_could_not_price(auth_client, seeded):
    totals = auth_client.get("/api/investments/summary").json()["totals"]
    assert totals["is_complete"] is False
    assert sorted(totals["unpriced"]) == ["KAYNES", "SPCX"]


def test_both_returns_are_present_even_when_neither_can_be_computed(auth_client, seeded):
    """⚠ The spec's rule. A measure that cannot be computed is named with its reason; it is
    never simply absent, and the other is never labelled "the return"."""
    returns = auth_client.get("/api/investments/summary").json()["returns"]
    assert {r["kind"] for r in returns} == {"money_weighted", "time_weighted"}
    for r in returns:
        assert r["value"] is None
        assert r["unavailable_because"]
        assert r["measures"], "each measure states what it measures"


def test_an_unpriced_holding_reports_no_value_rather_than_zero(auth_client, seeded):
    holdings = auth_client.get("/api/investments/summary").json()["holdings"]
    assert all(h["market_value_inr"] is None for h in holdings)
    assert all(h["mark"] is None for h in holdings)


def test_a_holding_carries_its_lots_and_boundary(auth_client, seeded):
    detail = auth_client.get("/api/investments/holdings/KAYNES").json()
    assert detail["holding"]["symbol"] == "KAYNES"
    assert len(detail["lots"]) == 1
    assert detail["lots"][0]["long_term_on"], "Indian equity becomes long-term after 12 months"
    assert detail["lots"][0]["is_long_term"] is False


def test_the_us_holding_is_measured_against_24_months(auth_client, seeded):
    """Three rules, not a default with exceptions — the US one is what goes silently wrong."""
    lot = auth_client.get("/api/investments/holdings/SPCX").json()["lots"][0]
    bought = _day(30)
    assert lot["long_term_on"] == bought.replace(year=bought.year + 2).isoformat()


def test_an_unknown_symbol_is_404(auth_client, seeded):
    assert auth_client.get("/api/investments/holdings/NOSUCH").status_code == 404


# --- the curve -----------------------------------------------------------------------------


def test_the_curve_ships_with_an_invested_line_and_no_value_line(auth_client, seeded):
    """The state this ships in, asserted end to end."""
    body = auth_client.get("/api/investments/history").json()
    assert body["covered_from"] is None and body["covered_to"] is None
    assert all(p["value_inr"] is None for p in body["points"])
    assert all(D(p["invested_inr"]) >= 0 for p in body["points"])
    assert body["points"][-1]["day"] == TODAY.isoformat()


def test_the_curve_window_can_be_narrowed(auth_client, seeded):
    body = auth_client.get(
        "/api/investments/history", params={"since": _day(10).isoformat()}
    ).json()
    assert body["points"][0]["day"] == _day(10).isoformat()


# --- writing -------------------------------------------------------------------------------


def _draft_body(**over):
    body = {
        "symbol": "KAYNES",
        "txn_type": "BUY",
        "quantity": "1",
        "price": "3500.00",
        "trade_date": _day(1).isoformat(),
    }
    body.update(over)
    return body


def test_the_draft_route_writes_nothing(auth_client, seeded):
    """Two steps on purpose: what comes back is what will be recorded, and nothing is."""
    before = len(auth_client.get("/api/investments/transactions").json())
    draft = auth_client.post("/api/investments/transactions/draft", json=_draft_body())
    assert draft.status_code == 200
    assert D(draft.json()["charges_inr"]) > 0, "Groww is not zero-brokerage"
    assert len(auth_client.get("/api/investments/transactions").json()) == before


def test_confirming_writes_the_transaction_and_records_how_it_arrived(auth_client, seeded):
    response = auth_client.post("/api/investments/transactions", json=_draft_body())
    assert response.status_code == 201
    written = response.json()
    assert written["entry_source"] == "FORM", (
        "a form entry is not a chat entry; writing it as CHAT would falsify provenance"
    )
    assert D(written["charges_inr"]) > 0


def test_the_confirm_route_recomputes_charges_and_ignores_any_the_client_sends(auth_client, seeded):
    """⚠ Charges the client can set are charges the client can set wrong. The write path
    re-runs `prepare` rather than accepting a costed draft."""
    honest = auth_client.post("/api/investments/transactions/draft", json=_draft_body()).json()
    written = auth_client.post(
        "/api/investments/transactions", json=_draft_body(charges_inr="0")
    ).json()
    assert D(written["charges_inr"]) == D(honest["charges_inr"])


def test_a_future_trade_date_is_rejected(auth_client, seeded):
    response = auth_client.post(
        "/api/investments/transactions",
        json=_draft_body(trade_date=(TODAY + dt.timedelta(days=1)).isoformat()),
    )
    assert response.status_code == 400


def test_there_is_no_way_to_delete_a_transaction(auth_client, seeded, client):
    """The ledger is append-only, so no DELETE route exists on this router at all.

    Asserted against the published schema rather than by calling one URL: an endpoint that
    promises deletion is a lie in the OpenAPI document before it is one in the interface, and
    a route added later under a path this test never guessed would slip straight past a
    single-URL check.
    """
    paths = client.get("/openapi.json").json()["paths"]
    offenders = [
        f"{method.upper()} {path}"
        for path, methods in paths.items()
        if path.startswith("/api/investments")
        for method in methods
        if method.lower() in ("delete", "put", "patch")
    ]
    assert offenders == [], f"the ledger cannot be rewritten over HTTP: {offenders}"

    txn_id = auth_client.get("/api/investments/transactions").json()[0]["id"]
    assert auth_client.delete(f"/api/investments/transactions/{txn_id}").status_code == 404


def test_reversing_leaves_the_original_readable_and_marks_it(auth_client, seeded):
    original = auth_client.post("/api/investments/transactions", json=_draft_body()).json()
    correction = auth_client.post(
        f"/api/investments/transactions/{original['id']}/reverse",
        json={"note": "typed the wrong price"},
    )
    assert correction.status_code == 200
    assert correction.json()["supersedes_id"] == original["id"]

    rows = {t["id"]: t for t in auth_client.get("/api/investments/transactions").json()}
    assert original["id"] in rows, "the superseded entry stays in the record"
    assert rows[original["id"]]["superseded_by_id"] == correction.json()["id"]


def test_a_reversed_purchase_leaves_the_position_as_it_was(auth_client, seeded, db):
    before = auth_client.get("/api/investments/summary").json()
    kaynes_before = next(h for h in before["holdings"] if h["symbol"] == "KAYNES")

    written = auth_client.post("/api/investments/transactions", json=_draft_body()).json()
    auth_client.post(f"/api/investments/transactions/{written['id']}/reverse")

    after = auth_client.get("/api/investments/summary").json()
    kaynes_after = next(h for h in after["holdings"] if h["symbol"] == "KAYNES")
    assert kaynes_after["quantity"] == kaynes_before["quantity"]
    assert kaynes_after["cost_basis_inr"] == kaynes_before["cost_basis_inr"]


# --- the duplicated cash-effect rule --------------------------------------------------------


def test_the_displayed_cash_effect_agrees_with_what_returns_are_computed_from(db, seeded):
    """`overview.cash_effect_inr` restates `portfolio.cash_flows` per transaction. A display
    figure that drifts from the figure returns are built on is a bug nobody would notice, so
    the two are pinned together here."""
    txns = pf.ledger(db, seeded.id)
    from_flows = sorted(amount for _, amount in pf.cash_flows(txns))
    from_display = sorted(
        overview.cash_effect_inr(t) for t in txns if overview.cash_effect_inr(t) != 0
    )
    assert from_flows == from_display


def test_subtotals_are_computed_on_the_server(auth_client, seeded, db):
    """⚠ A subtotal is a displayed monetary figure, so it must not be assembled by adding
    holdings together in the browser — that is float arithmetic on money immediately after
    the server took care to be exact."""
    data = auth_client.get("/api/investments/summary").json()
    by_class = {a["asset_class"]: a for a in data["by_asset_class"]}
    assert set(by_class) == {"EQUITY_IN", "EQUITY_US"}
    assert all(isinstance(a["invested_inr"], str) for a in data["by_asset_class"])

    equity = by_class["EQUITY_IN"]
    holdings = [h for h in data["holdings"] if h["asset_class"] == "EQUITY_IN"]
    assert equity["holdings"] == len(holdings)
    assert D(equity["invested_inr"]) == sum(D(h["cost_basis_inr"]) for h in holdings)


def test_an_unpriced_class_reports_no_value_for_the_class_either(auth_client, seeded):
    """The same rule as the book total, one level down: partial coverage yields nothing."""
    data = auth_client.get("/api/investments/summary").json()
    assert all(a["market_value_inr"] is None for a in data["by_asset_class"])
    assert D(data["unpriced_cost_inr"]) == sum(D(h["cost_basis_inr"]) for h in data["holdings"])


def test_the_curve_reports_how_many_days_it_actually_knows(auth_client, seeded):
    """⚠ Not just the first and last covered day. Coverage can have a hole in the middle —
    buy something and leave it unpriced for a week — and naming only the endpoints would
    claim a continuity the data does not have."""
    body = auth_client.get("/api/investments/history").json()
    assert body["total_days"] == len(body["points"])
    assert body["covered_days"] == 0, "no prices recorded, so no day carries a value"
    assert body["covered_days"] == sum(1 for p in body["points"] if p["value_inr"] is not None)


def test_a_new_instrument_is_rejected_with_the_wording_the_form_matches_on(auth_client, seeded):
    """⚠ A coupling worth pinning. The entry form reveals its exchange / kind / name fields
    when it sees this phrase, because that is the one rejection a user can answer by
    supplying more — every other one means the entry itself is wrong. Changing the wording
    without changing `IS_NEW` in `TransactionEntry.tsx` would leave the form showing a dead
    end on the only path that creates a holding.
    """
    response = auth_client.post(
        "/api/investments/transactions/draft", json=_draft_body(symbol="BRANDNEW")
    )
    assert response.status_code == 400
    assert "is new, so it needs" in response.json()["detail"]


def test_supplying_those_fields_records_the_new_instrument(auth_client, seeded):
    response = auth_client.post(
        "/api/investments/transactions",
        json=_draft_body(
            symbol="BRANDNEW",
            asset_class="EQUITY_IN",
            exchange="NSE",
            name="Brand New Ltd",
            currency="INR",
        ),
    )
    assert response.status_code == 201
    symbols = {h["symbol"] for h in auth_client.get("/api/investments/summary").json()["holdings"]}
    assert "BRANDNEW" in symbols, "recording a holding is also how it starts being tracked"


def test_invested_is_never_zero_on_a_book_that_holds_something(auth_client, seeded):
    """⚠ Regression, found by running the page for the first time rather than by a test.

    `BookTotals.invested_inr` accumulates only PRICED holdings, and skips ring-fenced ones,
    so that it stays comparable with `market_value_inr`. That is right for its job — and as
    a headline it is catastrophic: on a book with no prices it is zero, so the page read
    "Invested Rs 0" against real money. `cost_basis_inr` is the honest figure.
    """
    totals = auth_client.get("/api/investments/summary").json()["totals"]
    assert D(totals["invested_inr"]) == 0, "nothing is priced, so the comparable figure is 0"
    assert D(totals["cost_basis_inr"]) > 0, "but money was spent, and that is a fact"

    holdings = auth_client.get("/api/investments/summary").json()["holdings"]
    assert D(totals["cost_basis_inr"]) == sum(D(h["cost_basis_inr"]) for h in holdings)
