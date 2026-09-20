"""The books, and why none of them is a subset of another.

Three categories exist, and a single merged ledger would silently discard the third:

  * Acero proposed → you approved → you did it
  * Acero proposed → you approved → you did something else
  * **you bought something Acero never proposed**

Most of what follows checks that the separation holds under the operations that would most
easily collapse it — approving a suggestion, seeding a book, valuing them all at once.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import Portfolio, PriceObservation, Proposal, Transaction
from app.services.investments import books, framework_data, frameworks, proposals
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
def real(db, user):
    """A real book holding one company, bought a month ago."""
    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(book)
    db.flush()
    inst = make_instrument(
        db,
        symbol="BOOKHELD",
        exchange="NSE",
        name="Already Held Industries",
        asset_class="EQUITY_IN",
        currency="INR",
        sector="EMS_ELECTRONICS",
    )
    db.add(inst)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=inst.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=30),
            quantity=D(10),
            price=D(100),
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
            price=D(150),
            currency="INR",
        )
    )
    db.commit()
    book.instrument = inst
    return book


def _suggested(db, user, version, symbol="BOOKNEW"):
    """A suggestion that survived the rules, ready to be decided."""
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
    db.add(
        PriceObservation(
            instrument_id=inst.id,
            observed_at=dt.datetime.now(dt.UTC),
            source=TEST_SOURCE,
            kind="LAST",
            price=D(200),
            currency="INR",
        )
    )
    row = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=books.ensure(db, user.id, "MIRROR").id,
        instrument_id=inst.id,
        action="INITIATE",
        target_amount_inr=D(5000),
        target_qty=D(25),
        horizon_days=270,
        thesis="a thesis",
        confidence=D("0.8"),
        framework_version_id=version.id,
        price_snapshot={"price": "200"},
        input_refs={},
        gate_results={},
        status="PENDING",
    )
    db.add(row)
    db.commit()
    return row, inst


# --- seeding ------------------------------------------------------------------------------


def test_the_mirror_starts_as_a_copy_of_what_is_really_held(db, user, real):
    """It means "what would my portfolio look like if I had followed Acero FROM HERE", so it
    takes a snapshot of where here was."""
    copied = books.seed_mirror(db, user.id)
    db.commit()

    assert copied == 1
    mirror = books.get(db, user.id, "MIRROR")
    line = books.compare(db, user.id).by_kind("MIRROR")
    assert line.invested_inr == D(1000)
    assert line.value_inr == D(1500)
    assert mirror.id != real.id


def test_seeding_twice_copies_nothing_the_second_time(db, user, real):
    """⚠ Re-seeding would change what the comparison measures — from "did following Acero
    help" to "does Acero agree with what I did anyway"."""
    assert books.seed_mirror(db, user.id) == 1
    db.commit()
    assert books.seed_mirror(db, user.id) == 0
    db.commit()


def test_the_clean_book_starts_empty_and_stays_that_way_until_something_is_approved(db, user, real):
    """⚠ It answers a different question from the mirror: what has the machine itself
    produced, rather than what would my portfolio look like if I had followed it."""
    books.seed_mirror(db, user.id)
    books.ensure(db, user.id, "AI_CLEAN")
    db.commit()

    clean = books.compare(db, user.id).by_kind("AI_CLEAN")
    assert clean.positions == 0
    assert clean.invested_inr == D(0)


# --- approving ------------------------------------------------------------------------------


def test_approving_fills_both_paper_books_and_neither_is_the_other(db, user, real, version):
    """⚠ Both, and they are not duplicates. One started from the real holdings and one from
    nothing, so after the same approval they hold different totals."""
    books.seed_mirror(db, user.id)
    db.commit()
    proposal, inst = _suggested(db, user, version)

    proposals.decide(db, proposal, user_id=user.id, outcome="APPROVE", reason="agreed")
    db.commit()

    comparison = books.compare(db, user.id)
    mirror = comparison.by_kind("MIRROR")
    clean = comparison.by_kind("AI_CLEAN")

    assert mirror.positions == 2, "the opening position plus the new one"
    assert clean.positions == 1, "only what the machine produced"
    assert mirror.invested_inr > clean.invested_inr
    assert inst.symbol == "BOOKNEW"


def test_approving_never_touches_the_real_book(db, user, real, version):
    """⚠ What the user does in life is their word. The gap between the two books is one of
    the most interesting numbers this produces, and writing to the real one destroys it."""
    before = books.compare(db, user.id).by_kind("REAL")
    proposal, _ = _suggested(db, user, version)

    proposals.decide(db, proposal, user_id=user.id, outcome="APPROVE", reason="yes")
    db.commit()

    after = books.compare(db, user.id).by_kind("REAL")
    assert after.positions == before.positions
    assert after.invested_inr == before.invested_inr


def test_a_paper_fill_pays_modelled_charges(db, user, real, version):
    """⚠ A paper book that ignores transaction taxes and fees flatters itself by a few tenths
    of a percent on every round trip — against a real book that pays them."""
    proposal, inst = _suggested(db, user, version)
    proposals.decide(db, proposal, user_id=user.id, outcome="APPROVE", reason="yes")
    db.commit()

    clean = books.get(db, user.id, "AI_CLEAN")
    txn = db.execute(
        sa.select(Transaction).where(Transaction.portfolio_id == clean.id)
    ).scalar_one()
    assert txn.charges_inr > 0
    assert txn.entry_source == "PROPOSAL_APPROVAL"
    assert txn.price == D(200), "filled at the price frozen onto the suggestion"


