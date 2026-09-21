"""Turning a name somebody mentioned into something you can decide about.

Two properties are under test throughout, and both are guards rather than features:

**The model may place a company, and may not invent a place.** Which bottleneck a business
solves is a judgement about what the business *is*, so a model reads it — but the answer is
matched back against the framework's own ids, and anything unrecognised becomes no mapping.
A model free to name a bottleneck is free to invent a reason any company is nationally
strategic, and that reason reads exactly like a real one.

**A candidate gets no shortcuts.** It would be easy to score a company nobody owns more
loosely — fewer years, a guessed sector, a default multiple — and every one of those would
make a new idea look better than an existing holding purely because less was known about it.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import AbMapping, Candidate, Instrument, ListedCompany, PriceObservation
from app.services.investments import candidates, deduce, framework_data, frameworks, reading
from app.services.marketdata import feed
from tests.conftest import TEST_SOURCE

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    row = frameworks.install(db, spec, approved=True)
    db.commit()
    return row


@pytest.fixture
def exchange_list(db):
    rows = {}
    for symbol, name in [
        ("VOLTAMP", "Voltamp Transformers Limited"),
        ("NESTLEIND", "Nestle India Limited"),
    ]:
        row = ListedCompany(
            id=uuid.uuid4(),
            symbol=symbol,
            exchange="NSE",
            name=name,
            series="EQ",
            isin=f"INE{symbol[:6]}01011",
            refreshed_at=NOW,
        )
        db.add(row)
        rows[symbol] = row
    db.flush()
    db.commit()
    return rows


@pytest.fixture
def queued(db, exchange_list):
    """One candidate in the queue, the way a drop would leave it."""
    reading.drop(db, text="Voltamp Transformers is the quality play in the grid theme")
    db.commit()
    return db.execute(sa.select(Candidate)).scalar_one()


@pytest.fixture
def no_network(monkeypatch):
    """Filings and prices are exercised elsewhere; here they must not reach the exchange."""
    monkeypatch.setattr(candidates, "read_filings", lambda db, i, r, c=None: r)
    monkeypatch.setattr(candidates, "price_once", lambda db, i, r, c=None: r)


def _deduces(monkeypatch, bottleneck_id, confidence=0.9, why="it makes transformers"):
    monkeypatch.setattr(
        deduce,
        "bottleneck_for",
        lambda name, about, spec: deduce.Deduction(bottleneck_id, confidence, why),
    )


# --- placing a company ----------------------------------------------------------------------


def test_a_candidate_is_placed_in_the_framework(db, queued, spec, version, monkeypatch, no_network):
    _deduces(monkeypatch, "B1.1")

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert result.bottleneck_id == "B1.1"
    assert queued.proposed_bottleneck == "B1.1"
    assert queued.status == "ANALYSING"


def test_the_placement_is_a_proposal_and_scores_nothing_yet(
    db, queued, spec, version, monkeypatch, no_network
):
    """⚠ The guard against a machine talking itself into believing a random small-cap is
    nationally strategic — and it applies to a company the model just met exactly as it
    applies to one from Narendra's own notes."""
    _deduces(monkeypatch, "B1.1")

    candidates.analyse(db, queued, spec, version.id)
    db.commit()

    mapping = db.execute(sa.select(AbMapping)).scalar_one()
    assert mapping.approved_at is None
    assert frameworks.ab_score(mapping, spec).total == 0


def test_a_bottleneck_the_framework_does_not_know_is_refused(db, spec):
    """⚠ The only thing standing between "the model reads a description" and "the model
    invents a reason a company is nationally strategic"."""

    async def _invents(name, about, spec):
        return {"id": "B99.9", "confidence": 1.0, "why": "I made this up"}

    import app.services.investments.deduce as d

    original = d._ask
    d._ask = _invents
    try:
        result = d.bottleneck_for("Anything Limited", "-", spec)
    finally:
        d._ask = original

    assert result.bottleneck_id is None
    assert not result.is_usable
    assert "not in the framework" in result.why


def test_a_company_outside_the_framework_is_left_unmapped(
    db, queued, spec, version, monkeypatch, no_network
):
    """⚠ "NONE" is a real and common answer. Most listed companies are ordinary businesses
    this framework is not about, and forcing a fit is how a random small-cap becomes
    nationally strategic."""
    _deduces(monkeypatch, None, 0.9, "a packaged foods business")

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert result.bottleneck_id is None
    assert queued.proposed_bottleneck is None
    assert db.execute(sa.select(sa.func.count()).select_from(AbMapping)).scalar_one() == 0


