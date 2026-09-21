"""Discovery: recognising a company nobody is following, and queueing it.

Without this the system can only ever say hold, trim or sell — a research analyst that can
only comment on what you already own is a bookkeeper with opinions.

The property under test throughout: **recognising a company never heard of is exactly as
deterministic as recognising one already held.** The vocabulary is the exchange's own equity
list, so no model ever produces a name — a fictional company written into `mentions` would be
indistinguishable from a real one, in the very table the attribution measure counts.
"""

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import Candidate, Instrument, ListedCompany, Mention
from app.services.investments import reading
from app.services.marketdata import feeds
from tests.conftest import make_instrument

NOW = dt.datetime.now(dt.UTC)


def _listed(db, symbol, name, isin=None):
    row = ListedCompany(
        id=uuid.uuid4(),
        symbol=symbol,
        exchange="NSE",
        name=name,
        series="EQ",
        isin=isin,
        refreshed_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def exchange_list(db):
    """A handful of the exchange's real spellings, including the awkward ones."""
    rows = [
        _listed(db, "TARIL", "Transformers And Rectifiers (India) Limited"),
        _listed(db, "KIRLOSENG", "Kirloskar Oil Engines Limited"),
        _listed(db, "DELHIVERY", "Delhivery Limited"),
        _listed(db, "AMAL", "Amal Limited"),
        _listed(db, "ACE", "Action Construction Equipment Limited"),
        _listed(db, "ETERNAL", "Eternal Limited"),
        _listed(db, "KAYNES", "Kaynes Technology India Limited"),
    ]
    db.commit()
    return {row.symbol: row for row in rows}


@pytest.fixture
def held(db):
    """One company already followed, whose listed name is spelled differently."""
    row = make_instrument(
        db,
        symbol="KAYNES",
        exchange="NSE",
        name="Kaynes Technology",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.flush()
    db.commit()
    return row


@pytest.fixture
def channel(db):
    row = reading.register(
        db,
        kind="YOUTUBE",
        name="pytest channel",
        handle="UCresearch0000000000",
        trust_tier=reading.COMMENTARY,
        approved=True,
    )
    db.commit()
    return row


@pytest.fixture
def exchange(db):
    row = reading.register(
        db,
        kind="RSS_EXCHANGE",
        name="pytest exchange",
        handle="announcements",
        trust_tier=reading.FILING,
        approved=True,
    )
    db.commit()
    return row


def _item(external_id, title, body=""):
    return feeds.Item(
        external_id=external_id,
        title=title,
        url=f"https://example.invalid/{external_id}",
        published_at=NOW,
        body=body,
        feed="youtube",
    )


# --- recognising a company nobody follows ---------------------------------------------------


def test_a_company_never_heard_of_is_recognised(db, exchange_list):
    """The whole point. Before this, a name outside the portfolio produced nothing at all."""
    vocab = reading.vocabulary(db)

    found = reading.named_in("Why Delhivery is still my highest conviction pick", vocab)

    assert [t.symbol for t, _ in found] == ["DELHIVERY"]
    assert not found[0][0].is_known, "listed, not followed"


def test_an_ampersand_is_the_word_and(db, exchange_list):
    """⚠ The exchange lists TARIL as *Transformers **And** Rectifiers*; everyone who writes
    about it types *Transformers **&** Rectifiers*. Tokenised literally the two never meet,
    and the company is invisible — silently, because a name that fails to match looks exactly
    like a name that was never said."""
    vocab = reading.vocabulary(db)

    assert reading.named_in("Transformers & Rectifiers India won a large order", vocab)
    assert reading.named_in("Transformers And Rectifiers (India) Limited filed results", vocab)


def test_a_company_already_followed_is_not_rediscovered(db, exchange_list, held):
    """⚠ The instrument is "Kaynes Technology", the exchange says "Kaynes Technology India
    Limited". Longest-match-wins picks the listed spelling, so without resolving back to the
    holding, a filing about something you own would open a research line for it."""
    vocab = reading.vocabulary(db)

    found = reading.named_in("Kaynes Technology India Limited board meeting", vocab)

    assert len(found) == 1
    assert found[0][0].is_known
    assert found[0][0].instrument_id == held.id


def test_a_name_reached_twice_in_one_sentence_is_one_mention(db, exchange_list, held):
    """A company can be reached by its name and by its ticker in the same breath."""
    vocab = reading.vocabulary(db)

    found = reading.named_in("KAYNES — Kaynes Technology India Limited — reported", vocab)

    assert len(found) == 1


# --- and NOT recognising ordinary English ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "we had an ace of a quarter",
        "eternal optimism about the future",
        "a great amal of work",
        "the ACE of spades",
    ],
)
def test_a_company_name_that_is_also_an_ordinary_word_is_not_a_mention(db, exchange_list, text):
    """⚠ The asymmetry is deliberate: a missed mention costs an idea, a false one corrupts the
    denominator the attribution measure divides by — and nothing downstream can tell a false
    mention from a real one."""
    assert reading.named_in(text, reading.vocabulary(db)) == []


