"""The inbox: a link, a video, or a remark from a friend.

⚠ **You are a source, and you are measured like one.** What you drop in is recorded exactly
the way a channel's uploads are, with the same mention rows behind it — which is what
eventually answers whether the tips you act on beat the exchange feed you ignore.

The cases below are mostly the *unhappy* ones, because an inbox that swallows things silently
is worse than no inbox: its user goes on dropping links into a void.
"""

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import Candidate, ListedCompany, Mention, SourceItem
from app.services.investments import reading
from app.services.marketdata import webpage
from app.services.marketdata.http import ProviderError
from tests.conftest import make_instrument

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def exchange_list(db):
    rows = [
        ("VOLTAMP", "Voltamp Transformers Limited"),
        ("DELHIVERY", "Delhivery Limited"),
        ("KIRLOSENG", "Kirloskar Oil Engines Limited"),
        ("TARIL", "Transformers And Rectifiers (India) Limited"),
        ("KAYNES", "Kaynes Technology India Limited"),
    ]
    out = {}
    for symbol, name in rows:
        row = ListedCompany(
            id=uuid.uuid4(),
            symbol=symbol,
            exchange="NSE",
            name=name,
            series="EQ",
            refreshed_at=NOW,
        )
        db.add(row)
        out[symbol] = row
    db.flush()
    db.commit()
    return out


@pytest.fixture
def held(db):
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


def _page(text, *, url="https://example.invalid/a", title="An article", thin=False):
    return webpage.Page(url=url, title=title, text=text, is_thin=thin)


# --- a note with no link ----------------------------------------------------------------


def test_a_remark_from_a_friend_becomes_a_lead(db, exchange_list):
    """The plainest case, and the one that has to work without ceremony."""
    result = reading.drop(db, text="My friend says Voltamp Transformers is the quality play")
    db.commit()

    assert result.stored
    assert result.named == ["VOLTAMP"]
    assert result.discovered == ["VOLTAMP"]
    assert reading.queue(db)[0].symbol == "VOLTAMP"


def test_a_company_you_already_follow_is_filed_against_it_not_queued(db, exchange_list, held):
    """⚠ News about your own book belongs on the holding. Queueing it would ask you to decide
    about something you have already decided about."""
    result = reading.drop(db, text="Kaynes Technology keeps compounding")
    db.commit()

    assert result.already_followed == ["KAYNES"]
    assert result.discovered == []
    assert reading.queue(db) == []


def test_a_note_naming_nothing_is_still_recorded(db, exchange_list):
    """The record that you dropped something is the point; the absence of a name is a finding
    about what you dropped, not a reason to lose it."""
    result = reading.drop(db, text="the market feels expensive to me right now")
    db.commit()

    assert result.stored
    assert result.named == []
    assert db.execute(sa.select(sa.func.count()).select_from(SourceItem)).scalar_one() == 1


def test_dropping_nothing_says_so(db):
    """⚠ Never a silent no-op."""
    result = reading.drop(db)

    assert not result.stored
    assert result.note


# --- a link -------------------------------------------------------------------------------


def test_a_link_is_read_and_filed(db, exchange_list, monkeypatch):
    monkeypatch.setattr(
        webpage,
        "fetch",
        lambda url, c=None: _page("Why Delhivery is the pick of the logistics names"),
    )

    result = reading.drop(db, url="https://example.invalid/a")
    db.commit()

    assert result.stored
    assert result.discovered == ["DELHIVERY"]
    assert db.execute(sa.select(SourceItem.url)).scalar_one() == "https://example.invalid/a"


def test_a_page_from_the_exchange_is_a_filing(db, exchange_list, monkeypatch):
    """⚠ Tier 1 rather than tier 2, and it matters: a proposal may rest on a filing and may
    not rest on commentary alone."""
    monkeypatch.setattr(
        webpage,
        "fetch",
        lambda url, c=None: _page("Delhivery order win", url="https://www.nseindia.com/x"),
    )

    result = reading.drop(db, url="https://www.nseindia.com/x")
    db.commit()

    assert result.trust_tier == reading.FILING


def test_a_page_from_anywhere_else_is_a_report_of_one(db, exchange_list, monkeypatch):
    monkeypatch.setattr(
        webpage,
        "fetch",
        lambda url, c=None: _page("Delhivery order win", url="https://blog.invalid/x"),
    )

    assert reading.drop(db, url="https://blog.invalid/x").trust_tier == reading.PRESS


def test_a_lookalike_domain_does_not_inherit_the_exchanges_trust(db):
    """⚠ Matched on the registrable suffix. `nseindia.com.evil.test` is not the exchange."""
    assert not _page("x", url="https://nseindia.com.evil.test/a").is_official
    assert _page("x", url="https://nsearchives.nseindia.com/a").is_official


def test_a_page_that_gave_no_text_is_reported_not_filed(db, exchange_list, monkeypatch):
    """⚠ "Nothing was read" is not "nobody was named". A site needing JavaScript produces
    exactly the same empty result as a page about nothing, and filing it would record a
    source that said nothing when in truth nothing was heard."""
    monkeypatch.setattr(webpage, "fetch", lambda url, c=None: _page("short", thin=True))

    result = reading.drop(db, url="https://example.invalid/spa")

    assert not result.stored
    assert "browser" in result.note