def test_rejecting_fills_no_paper_book(db, user, real, version):
    books.ensure(db, user.id, "AI_CLEAN")
    proposal, _ = _suggested(db, user, version)
    proposals.decide(db, proposal, user_id=user.id, outcome="REJECT", reason="no")
    db.commit()

    assert books.compare(db, user.id).by_kind("AI_CLEAN").positions == 0


# --- the benchmark and the what-ifs ------------------------------------------------------------


def test_everything_it_ever_suggested_is_weighted_equally(db, user, real, version):
    """⚠ Equal weighting is the point. Sizing by conviction would fold the sizing judgement
    back into a benchmark that exists to ask whether the IDEAS were any good."""
    _suggested(db, user, version, symbol="BOOKA")
    _suggested(db, user, version, symbol="BOOKB")
    db.commit()

    line = books.compare(db, user.id).by_kind("PROPOSED_ALL")
    assert line.positions == 2
    assert line.invested_inr == books.BENCHMARK_TICKET * 2


def test_a_blocked_suggestion_is_not_in_the_benchmark(db, user, real, version):
    """⚠ It was never proposed — the rules stopped it before it reached anyone. Including it
    would measure the rules, which the shadow book already does separately."""
    proposal, _ = _suggested(db, user, version, symbol="BOOKBLOCK")
    blocked = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=proposal.portfolio_id,
        instrument_id=proposal.instrument_id,
        action="INITIATE",
        horizon_days=270,
        thesis="blocked",
        confidence=D("0.8"),
        framework_version_id=version.id,
        price_snapshot={"price": "200"},
        input_refs={},
        gate_results={},
        status="BLOCKED",
        blocked_by="G2_quadrant",
    )
    db.add(blocked)
    db.commit()

    assert books.compare(db, user.id).by_kind("PROPOSED_ALL").positions == 1


def test_what_the_rules_blocked_is_valued_like_everything_else(db, user, real, version):
    """The only way to ever ask whether the rails protect or merely obstruct."""
    proposal, inst = _suggested(db, user, version, symbol="BOOKGATE")
    entry = proposals._shadow_from_proposal(db, user.id, proposal, "GATE_BLOCKED")
    db.commit()
    assert entry is not None

    line = books.compare(db, user.id).by_kind("SHADOW_GATE")
    assert line.positions == 1
    assert line.invested_inr == D(200) * D(25)
    assert line.value_inr == D(200) * D(25), "entry price is today's price here"


# --- the third category ---------------------------------------------------------------------------


def test_what_you_bought_unaided_is_reported(db, user, real, version):
    """⚠ The direct read on your own judgement against the machine's, and the one category a
    single merged ledger would silently discard."""
    books.seed_mirror(db, user.id)
    db.commit()

    assert books.unaided(db, user.id) == ["BOOKHELD"]


def test_a_company_the_system_suggested_is_not_counted_as_unaided(db, user, real, version):
    books.seed_mirror(db, user.id)
    proposal, inst = _suggested(db, user, version, symbol="BOOKSUGG")
    proposals.decide(db, proposal, user_id=user.id, outcome="APPROVE", reason="yes")
    db.commit()

    # It is in the paper books, not the real one, so it is not a real holding at all.
    assert "BOOKSUGG" not in books.unaided(db, user.id)


# --- valuing --------------------------------------------------------------------------------------


def test_a_book_with_an_unpriced_holding_reports_no_total(db, user, real):
    """⚠ A total assembled from partial coverage steps whenever coverage changes, and a reader
    cannot tell that apart from the book actually moving."""
    unpriced = make_instrument(
        db,
        symbol="BOOKDARK",
        exchange="NSE",
        name="Unpriced Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(unpriced)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=real.id,
            instrument_id=unpriced.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=5),
            quantity=D(5),
            price=D(50),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()

    line = books.compare(db, user.id).by_kind("REAL")
    assert line.value_inr is None
    assert not line.is_complete
    assert line.invested_inr > 0, "what was paid is still exact"


def test_the_comparison_refuses_to_be_read_until_both_sides_are_priced(db, user, real):
    """Comparing a complete total against a partial one is worse than not comparing."""
    books.ensure(db, user.id, "AI_CLEAN")
    db.commit()
    assert books.compare(db, user.id).readable


def test_every_book_carries_what_it_is_for(db, user, real):
    """A reader who cannot tell the books apart will average them in their head."""
    for line in books.compare(db, user.id).lines:
        assert line.name and line.purpose, line.kind


# --- over the wire -----------------------------------------------------------------------


def test_the_books_route_seeds_and_returns_everything(auth_client, db, user, real):
    body = auth_client.get("/api/investments/books").json()
    kinds = {line["kind"] for line in body["lines"]}

    assert {"REAL", "MIRROR", "AI_CLEAN", "PROPOSED_ALL"} <= kinds
    assert body["unaided"] == ["BOOKHELD"]
    # ⚠ Money crosses as strings, like everything else in this module.
    assert all(isinstance(line["invested_inr"], str) for line in body["lines"])
