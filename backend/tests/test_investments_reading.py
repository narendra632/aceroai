"""The reading layer, and the one property that cannot be added later.

`mentions` exists to record **every** instrument **every** source names — acted on or not,
held or not, dismissed or not. Most of what follows checks that property against the ways it
would most easily be lost: a matcher that misses a name, a model that invents one, a stance
read onto a filing that never took a side, and an attribution number computed over six calls.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import (
    Mention,
    Portfolio,
    PriceObservation,
    Source,
    SourceItem,
    Transaction,
)
from app.services.investments import reading
from app.services.marketdata import feeds
from tests.conftest import TEST_SOURCE, make_instrument

TODAY = dt.date.today()


@pytest.fixture
def tracked(db):
    """Two companies whose names behave differently in text."""
    rows = [
        make_instrument(
            db,
            symbol="APARINDS",
            exchange="NSE",
            name="Apar Industries",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        make_instrument(
            db,
            symbol="ROLEXRINGS",
            exchange="NSE",
            name="Rolex Rings",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
    ]
    db.flush()
    db.commit()
    return rows


@pytest.fixture
def channel(db):
    row = reading.register(
        db,
        kind="YOUTUBE",
        name="pytest channel",
        handle="UCpytest00000000000000",
        trust_tier=reading.COMMENTARY,
        approved=True,
    )
    # Committed, because the API tests read through the request's own session and a flushed
    # row is invisible to it.
    db.commit()
    return row


@pytest.fixture
def real_holding(db, user, tracked):
    """Apar actually owned, so `is_held` is true and a filing on it can earn a push."""
    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-real", kind="REAL")
    db.add(book)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=tracked[0].id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=30),
            quantity=D(10),
            price=D(100),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    db.commit()
    return book


def _item(external_id, title, body="", when=None):
    return feeds.Item(
        external_id=external_id,
        title=title,
        url=f"https://example.invalid/{external_id}",
        published_at=when or dt.datetime.now(dt.UTC),
        body=body,
        feed="youtube",
    )


# --- who was named -----------------------------------------------------------------------


def test_a_company_is_found_by_its_full_filed_name(db, tracked):
    """The exchange writes the legal name, so that is the form that must match."""
    vocab = reading.vocabulary(db)
    text = "Apar Industries Limited has informed the Exchange about bagging of orders."

    found = reading.named_in(text, vocab)
    assert [t.symbol for t, _ in found] == ["APARINDS"]


def test_stripping_the_trailing_form_does_not_strip_the_name(db, tracked):
    """⚠ The bug this guards. Stripping "Industries" everywhere left `apar` — four
    characters, under the floor — so Apar could never be matched by name at all."""
    vocab = reading.vocabulary(db)
    assert reading.named_in("A report on Apar Industries today", vocab)
    assert reading._name_key("Apar Industries Limited") == ("apar", "industries")


def test_a_ticker_is_matched_only_when_it_is_shouted(db, tracked):
    """⚠ Case-sensitive on purpose. Lower-cased, half the tickers on the exchange are
    ordinary English words."""
    vocab = reading.vocabulary(db)

    assert reading.named_in("I am buying APARINDS today", vocab)
    assert not reading.named_in("the aparinds of the matter", vocab)


def test_an_ordinary_word_that_happens_to_be_part_of_a_name_is_not_a_mention(db, tracked):
    """⚠ A false mention is worse than a missed one: it enters the denominator the
    attribution measure divides by, and nothing downstream can tell it from a real one."""
    vocab = reading.vocabulary(db)

    assert reading.named_in("Rolex Rings Limited declared results", vocab)
    assert not reading.named_in("I wear a Rolex watch", vocab)


def test_only_indian_equities_are_matched(db, tracked):
    """A crypto ticker inside prose would match constantly, and a mention of Bitcoin is not
    an idea about an instrument in the sense this table measures."""
    coin = make_instrument(
        db,
        symbol="BTC",
        exchange="CRYPTO",
        name="Bitcoin",
        asset_class="CRYPTO",
        currency="INR",
    )
    db.flush()
    db.commit()

    assert coin.symbol not in reading.vocabulary(db).by_symbol


# --- every one of them -------------------------------------------------------------------


def test_every_company_named_gets_a_row_even_though_none_was_acted_on(
    db, tracked, channel, monkeypatch
):
    """⚠ The whole reason this table exists. Recording only the ideas that were acted on
    measures the reader's filter rather than the source."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("v1", "Apar Industries and Rolex Rings both look interesting")],
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.mentions == 2
    assert sorted(result.names) == ["APARINDS", "ROLEXRINGS"]
    rows = db.execute(sa.select(Mention)).scalars().all()
    assert all(row.became_proposal_id is None for row in rows), "none was acted on, and they count"