def test_a_pdf_is_refused_rather_than_mangled(db, monkeypatch):
    """⚠ Stripping tags from a binary produces plausible nonsense, and plausible nonsense in a
    research note is worse than an honest refusal — the module rests on every figure being
    traceable to words somebody actually wrote."""

    def _pdf(url, c=None):
        raise ProviderError("WEB", "that is a PDF, and there is no reader for one yet")

    monkeypatch.setattr(webpage, "fetch", _pdf)

    result = reading.drop(db, url="https://example.invalid/a.pdf")

    assert not result.stored
    assert "PDF" in result.note


def test_an_unreachable_link_says_why(db, monkeypatch):
    def _dead(url, c=None):
        raise ProviderError("WEB", "HTTP 404")

    monkeypatch.setattr(webpage, "fetch", _dead)

    assert reading.drop(db, url="https://example.invalid/gone").note == "HTTP 404"


# --- the listing-page problem ----------------------------------------------------------------


def test_a_page_naming_too_many_companies_is_refused(db, exchange_list, monkeypatch):
    """⚠ Measured, not hypothetical: a live Economic Times "stocks in news" listing named 32
    companies on 21 Sep 2026. A drop naming thirty companies is not a lead about thirty
    companies, and queueing them would bury the handful actually argued for under a page of
    navigation."""
    extra = [
        ListedCompany(
            id=uuid.uuid4(),
            symbol=f"FILLER{n}",
            exchange="NSE",
            name=f"Fillerton Number {n} Industries",
            series="EQ",
            refreshed_at=NOW,
        )
        for n in range(15)
    ]
    db.add_all(extra)
    db.commit()
    names = " and ".join(row.name for row in extra)
    monkeypatch.setattr(webpage, "fetch", lambda url, c=None: _page(names))

    result = reading.drop(db, url="https://news.invalid/stocks")
    db.commit()

    assert not result.stored
    assert "listing page" in result.note
    assert reading.queue(db) == []
    assert db.execute(sa.select(sa.func.count()).select_from(Mention)).scalar_one() == 0


def test_a_page_naming_a_handful_is_filed_normally(db, exchange_list, monkeypatch):
    monkeypatch.setattr(
        webpage,
        "fetch",
        lambda url, c=None: _page(
            "Voltamp Transformers and Kirloskar Oil Engines both look interesting"
        ),
    )

    result = reading.drop(db, url="https://blog.invalid/two")
    db.commit()

    assert result.stored
    assert sorted(result.discovered) == ["KIRLOSENG", "VOLTAMP"]


# --- filing the same thing twice ---------------------------------------------------------------


def test_the_same_link_is_not_filed_twice(db, exchange_list, monkeypatch):
    monkeypatch.setattr(webpage, "fetch", lambda url, c=None: _page("Delhivery is the pick"))

    reading.drop(db, url="https://blog.invalid/one")
    db.commit()
    again = reading.drop(db, url="https://blog.invalid/one")
    db.commit()

    assert not again.stored
    assert "already filed" in again.note


def test_the_same_note_twice_is_recognised(db, exchange_list):
    reading.drop(db, text="Voltamp Transformers looks good")
    db.commit()
    again = reading.drop(db, text="Voltamp Transformers looks good")
    db.commit()

    assert not again.stored


# --- you, as a measured source -----------------------------------------------------------------


def test_what_you_drop_is_attributed_to_you(db, exchange_list):
    """⚠ The point of filing your own drops. In six months this answers whether the tips you
    act on beat the feed you ignore."""
    reading.drop(db, text="Voltamp Transformers is the quality play")
    db.commit()

    mine = next(s for s in reading.registered(db) if s.handle == reading.INBOX_HANDLE)
    assert reading.attribution(db, mine).named == 1


def test_your_filings_and_your_tips_are_counted_separately(db, exchange_list, monkeypatch):
    """A page from the regulator and a remark from a friend are different species, and
    averaging them would make both unreadable."""
    monkeypatch.setattr(
        webpage,
        "fetch",
        lambda url, c=None: _page("Delhivery filing", url="https://www.sebi.gov.in/x"),
    )
    reading.drop(db, url="https://www.sebi.gov.in/x")
    reading.drop(db, text="Voltamp Transformers is the quality play")
    db.commit()

    handles = {s.handle: s.trust_tier for s in reading.registered(db)}
    assert handles[reading.INBOX_OFFICIAL_HANDLE] == reading.FILING
    assert handles[reading.INBOX_HANDLE] == reading.PRESS


# --- over the wire -------------------------------------------------------------------------------


def test_the_inbox_route_files_a_note(auth_client, db, exchange_list):
    body = auth_client.post(
        "/api/investments/inbox", json={"text": "Voltamp Transformers is worth a look"}
    ).json()

    assert body["stored"] is True
    assert body["discovered"] == ["VOLTAMP"]
    assert db.execute(sa.select(sa.func.count()).select_from(Candidate)).scalar_one() == 1


def test_the_inbox_route_reports_a_refusal_as_an_outcome(auth_client, db, exchange_list):
    """⚠ Not an error status. Nothing went wrong — the page simply had nothing in it, and the
    user needs telling in the same place they dropped it."""
    r = auth_client.post("/api/investments/inbox", json={})

    assert r.status_code == 200
    assert r.json()["stored"] is False
    assert r.json()["note"]


def test_the_chat_tool_files_a_tip(db, user, exchange_list):
    """⚠ Writes immediately, unlike recording a transaction. A drop only records that
    something was said, and confirming every link is how an inbox stops being used."""
    from app.core.tools.investments import drop_source

    out = drop_source(db, user.id, {"text": "friend likes Kirloskar Oil Engines"})

    assert out["stored"]
    assert out["added_to_research_queue"] == ["KIRLOSENG"]