def test_a_low_confidence_placement_is_not_proposed(
    db, queued, spec, version, monkeypatch, no_network
):
    """⚠ Unmapped is honest: the framework says "I do not know where this sits". A guess
    recorded as a proposal would be indistinguishable from a confident reading."""
    _deduces(monkeypatch, "B1.1", 0.2)

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert result.bottleneck_id is None
    assert db.execute(sa.select(sa.func.count()).select_from(AbMapping)).scalar_one() == 0


def test_an_unreachable_model_leaves_it_unmapped_rather_than_failing(db, spec):
    """A provider outage must not lose the candidate."""

    async def _down(name, about, spec):
        raise RuntimeError("provider down")

    import app.services.investments.deduce as d

    original = d._ask
    d._ask = _down
    try:
        result = d.bottleneck_for("Anything Limited", "-", spec)
    finally:
        d._ask = original

    assert result.bottleneck_id is None
    assert "could not be reached" in result.why


def test_the_placement_rests_on_what_sources_actually_said(db, queued, spec, version, monkeypatch):
    """⚠ The words, never a summary of them. A paraphrase of evidence is not evidence — if the
    mapping later looks wrong, what produced it has to still be there to check."""
    seen = {}

    def _capture(name, about, spec):
        seen["about"] = about
        return deduce.Deduction("B1.1", 0.9, "transformers")

    monkeypatch.setattr(deduce, "bottleneck_for", _capture)
    monkeypatch.setattr(candidates, "read_filings", lambda db, i, r, c=None: r)
    monkeypatch.setattr(candidates, "price_once", lambda db, i, r, c=None: r)

    candidates.analyse(db, queued, spec, version.id)

    assert "quality play in the grid theme" in seen["about"]


# --- what analysis costs -----------------------------------------------------------------------


def test_analysing_does_not_start_following(db, queued, spec, version, monkeypatch, no_network):
    """⚠ Analysis reads filings once and fetches one price; following joins the daily price
    loop for as long as the company is kept. The first costs a handful of requests and the
    second costs them every day, which is why they are separate acts."""
    _deduces(monkeypatch, "B1.1")

    candidates.analyse(db, queued, spec, version.id)
    db.commit()

    instrument = db.get(Instrument, queued.instrument_id)
    assert instrument is not None
    assert instrument.is_tracked is False


def test_promoting_is_what_starts_the_meter(db, queued, spec, version, monkeypatch, no_network):
    _deduces(monkeypatch, "B1.1")
    candidates.analyse(db, queued, spec, version.id)
    db.commit()

    reading.promote(db, queued)
    db.commit()

    assert db.get(Instrument, queued.instrument_id).is_tracked is True
    assert queued.status == "PROMOTED"


def test_the_identity_carries_the_exchanges_own_isin(db, queued, exchange_list):
    instrument = reading.identity_for(db, queued)
    db.commit()

    assert instrument.isin == exchange_list["VOLTAMP"].isin
    assert instrument.asset_class == "EQUITY_IN"


def test_only_a_few_candidates_are_analysed_per_run(db, exchange_list, spec, version, monkeypatch):
    """⚠ Each costs a model call and several filing fetches. A queue that suddenly gained
    forty names would otherwise spend an evening's whole budget on companies nobody has
    looked at."""
    for n in range(8):
        db.add(
            ListedCompany(
                id=uuid.uuid4(),
                symbol=f"BULK{n}",
                exchange="NSE",
                name=f"Bulkington Number {n} Industries",
                series="EQ",
                refreshed_at=NOW,
            )
        )
    db.commit()
    for n in range(8):
        reading.drop(db, text=f"Bulkington Number {n} Industries is interesting")
    db.commit()

    assert len(candidates.pending(db)) == candidates.MAX_PER_RUN