def test_an_item_naming_nothing_tracked_is_still_stored(db, channel, monkeypatch):
    """The item is the record that the source published; the absence of a mention is the
    finding. A poller that dropped it would report the source as having said nothing."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "A video about bonds")])

    result = reading.poll(db, channel)
    db.commit()

    assert result.stored == 1
    assert result.mentions == 0


def test_the_same_item_is_not_ingested_twice(db, tracked, channel, monkeypatch):
    """⚠ A feed is polled four times a day and returns the same window each time."""
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )

    first = reading.poll(db, channel)
    db.commit()
    second = reading.poll(db, channel)
    db.commit()

    assert (first.stored, first.mentions) == (1, 1)
    assert (second.stored, second.mentions) == (0, 0)


def test_a_feed_that_says_nothing_is_not_a_source_that_published_nothing(db, channel, monkeypatch):
    """⚠ YouTube's RSS endpoint is unsupported and 404s intermittently. Conflating the two
    would turn a missed fetch into "this channel named no companies this week"."""

    def _silent(source, c):
        raise feeds.NotPublished(source.handle)

    monkeypatch.setattr(reading, "_fetch", _silent)

    result = reading.poll(db, channel)
    db.commit()

    assert result.silent
    assert result.error is None
    assert channel.last_polled_at is not None, "it was polled; the feed simply answered nothing"


# --- what the model is allowed to do -------------------------------------------------------


def test_the_model_reads_a_direction_onto_what_the_matcher_found(db, tracked, channel, monkeypatch):
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries is my top pick")]
    )
    monkeypatch.setattr(reading, "stances_for", lambda text, symbols: {s: "BULL" for s in symbols})

    reading.poll(db, channel)
    db.commit()

    assert db.execute(sa.select(Mention.stance)).scalar_one() == "BULL"


def test_the_model_cannot_introduce_a_company_that_was_not_named(db, tracked, channel, monkeypatch):
    """⚠ The guard on the split. A model that could add names would be inventing the very
    mentions the attribution measure counts, and an invented one is indistinguishable from a
    real one once written."""

    async def _hallucinate(text, symbols):
        return {"APARINDS": "BULL", "HDFCBANK": "BEAR", "TCS": "BULL"}

    monkeypatch.setattr(reading, "_ask_stances", _hallucinate)

    stances = reading.stances_for("Apar Industries is my top pick", ["APARINDS"])

    assert stances == {"APARINDS": "BULL"}


def test_a_failed_model_call_still_records_the_mention(db, tracked, channel, monkeypatch):
    """⚠ The denominator matters more than the direction. Losing the row to save the stance
    would be exactly backwards."""

    async def _boom(text, symbols):
        raise RuntimeError("provider down")

    monkeypatch.setattr(reading, "_ask_stances", _boom)

    assert reading.stances_for("Apar Industries", ["APARINDS"]) == {"APARINDS": "MENTION_ONLY"}


def test_an_unreadable_stance_becomes_mention_only_rather_than_a_guess(db, monkeypatch):
    async def _nonsense(text, symbols):
        return {"APARINDS": "VERY BULLISH INDEED"}

    monkeypatch.setattr(reading, "_ask_stances", _nonsense)

    assert reading.stances_for("x", ["APARINDS"]) == {"APARINDS": "MENTION_ONLY"}


def test_a_filing_is_never_asked_which_side_it_takes(db, tracked, monkeypatch):
    """⚠ An exchange announcement reports that something happened. Reading a bull case into
    "board meeting intimation" would put noise straight into the attribution numbers."""
    exchange = reading.register(
        db,
        kind="RSS_EXCHANGE",
        name="pytest exchange",
        handle="announcements",
        trust_tier=reading.FILING,
        approved=True,
    )
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("f1", "Apar Industries Limited", "informed the Exchange")],
    )

    def _never(text, symbols):
        raise AssertionError("a filing must not be sent to the model for a stance")

    monkeypatch.setattr(reading, "stances_for", _never)

    reading.poll(db, exchange)
    db.commit()

    assert db.execute(sa.select(Mention.stance)).scalar_one() == "MENTION_ONLY"


# --- the register ---------------------------------------------------------------------------


def test_nothing_is_read_from_an_unapproved_source(db, tracked):
    """⚠ Adding a source changes what the system can be talked into. That is a decision."""
    pending = reading.register(
        db,
        kind="YOUTUBE",
        name="unapproved",
        handle="UCnope0000000000000000",
        trust_tier=reading.COMMENTARY,
    )
    db.commit()

    assert pending.approved_at is None
    with pytest.raises(reading.Unapproved):
        reading.poll(db, pending)


def test_registering_the_same_handle_twice_does_not_reset_its_approval(db):
    first = reading.register(
        db, kind="YOUTUBE", name="a", handle="UCsame000000000000000", trust_tier=3, approved=True
    )
    db.commit()
    again = reading.register(
        db, kind="YOUTUBE", name="a", handle="UCsame000000000000000", trust_tier=3
    )

    assert again.id == first.id
    assert again.approved_at is not None


def test_a_source_is_switched_off_rather_than_deleted(db, channel):
    """⚠ Deleting one would orphan every mention that cited it and quietly rewrite the
    attribution history."""
    reading.set_active(db, channel, active=False)
    db.commit()

    assert channel.id in {s.id for s in reading.registered(db)}
    assert channel.id not in {s.id for s in reading.registered(db, only_readable=True)}


# --- what the database refuses ---------------------------------------------------------------


def test_what_a_source_said_cannot_be_edited(db, tracked, channel, monkeypatch):
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )
    reading.poll(db, channel)
    db.commit()

    row = db.execute(sa.select(Mention)).scalar_one()
    row.stance = "BEAR"
    with pytest.raises(sa.exc.DatabaseError):
        db.flush()
    db.rollback()


def test_what_a_mention_led_to_can_still_be_recorded(db, tracked, channel, monkeypatch):
    """⚠ Why the guard is narrowed rather than whole-table, exactly as 021 had to narrow
    claims. A fact discovered later about an utterance that has not moved."""
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )
    reading.poll(db, channel)
    db.commit()

    row = db.execute(sa.select(Mention)).scalar_one()
    row.became_proposal_id = None  # no proposal exists here; the UPDATE itself is the check
    row.claim_excerpt = row.claim_excerpt
    db.commit()

    assert db.execute(sa.select(sa.func.count()).select_from(Mention)).scalar_one() == 1


def test_a_mention_cannot_be_deleted(db, tracked, channel, monkeypatch):
    """⚠ A mention that can be removed after the fact is one that never has to be counted."""
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )
    reading.poll(db, channel)
    db.commit()

    # ⚠ The trigger fires on the statement, not on the commit, so the DELETE itself is what
    # must be caught — a test that only wrapped `commit()` would pass for the wrong reason.
    with pytest.raises(sa.exc.DatabaseError):
        db.execute(sa.delete(Mention))
    db.rollback()


# --- was the source worth reading ------------------------------------------------------------


def _mention_with_price(db, channel, instrument, *, stance, days_ago, then, later):
    """One directional call, with prices at the call and at its horizon."""
    when = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)
    item = SourceItem(
        id=uuid.uuid4(),
        kind="YOUTUBE",
        source_id=channel.id,
        source=channel.name,
        external_id=f"e{uuid.uuid4().hex[:8]}",
        published_at=when,
        fetched_at=when,
        content_hash=uuid.uuid4().hex,
        excerpt="x",
    )
    db.add(item)
    db.flush()
    db.add(
        Mention(
            id=uuid.uuid4(),
            source_item_id=item.id,
            instrument_id=instrument.id,
            stance=stance,
            claim_excerpt="x",
        )
    )
    for offset, price in ((0, then), (90, later)):
        db.add(
            PriceObservation(
                instrument_id=instrument.id,
                observed_at=when + dt.timedelta(days=offset),
                source=TEST_SOURCE,
                kind="CLOSE",
                price=price,
                currency="INR",
            )
        )


def test_a_hit_rate_is_withheld_until_there_are_enough_settled_calls(db, tracked, channel):
    """⚠ A figure over six calls reads exactly like one over six hundred."""
    _mention_with_price(
        db, channel, tracked[0], stance="BULL", days_ago=120, then=D(100), later=D(150)
    )
    db.commit()

    measure = reading.attribution(db, channel).hit_rate
    assert measure.value is None
    assert str(reading.watching.MIN_OBSERVATIONS) in measure.detail


def test_a_call_whose_horizon_has_not_arrived_is_pending_not_wrong(db, tracked, channel):
    """Counting an unsettled call as a miss would make every recent source look bad."""
    _mention_with_price(
        db, channel, tracked[0], stance="BULL", days_ago=5, then=D(100), later=D(150)
    )
    db.commit()

    attribution = reading.attribution(db, channel)
    assert attribution.pending == 1
    assert attribution.scored == 0


def test_a_source_that_took_no_side_is_counted_but_never_scored(db, tracked, channel):
    """⚠ Naming a company without a view cannot be right or wrong — but it still belongs in
    the denominator of what the source named."""
    _mention_with_price(
        db, channel, tracked[0], stance="MENTION_ONLY", days_ago=120, then=D(100), later=D(150)
    )
    db.commit()

    attribution = reading.attribution(db, channel)
    assert attribution.named == 1
    assert attribution.directional == 0
    assert attribution.scored == 0


def test_a_bear_call_on_a_stock_that_fell_is_a_hit(db, tracked, channel):
    for _ in range(reading.watching.MIN_OBSERVATIONS):
        _mention_with_price(
            db, channel, tracked[0], stance="BEAR", days_ago=120, then=D(100), later=D(80)
        )
    db.commit()

    measure = reading.attribution(db, channel).hit_rate
    assert measure.n == reading.watching.MIN_OBSERVATIONS
    assert measure.value == D(1)


def test_a_bull_call_on_a_stock_that_fell_is_a_miss(db, tracked, channel):
    for _ in range(reading.watching.MIN_OBSERVATIONS):
        _mention_with_price(
            db, channel, tracked[0], stance="BULL", days_ago=120, then=D(100), later=D(80)
        )
    db.commit()

    assert reading.attribution(db, channel).hit_rate.value == D(0)


def test_a_call_is_not_scored_against_a_price_that_never_reached_its_horizon(db, tracked, channel):
    """⚠ `value_as_of` carries the last price forward, so a series ending before the horizon
    would answer with a stale price and score the call against a date that never arrived."""
    when = dt.datetime.now(dt.UTC) - dt.timedelta(days=120)
    item = SourceItem(
        id=uuid.uuid4(),
        kind="YOUTUBE",
        source_id=channel.id,
        source=channel.name,
        external_id="stale",
        published_at=when,
        fetched_at=when,
        content_hash="h",
        excerpt="x",
    )
    db.add(item)
    db.flush()
    db.add(
        Mention(
            id=uuid.uuid4(),
            source_item_id=item.id,
            instrument_id=tracked[0].id,
            stance="BULL",
            claim_excerpt="x",
        )
    )
    db.add(
        PriceObservation(
            instrument_id=tracked[0].id,
            observed_at=when,
            source=TEST_SOURCE,
            kind="CLOSE",
            price=D(100),
            currency="INR",
        )
    )
    db.commit()

    attribution = reading.attribution(db, channel)
    assert attribution.scored == 0
    assert attribution.pending == 1


# --- over the wire -----------------------------------------------------------------------


def test_the_reading_route_reports_what_is_registered(auth_client, db, tracked, channel):
    body = auth_client.get("/api/investments/reading").json()

    assert any(s["name"] == "pytest channel" for s in body["sources"])
    assert body["awaiting_approval"] == 0


def test_an_unapproved_source_is_counted_for_the_user_to_decide(auth_client, db):
    reading.register(
        db, kind="YOUTUBE", name="waiting", handle="UCwait00000000000000", trust_tier=3
    )
    db.commit()

    assert auth_client.get("/api/investments/reading").json()["awaiting_approval"] == 1


def test_approving_a_source_starts_it_being_read(auth_client, db):
    row = reading.register(
        db, kind="YOUTUBE", name="waiting", handle="UCwait00000000000000", trust_tier=3
    )
    db.commit()

    out = auth_client.post(f"/api/investments/reading/sources/{row.id}/approve").json()

    assert out["approved_at"] is not None
    # The route wrote through its OWN session, so this one is still holding the row it read
    # before the call. Expiring it is what makes the assertion about the database.
    db.expire_all()
    assert db.get(Source, row.id).approved_at is not None


def test_switching_a_source_off_leaves_it_registered(auth_client, db, channel):
    out = auth_client.post(
        f"/api/investments/reading/sources/{channel.id}/active", json={"is_active": False}
    ).json()

    assert out["is_active"] is False
    assert db.get(Source, channel.id) is not None


def test_what_was_heard_shows_whether_it_is_held(auth_client, db, tracked, channel, monkeypatch):
    """⚠ Shown, not filtered on. A reading list that hid what is already owned would hide
    every piece of bad news about it — the half that actually costs money."""
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )
    reading.poll(db, channel)
    db.commit()

    heard = auth_client.get("/api/investments/reading").json()["heard"]
    assert [h["symbol"] for h in heard] == ["APARINDS"]
    assert heard[0]["is_held"] is False, "tracked, but nothing was bought in this test"


# --- the job ------------------------------------------------------------------------------


def test_the_poll_says_nothing_when_no_source_named_anything(db, user, channel, monkeypatch):
    """⚠ The announcement feed carries several hundred items a day. A job that pushed on each
    one would be a job whose notifications are dismissed unread within a week — and the one
    about a factory fire would be dismissed with them."""
    from app.jobs import reading as reading_job

    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_item("v1", "A video on bonds")])

    result = reading_job.sources_poll(db, user)

    assert result.silent
    assert result.notify is None
    assert result.detail["stored"] == 1


def test_commentary_never_interrupts_however_loud_it_is(db, user, tracked, channel, monkeypatch):
    """⚠ A video naming a holding is something to read on a schedule, not an interruption.
    Interrupting on it is how a channel ends up setting the agenda for a portfolio."""
    from app.jobs import reading as reading_job

    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("v1", "Apar Industries just won a massive order, huge news")],
    )
    monkeypatch.setattr(reading, "stances_for", lambda text, symbols: {s: "BULL" for s in symbols})

    result = reading_job.sources_poll(db, user)

    assert result.detail["mentions"] == 1
    assert result.notify is None, "tier 3, so it is read rather than pushed"


def test_a_material_filing_on_a_held_company_is_worth_saying(db, user, real_holding, monkeypatch):
    """The one case that earns an interruption: the exchange, about something owned."""
    from app.jobs import reading as reading_job

    exchange = reading.register(
        db,
        kind="RSS_EXCHANGE",
        name="pytest exchange",
        handle="announcements",
        trust_tier=reading.FILING,
        approved=True,
    )
    db.commit()
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item(
                "f1",
                "Apar Industries Limited",
                "Apar Industries Limited has informed the Exchange about "
                "Bagging/Receiving of orders/contracts",
            )
        ],
    )

    result = reading_job.sources_poll(db, user)

    assert exchange.last_polled_at is not None
    assert result.notify is not None
    assert "APARINDS" in result.notify.title


def test_a_routine_filing_on_a_held_company_is_recorded_without_buzzing(
    db, user, real_holding, monkeypatch
):
    """⚠ A board-meeting intimation is not news. Recording it and pushing it are different
    decisions, and conflating them is what makes a notification stream worthless."""
    from app.jobs import reading as reading_job

    reading.register(
        db,
        kind="RSS_EXCHANGE",
        name="pytest exchange",
        handle="announcements",
        trust_tier=reading.FILING,
        approved=True,
    )
    db.commit()
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("f1", "Apar Industries Limited", "informed the Exchange about Board Meeting")
        ],
    )

    result = reading_job.sources_poll(db, user)

    assert result.detail["mentions"] == 1
    assert result.notify is None


def test_one_document_announced_twice_is_stored_once(db, tracked, channel, monkeypatch):
    """⚠ Measured, not hypothetical: NSE's results feed returned four entries and two links
    on 21 Sep 2026 — the same XBRL file announced twice, a second apart. A poller that
    trusted the feed to be a set would collide with its own insert halfway through the batch
    and lose the whole round to a rollback."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("same", "Apar Industries", "RELATING TO:Annual"),
            _item("same", "Apar Industries", "RELATING TO:Fourth Quarter"),
        ],
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.fetched == 2
    assert result.stored == 1
    assert result.mentions == 1


