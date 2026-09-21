"""Looking backwards, on a schedule.

The artefact actually worth reading. The daily notifications are operational; this is where
the thinking accumulates — and where the system is asked, in public and on a timetable,
whether any of it is working.

The properties under test are mostly about **refusing to flatter**: withholding a measure that
has no sample behind it, naming the queue nobody has cleared, reporting unspent budget without
apology, and never rewriting a review once it is written.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import (
    InvalidationTrigger,
    ListedCompany,
    Portfolio,
    PriceObservation,
    Proposal,
    Review,
    Transaction,
)
from app.services.investments import books, framework_data, frameworks, reading, reviews
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def version(db):
    row = frameworks.install(db, framework_data.spec(), approved=True)
    db.commit()
    return row


@pytest.fixture
def book(db, user):
    real = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(real)
    db.flush()
    books.ensure(db, user.id, "MIRROR")
    db.commit()
    return real


@pytest.fixture
def company(db):
    inst = make_instrument(
        db,
        symbol="REVCO",
        exchange="NSE",
        name="Revco Industries",
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
            price=D(400),
            currency="INR",
        )
    )
    db.commit()
    return inst


def _proposal(db, user, company, version, *, status="PENDING", blocked_by=None):
    mirror = books.get(db, user.id, "MIRROR")
    row = Proposal(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        portfolio_id=mirror.id,
        instrument_id=company.id,
        action="INITIATE",
        target_amount_inr=D(8000),
        horizon_days=270,
        thesis="a thesis about the grid",
        confidence=D("0.8"),
        framework_version_id=version.id,
        price_snapshot={"price": "400"},
        input_refs={},
        gate_results={},
        status=status,
        blocked_by=blocked_by,
    )
    db.add(row)
    db.commit()
    return row


# --- the window ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "end", "start"),
    [
        ("WEEKLY", dt.date(2026, 9, 19), dt.date(2026, 9, 13)),
        ("MONTHLY", dt.date(2026, 9, 30), dt.date(2026, 9, 1)),
        ("QUARTERLY", dt.date(2026, 9, 30), dt.date(2026, 7, 1)),
        ("QUARTERLY", dt.date(2026, 2, 14), dt.date(2026, 1, 1)),
    ],
)
def test_the_period_is_what_it_claims(kind, end, start):
    assert reviews.period_for(kind, end) == (start, end)


# --- what it reports -----------------------------------------------------------------------


def test_a_decision_is_reported_with_the_reason_in_your_own_words(db, user, book, company, version):
    """⚠ The reasons are carried verbatim. They are the data that eventually says what kinds
    of suggestion keep being refused, and a count without them says nothing."""
    from app.services.investments import proposals as prop_service

    row = _proposal(db, user, company, version)
    prop_service.decide(db, row, user_id=user.id, outcome="REJECT", reason="already too much grid")
    db.commit()

    content, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert content["decisions"]["counts"] == {"REJECT": 1}
    assert content["decisions"]["decisions"][0]["reason"] == "already too much grid"


def test_what_the_rules_refused_is_reported_too(db, user, book, company, version):
    """⚠ The rails are measured. A refusal nobody is shown is a rule nobody can ever ask
    whether it was protecting or merely obstructing."""
    _proposal(db, user, company, version, status="BLOCKED", blocked_by="G2_quadrant")

    content, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert content["blocked"] == [{"action": "INITIATE", "blocked_by": "G2_quadrant"}]


def test_a_condition_close_to_firing_is_reported_before_it_fires(db, user, book, company, version):
    """⚠ The most useful thing a weekly review carries, and invisible to anything that reports
    only firings. A condition at 97% of its threshold is a week's warning."""
    proposal = _proposal(db, user, company, version)
    db.add(
        InvalidationTrigger(
            id=uuid.uuid4(),
            proposal_id=proposal.id,
            instrument_id=company.id,
            description="the price falls below 390",
            metric_key="price",
            comparator="LT",
            threshold=D(390),
            unit="inr",
            window_until=TODAY + dt.timedelta(days=60),
            status="ARMED",
        )
    )
    db.commit()

    content, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert len(content["approaching"]) == 1
    assert content["approaching"][0]["metric"] == "price"