def test_the_best_sourced_candidate_is_analysed_first(db, exchange_list, monkeypatch):
    """A filing-grade lead outranks a mention on a channel, whatever order they arrived in."""
    reading.drop(db, text="Nestle India is interesting")
    db.commit()
    monkeypatch.setattr(
        "app.services.marketdata.webpage.fetch",
        lambda url, c=None: __import__("app.services.marketdata.webpage", fromlist=["Page"]).Page(
            url="https://www.nseindia.com/x",
            title="filing",
            text="Voltamp Transformers Limited has informed the Exchange",
            is_thin=False,
        ),
    )
    reading.drop(db, url="https://www.nseindia.com/x")
    db.commit()

    first = candidates.pending(db)[0]
    assert db.get(ListedCompany, first.listed_company_id).symbol == "VOLTAMP"


# --- scoring gets no shortcuts -------------------------------------------------------------------


def test_a_candidate_with_no_filings_scores_unknown_not_badly(
    db, queued, spec, version, monkeypatch
):
    """⚠ The rule the whole module rests on. A company unscored because nothing was read must
    never be indistinguishable from one that was read and found wanting."""
    _deduces(monkeypatch, "B1.1")
    monkeypatch.setattr(candidates, "read_filings", lambda db, i, r, c=None: r)
    monkeypatch.setattr(candidates, "price_once", lambda db, i, r, c=None: r)

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert result.quality_earned == 0
    assert result.quality_available == 0, (
        "nothing was available to score, which is not a zero score"
    )
    assert not result.is_scoreable
    assert any("too little filed data" in note for note in result.notes)


def test_a_missing_price_is_stated_rather_than_assumed(db, queued, spec, version, monkeypatch):
    _deduces(monkeypatch, "B1.1")
    monkeypatch.setattr(candidates, "read_filings", lambda db, i, r, c=None: r)
    monkeypatch.setattr(feed, "close_for", lambda db, i, c=None, **kw: None)

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert result.price is None
    assert any("no price" in note for note in result.notes)


def test_one_price_is_fetched_not_a_history(db, queued, spec, version, monkeypatch):
    """⚠ A candidate needs to be comparable with a defensible multiple today; it does not need
    a curve, and a year of closes for every name anyone mentions is the spend this avoids."""
    _deduces(monkeypatch, "B1.1")
    monkeypatch.setattr(candidates, "read_filings", lambda db, i, r, c=None: r)

    calls = []

    def _one(db_, instrument, c=None, **kw):
        calls.append(instrument.symbol)
        db_.add(
            PriceObservation(
                instrument_id=instrument.id,
                observed_at=dt.datetime.now(dt.UTC),
                source=TEST_SOURCE,
                kind="CLOSE",
                price=D(10879),
                currency="INR",
            )
        )
        db_.flush()
        return D(10879)

    monkeypatch.setattr(feed, "close_for", _one)

    result = candidates.analyse(db, queued, spec, version.id)
    db.commit()

    assert calls == ["VOLTAMP"]
    assert result.price == D(10879)


def test_one_bad_candidate_does_not_end_the_round(db, exchange_list, spec, version, monkeypatch):
    reading.drop(db, text="Voltamp Transformers looks good")
    reading.drop(db, text="Nestle India looks good")
    db.commit()

    calls = {"n": 0}

    def _explodes(db_, candidate, spec_, version_id, c=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return candidates.Analysis(symbol="OK", name="OK")

    monkeypatch.setattr(candidates, "analyse", _explodes)

    results = candidates.analyse_pending(db, spec, version.id)

    assert calls["n"] == 2
    assert len(results) == 1


# --- over the wire ---------------------------------------------------------------------


def test_analysing_over_the_wire_returns_the_placement(
    auth_client, db, queued, version, monkeypatch, no_network
):
    _deduces(monkeypatch, "B1.1")

    body = auth_client.post(f"/api/investments/research/{queued.id}/analyse").json()

    assert body["status"] == "ANALYSING"
    assert body["proposed_bottleneck"] == "B1.1"
    assert body["bottleneck_name"] == "Power Transmission & HVDC"
    assert body["bottleneck_why"]


def test_the_queue_shows_a_score_only_once_something_has_been_read(
    auth_client, db, queued, version, monkeypatch, no_network
):
    """⚠ Running the quality score over every queued name would read filings nobody asked
    about — the spend the whole candidate/instrument split exists to avoid."""
    before = auth_client.get("/api/investments/research").json()["lines"][0]
    assert before["quality_available"] is None

    _deduces(monkeypatch, "B1.1")
    auth_client.post(f"/api/investments/research/{queued.id}/analyse")

    after = auth_client.get("/api/investments/research").json()["lines"][0]
    assert after["quality_available"] is not None