def test_both_announcements_of_one_document_are_kept_in_its_words(
    db, tracked, channel, monkeypatch
):
    """⚠ They are two readings of one filing, not duplicates. The excerpt is the evidence,
    so discarding one would throw away half of what the exchange said about the file."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("same", "Apar Industries", "RELATING TO:Annual"),
            _item("same", "Apar Industries", "RELATING TO:Fourth Quarter"),
        ],
    )

    reading.poll(db, channel)
    db.commit()

    excerpt = db.execute(sa.select(SourceItem.excerpt)).scalar_one()
    assert "Annual" in excerpt
    assert "Fourth Quarter" in excerpt


def test_a_document_already_stored_under_this_source_is_not_stored_again(
    db, tracked, channel, monkeypatch
):
    """⚠ Matched on the source NAME, because that is the unique constraint the table carries.
    Checking `source_id` would look right and still collide with rows written before the
    register existed, which carry no `source_id` at all."""
    db.add(
        SourceItem(
            id=uuid.uuid4(),
            kind="YOUTUBE",
            source_id=None,
            source=channel.name,
            external_id="v1",
            fetched_at=dt.datetime.now(dt.UTC),
            content_hash="h",
            excerpt="x",
        )
    )
    db.commit()
    monkeypatch.setattr(
        reading, "_fetch", lambda source, c: [_item("v1", "Apar Industries reported results")]
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.stored == 0