def test_a_condition_far_from_firing_is_not_noise_in_the_review(db, user, book, company, version):
    proposal = _proposal(db, user, company, version)
    db.add(
        InvalidationTrigger(
            id=uuid.uuid4(),
            proposal_id=proposal.id,
            instrument_id=company.id,
            description="the price falls below 100",
            metric_key="price",
            comparator="LT",
            threshold=D(100),
            unit="inr",
            window_until=TODAY + dt.timedelta(days=60),
            status="ARMED",
        )
    )
    db.commit()

    assert reviews.assemble(db, user.id, "WEEKLY")[0]["approaching"] == []


def test_a_queue_nobody_has_cleared_is_named_not_counted(db, user, book, monkeypatch):
    """⚠ "Three have been waiting a month" prompts nothing. Naming them is what turns a
    statistic into a decision."""
    db.add(
        ListedCompany(
            id=uuid.uuid4(),
            symbol="STALECO",
            exchange="NSE",
            name="Staleco Industries",
            series="EQ",
            refreshed_at=dt.datetime.now(dt.UTC),
        )
    )
    db.commit()
    reading.drop(db, text="Staleco Industries is interesting")
    db.commit()

    candidate = db.execute(sa.select(sa.text("id, first_seen_at FROM candidates"))).first()
    db.execute(
        sa.text("UPDATE candidates SET first_seen_at = :when"),
        {"when": dt.datetime.now(dt.UTC) - dt.timedelta(days=40)},
    )
    db.commit()
    assert candidate is not None

    content, headline, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert content["queue"]["waiting"] == 1
    assert content["queue"]["stale"][0]["symbol"] == "STALECO"
    assert "waiting to be looked at" in headline


def test_unspent_budget_is_reported_without_apology(db, user, book):
    """⚠ The budget is a ceiling, not a target. A review that framed unspent money as a
    shortfall would be arguing for activity — the one bias this design is built against."""
    content, headline, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert content["budget"]["unspent_inr"] == content["budget"]["budget_inr"]
    assert "unspent" in headline
    assert "shortfall" not in headline.lower()
    assert "missed" not in headline.lower()


def test_money_in_a_review_never_becomes_a_float(db, user, book):
    """⚠ Stored as text. `json` would turn a Decimal into a float on the way in, and 4.1
    recorded as 4.0999999999999996 in a row nobody can correct is exactly what this module
    spends its effort avoiding."""
    row = reviews.write(db, user, "WEEKLY")
    db.commit()

    assert isinstance(row.content["budget"]["budget_inr"], str)
    assert isinstance(row.content["period"]["start"], str)


# --- what it refuses to say ---------------------------------------------------------------------


def test_every_measure_withholds_itself_until_it_has_a_sample(db, user, book):
    """⚠ A hit rate over six reads exactly like one over six hundred. "Not yet" is the honest
    state for most of the first year, and a review showing both the same way would teach its
    reader to trust numbers that mean nothing."""
    content, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert content["measures"]
    for measure in content["measures"]:
        assert measure["value"] is None, measure["name"]
        # ⚠ And it says WHY in words, not as a bare null. A measure that renders as blank is
        # read as zero by anyone scanning; one that says "not yet, and here is what is
        # missing" cannot be.
        assert measure["detail"].strip()


def test_source_attribution_is_monthly_and_not_weekly(db, user, book):
    """⚠ Over seven days it is noise wearing a number, and showing it weekly would train its
    reader to read noise."""
    weekly, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")
    monthly, _, _, _ = reviews.assemble(db, user.id, "MONTHLY")

    assert "sources" not in weekly
    assert "sources" in monthly


def test_the_headline_leads_with_what_needs_doing(db, user, book):
    """⚠ Not with the week's return. A review whose first line is a number invites reading
    only that number, and this early the numbers mean least."""
    _, headline, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    assert headline.startswith("Weekly review: no decisions")


# --- writing it once ------------------------------------------------------------------------------