def test_a_short_ticker_is_not_matched_in_the_wider_universe(db, exchange_list):
    """⚠ The exchange carries 165 symbols of three characters or fewer. At that length an
    uppercase run in ordinary text is far more often an abbreviation than a company."""
    vocab = reading.vocabulary(db)

    assert "ACE" not in vocab.by_symbol


def test_a_short_ticker_you_follow_is_still_matched(db, exchange_list):
    """A symbol you confirmed by following it gets the lower floor — you chose it."""
    inst = make_instrument(
        db,
        symbol="ACE",
        exchange="NSE",
        name="Action Construction Equipment",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.flush()
    db.commit()

    vocab = reading.vocabulary(db)
    found = reading.named_in("ACE reported results today", vocab)

    assert [t.instrument_id for t, _ in found] == [inst.id]


# --- the queue -------------------------------------------------------------------------------


def test_a_commentator_naming_something_new_opens_a_research_line(
    db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Delhivery is my top pick for 2026")]
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.discovered == ["DELHIVERY"]
    line = reading.queue(db)[0]
    assert line.symbol == "DELHIVERY"
    assert line.named_by == "pytest channel"
    assert line.mention_count == 1


def test_an_exchange_filing_on_an_unfollowed_company_opens_nothing(
    db, exchange_list, exchange, monkeypatch
):
    """⚠ Measured, not assumed: one live poll of NSE's five feeds named 184 listed companies,
    21 of them one asset manager's routine ETF notices. A company filing its own paperwork is
    not recommending itself, and a queue holding several hundred entries a day is a queue
    abandoned within a week."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("f1", "Delhivery Limited", "has informed the Exchange")],
    )

    result = reading.poll(db, exchange)
    db.commit()

    assert result.stored == 1, "the document was still read"
    assert result.discovered == []
    assert reading.queue(db) == []
    assert result.mentions == 0, "and no mention, because the exchange makes no claims"


def test_an_exchange_filing_on_a_company_you_follow_is_recorded_in_full(
    db, exchange_list, held, exchange, monkeypatch
):
    """That half is news about your own book, and it is the half that costs money."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("f1", "Kaynes Technology India Limited", "informed the Exchange")],
    )

    result = reading.poll(db, exchange)
    db.commit()

    assert result.mentions == 1


def test_being_named_again_raises_the_count_not_a_second_line(
    db, exchange_list, channel, monkeypatch
):
    """A company several sources keep returning to is a different proposition from one named
    once in passing, and the queue is ordered on exactly that."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery looks good")])
    reading.poll(db, channel)
    db.commit()
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v2", "Delhivery again, still good")]
    )
    reading.poll(db, channel)
    db.commit()

    lines = reading.queue(db)
    assert len(lines) == 1
    assert lines[0].mention_count == 2


def test_the_best_tier_that_ever_named_it_is_kept(db, exchange_list, channel, monkeypatch):
    """⚠ Not the latest and not the worst. A company named once by a filing and ten times by
    commentary is a filing-grade lead, and tier is what the sourcing gate reads."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery looks good")])
    reading.poll(db, channel)
    db.commit()

    press = reading.register(
        db,
        kind="RSS_NEWS",
        name="pytest press",
        handle="feed",
        trust_tier=reading.PRESS,
        approved=True,
    )
    db.commit()
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("n1", "Delhivery wins deal")])
    reading.poll(db, press)
    db.commit()

    assert reading.queue(db)[0].best_trust_tier == reading.PRESS


def test_the_queue_is_ordered_by_how_hard_it_is_being_pushed(
    db, exchange_list, channel, monkeypatch
):
    """Not by date — newest-first would bury a repeatedly-named company under today's noise."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("v1", "Delhivery is interesting"),
            _item("v2", "Delhivery again"),
            _item("v3", "Kirloskar Oil Engines is worth a look"),
        ],
    )
    reading.poll(db, channel)
    db.commit()

    assert [line.symbol for line in reading.queue(db)] == ["DELHIVERY", "KIRLOSENG"]


# --- deciding about a candidate ---------------------------------------------------------------


def test_promoting_a_candidate_starts_it_being_followed(db, exchange_list, channel, monkeypatch):
    """⚠ The moment the meter starts. Until now it has cost nothing — which is why it is an
    explicit act rather than something the queue does on its own."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()

    candidate = db.execute(sa.select(Candidate)).scalar_one()
    instrument = reading.promote(db, candidate, sector="LOGISTICS")
    db.commit()

    assert instrument.is_tracked
    assert instrument.symbol == "DELHIVERY"
    assert instrument.isin == exchange_list["DELHIVERY"].isin
    assert candidate.status == "PROMOTED"
    assert reading.queue(db) == [], "it has left the queue"


def test_a_promoted_company_is_thereafter_recognised_as_followed(
    db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    reading.promote(db, db.execute(sa.select(Candidate)).scalar_one())
    db.commit()

    found = reading.named_in("Delhivery reported results", reading.vocabulary(db))

    assert found[0][0].is_known


def test_dismissing_a_candidate_demands_a_reason(db, exchange_list, channel, monkeypatch):
    """⚠ The reason is the data. It is the only record of what kinds of idea keep being
    refused, and without it a tidied queue is indistinguishable from one never filled."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    candidate = db.execute(sa.select(Candidate)).scalar_one()

    with pytest.raises(ValueError):
        reading.dismiss(db, candidate, "   ")


def test_the_database_refuses_a_dismissal_with_no_reason(db, exchange_list, channel, monkeypatch):
    """Enforced below the application, because a rule the code promises to honour is one a
    later writer forgets."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    candidate = db.execute(sa.select(Candidate)).scalar_one()

    candidate.status = "DISMISSED"
    with pytest.raises(sa.exc.DatabaseError):
        db.flush()
    db.rollback()


def test_a_dismissed_candidate_is_not_silently_reopened(db, exchange_list, channel, monkeypatch):
    """⚠ Being named again is not new information — a channel repeating itself is the most
    ordinary thing a channel does — and a queue that resurrected everything you refused would
    train you to stop refusing."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    reading.dismiss(db, db.execute(sa.select(Candidate)).scalar_one(), "too expensive")
    db.commit()

    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v2", "Delhivery still good")])
    reading.poll(db, channel)
    db.commit()

    assert reading.queue(db) == []
    candidate = db.execute(sa.select(Candidate)).scalar_one()
    assert candidate.status == "DISMISSED"
    assert candidate.mention_count == 2, "it is still being pushed, and a review can see that"


# --- the vocabulary ---------------------------------------------------------------------------


def test_a_delisted_company_is_marked_not_removed(db, exchange_list, monkeypatch):
    """⚠ It was still named by sources while it was listed. Removing it would make those
    mentions unresolvable — shrinking the denominator in the one direction that flatters
    every source."""
    monkeypatch.setattr(
        reading.universe,
        "fetch",
        lambda c=None: [
            reading.universe.Listed("DELHIVERY", "Delhivery Limited", "EQ", None, None)
        ],
    )

    report = reading.sync_universe(db)
    db.commit()

    assert report["delisted"] == len(exchange_list) - 1
    assert db.execute(sa.select(sa.func.count()).select_from(ListedCompany)).scalar_one() == len(
        exchange_list
    )


def test_a_renamed_company_keeps_its_row(db, exchange_list, monkeypatch):
    monkeypatch.setattr(
        reading.universe,
        "fetch",
        lambda c=None: [reading.universe.Listed("ETERNAL", "Zomato Limited", "EQ", None, None)],
    )
    reading.sync_universe(db)
    db.commit()

    row = db.execute(sa.select(ListedCompany).where(ListedCompany.symbol == "ETERNAL")).scalar_one()
    assert row.name == "Zomato Limited"


# --- over the wire -----------------------------------------------------------------------------


def test_the_research_route_reports_the_queue_and_the_vocabulary(
    auth_client, db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()

    body = auth_client.get("/api/investments/research").json()

    assert [line["symbol"] for line in body["lines"]] == ["DELHIVERY"]
    # ⚠ Shown because a vocabulary that failed to load would make discovery silently stop,
    # and a count of zero says so immediately.
    assert body["universe_size"] == len(exchange_list)


def test_promoting_over_the_wire_creates_the_instrument(
    auth_client, db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    candidate = db.execute(sa.select(Candidate)).scalar_one()

    out = auth_client.post(
        f"/api/investments/research/{candidate.id}/promote", json={"sector": "LOGISTICS"}
    ).json()

    assert out["status"] == "PROMOTED"
    db.expire_all()
    assert (
        db.execute(sa.select(Instrument).where(Instrument.symbol == "DELHIVERY"))
        .scalar_one()
        .is_tracked
    )


def test_dismissing_over_the_wire_records_the_reason(
    auth_client, db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    candidate = db.execute(sa.select(Candidate)).scalar_one()

    out = auth_client.post(
        f"/api/investments/research/{candidate.id}/dismiss",
        json={"reason": "50% above any defensible multiple"},
    ).json()

    assert out["status"] == "DISMISSED"
    assert "defensible" in out["dismissed_reason"]


def test_an_empty_reason_is_refused_at_the_edge(
    auth_client, db, exchange_list, channel, monkeypatch
):
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()
    candidate = db.execute(sa.select(Candidate)).scalar_one()

    r = auth_client.post(f"/api/investments/research/{candidate.id}/dismiss", json={"reason": ""})

    assert r.status_code == 422


def test_a_mention_of_an_unfollowed_company_names_exactly_one_of_the_two(
    db, exchange_list, channel, monkeypatch
):
    """⚠ A mention is about a company; sometimes that company is tracked and sometimes it is
    merely listed. The database insists on exactly one, so neither can be quietly forgotten."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "Delhivery, my pick")])
    reading.poll(db, channel)
    db.commit()

    row = db.execute(sa.select(Mention)).scalar_one()
    assert row.instrument_id is None
    assert row.listed_company_id == exchange_list["DELHIVERY"].id

    row.instrument_id = uuid.uuid4()
    with pytest.raises(sa.exc.DatabaseError):
        db.flush()
    db.rollback()