def test_a_period_gets_exactly_one_review(db, user, book):
    """⚠ Two copies of one review will eventually disagree, and neither would be wrong on its
    face. A catch-up run after a restart must leave the first alone."""
    first = reviews.write(db, user, "WEEKLY")
    db.commit()
    second = reviews.write(db, user, "WEEKLY")
    db.commit()

    assert first is not None
    assert second is None
    assert db.execute(sa.select(sa.func.count()).select_from(Review)).scalar_one() == 1


def test_a_review_cannot_be_rewritten(db, user, book):
    """⚠ It states what was true at a moment. Regenerating March's review in June would show a
    position that recovered as never having fallen, and a prediction that failed as never
    having been made."""
    row = reviews.write(db, user, "WEEKLY")
    db.commit()

    row.headline = "a much better week actually"
    with pytest.raises(sa.exc.DatabaseError):
        db.flush()
    db.rollback()


def test_a_review_cannot_be_deleted(db, user, book):
    reviews.write(db, user, "WEEKLY")
    db.commit()

    with pytest.raises(sa.exc.DatabaseError):
        db.execute(sa.delete(Review))
    db.rollback()


def test_different_kinds_coexist_for_the_same_day(db, user, book):
    """A month end is also a week end, and the two reviews answer different questions."""
    end = dt.date(2026, 9, 30)
    assert reviews.write(db, user, "WEEKLY", end=end) is not None
    assert reviews.write(db, user, "MONTHLY", end=end) is not None
    db.commit()

    assert db.execute(sa.select(sa.func.count()).select_from(Review)).scalar_one() == 2


# --- through the job ----------------------------------------------------------------------------


def test_the_weekly_job_writes_one_and_says_so(db, user, book):
    from app.jobs import reviews as review_jobs

    result = review_jobs.investments_weekly_review(db, user)

    assert result.notify is not None
    assert "weekly review" in result.notify.title
    assert result.notify.body.startswith("Weekly review:")


def test_running_the_weekly_job_twice_delivers_once(db, user, book):
    """⚠ Silent the second time, not an error — the same idempotence every scheduled thing
    here has."""
    from app.jobs import reviews as review_jobs

    first = review_jobs.investments_weekly_review(db, user)
    second = review_jobs.investments_weekly_review(db, user)

    assert first.notify is not None
    assert second.notify is None
    assert second.silent


def test_no_review_job_calls_a_model(db):
    """⚠ A review is almost entirely numbers, and everywhere else here a model is forbidden
    from producing one. A summary paragraph would be the single place a figure could be
    restated wrongly with nothing to check it against."""
    from app.jobs import all_jobs

    for entry in all_jobs():
        if "review" in entry.name:
            assert entry.uses_ai is False, entry.name


# --- over the wire --------------------------------------------------------------------------------


def test_the_reviews_route_returns_them_newest_first(auth_client, db, user, book):
    reviews.write(db, user, "WEEKLY", end=TODAY - dt.timedelta(days=7))
    reviews.write(db, user, "WEEKLY", end=TODAY)
    db.commit()

    body = auth_client.get("/api/investments/reviews").json()["reviews"]

    assert len(body) == 2
    assert body[0]["period_end"] > body[1]["period_end"]
    assert body[0]["content"]["kind"] == "WEEKLY"


def test_another_users_review_is_not_returned(auth_client, db, user, other_user, book):
    other_book = Portfolio(id=uuid.uuid4(), user_id=other_user.id, name="theirs", kind="REAL")
    db.add(other_book)
    books.ensure(db, other_user.id, "MIRROR")
    db.commit()
    reviews.write(db, other_user, "WEEKLY")
    db.commit()

    assert auth_client.get("/api/investments/reviews").json()["reviews"] == []


def test_a_transaction_in_the_window_does_not_break_assembly(db, user, book, company):
    """The books section values everything at once; a real holding must not upset it."""
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=company.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=3),
            quantity=D(10),
            price=D(380),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()

    content, _, _, _ = reviews.assemble(db, user.id, "WEEKLY")

    real = next(line for line in content["books"]["lines"] if line["kind"] == "REAL")
    assert real["positions"] == 1
    assert "REVCO" in content["books"]["unaided"]
