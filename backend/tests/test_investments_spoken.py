"""Reading names out of commentary that is not written in Latin script.

The point of interest is not that it works — it is what happens when the model is wrong.
Everything it produces is a *string*, and the exchange's own listed register decides whether
any string is a company. So these tests are mostly about the model being confidently wrong and
nothing bad happening.
"""

import json

import pytest
import sqlalchemy as sa

from app.db.models import Mention, SourceItem
from app.services.investments import reading, spoken
from app.services.marketdata import feeds, transcript
from tests.conftest import make_instrument

HINDI = "आज हम कायन्स टेक्नोलॉजी के बारे में बात करेंगे, यह एक अच्छी कंपनी है"


def _reply(monkeypatch, payload):
    async def fake(_text):
        return payload

    monkeypatch.setattr(spoken, "_ask", fake)


def test_a_name_arrives_with_the_words_it_was_heard_in(monkeypatch):
    _reply(
        monkeypatch,
        {"companies": [{"name": "Kaynes Technology", "said": "कायन्स टेक्नोलॉजी के बारे में"}]},
    )
    got = spoken.names_in(HINDI)
    assert [n.name for n in got] == ["Kaynes Technology"]
    assert got[0].said == "कायन्स टेक्नोलॉजी के बारे में"


def test_a_quote_that_is_not_in_the_transcript_takes_its_name_down_with_it(monkeypatch):
    """⚠ The echo gate, the same one `judgement` uses on a checklist verdict. A model
    answering from what it expects an Indian market video to contain writes fluent, plausible
    quotes that are not there — and on a transcript this is the only available check that it
    read the document rather than its own expectations."""
    _reply(
        monkeypatch,
        {
            "companies": [
                {"name": "Reliance Industries", "said": "रिलायंस इंडस्ट्रीज़ का शेयर"},
                {"name": "Kaynes Technology", "said": "कायन्स टेक्नोलॉजी के बारे में"},
            ]
        },
    )
    assert [n.name for n in spoken.names_in(HINDI)] == ["Kaynes Technology"]


def test_a_provider_failure_reads_as_no_names_read_not_as_a_quiet_video(monkeypatch):
    async def boom(_text):
        raise RuntimeError("provider down")

    monkeypatch.setattr(spoken, "_ask", boom)
    assert spoken.names_in(HINDI) == []


def test_a_model_that_lists_eighty_companies_is_capped(monkeypatch):
    """A model asked for "every company mentioned" in a market round-up will happily list
    eighty, and eighty names from one video would swamp the denominator the attribution
    measure divides by."""
    said = HINDI[:20]
    _reply(
        monkeypatch,
        {"companies": [{"name": f"Company {i}", "said": said} for i in range(80)]},
    )
    assert len(spoken.names_in(HINDI)) == spoken.MAX_NAMES


def test_a_two_character_quote_proves_nothing_and_is_refused(monkeypatch):
    _reply(monkeypatch, {"companies": [{"name": "Kaynes Technology", "said": "आज"}]})
    assert spoken.names_in(HINDI) == []


def test_malformed_json_is_not_a_crash(monkeypatch):
    async def junk(_text):
        raise json.JSONDecodeError("no", "", 0)

    monkeypatch.setattr(spoken, "_ask", junk)
    assert spoken.names_in(HINDI) == []


# --- and the boundary that makes all of the above safe ----------------------------------------


@pytest.fixture
def channel(db):
    source = reading.register(
        db,
        kind="YOUTUBE",
        name="A channel",
        handle="UCtest",
        trust_tier=reading.COMMENTARY,
        approved=True,
    )
    db.commit()
    return source


def _video(vid="abc123", title="बाजार की बात"):
    return feeds.Item(
        external_id=f"yt:{vid}",
        title=title,
        url=f"https://www.youtube.com/watch?v={vid}",
        published_at=None,
        body="",
        feed="youtube",
    )


def _captions(text, *, language="hi", matchable=False):
    return transcript.Transcript(
        text=text,
        language=language,
        is_auto=True,
        is_matchable=matchable,
        words=len(text.split()),
    )


def test_a_hindi_video_names_a_company_the_matcher_could_not_have_seen(db, channel, monkeypatch):
    """The whole point. A Devanagari transcript matches nothing deterministically, and "in
    Hindi" and "named nobody" are different findings."""
    make_instrument(
        db,
        symbol="KAYNES",
        exchange="NSE",
        name="Kaynes Technology India",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.commit()

    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_video()])
    monkeypatch.setattr(reading, "_spoken_words", lambda source, item, c: _captions(HINDI))
    monkeypatch.setattr(reading, "stances_for", lambda text, symbols: {})
    _reply(
        monkeypatch,
        {"companies": [{"name": "Kaynes Technology", "said": "कायन्स टेक्नोलॉजी के बारे में"}]},
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.names == ["KAYNES"]
    mention = db.execute(sa.select(Mention)).scalar_one()
    assert mention.claim_excerpt == "कायन्स टेक्नोलॉजी के बारे में", (
        "the excerpt quotes the ORIGINAL words, not the transliteration — an excerpt is "
        "there so a person can check what was said"
    )


def test_a_company_the_model_invented_is_matched_against_the_exchange_and_found_in_none(
    db, channel, monkeypatch
):
    """⚠ The boundary. The model hands back strings; the exchange's register decides what a
    company is. A hallucinated name is checked against the real list exactly as a misheard one
    would be, so a language model can never write a row into the table the attribution measure
    counts."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_video()])
    monkeypatch.setattr(reading, "_spoken_words", lambda source, item, c: _captions(HINDI))
    _reply(
        monkeypatch,
        {"companies": [{"name": "Kaynes Technology", "said": "कायन्स टेक्नोलॉजी के बारे में"}]},
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.mentions == 0, "no such company is listed, so nothing was named"
    assert result.stored == 1, "and the video is still on record as having been published"


def test_an_english_transcript_never_reaches_the_model_at_all(db, channel, monkeypatch):
    """⚠ Cost and safety at once. An English video is matched deterministically, which keeps
    the model off the path that produces most of the evidence."""
    called = []

    async def spy(text):
        called.append(text)
        return {"companies": []}

    monkeypatch.setattr(spoken, "_ask", spy)
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_video(title="Market talk")])
    monkeypatch.setattr(
        reading,
        "_spoken_words",
        lambda source, item, c: _captions("a video about bonds", language="en", matchable=True),
    )

    reading.poll(db, channel)
    db.commit()
    assert called == []


def test_every_video_records_whether_its_words_could_be_read(db, channel, monkeypatch):
    """⚠ Absent metadata and "there was nothing to read" are the same shape in JSON, and
    telling a video nobody could read from a video that named nobody is the entire reason
    this is recorded."""
    monkeypatch.setattr(reading, "_fetch", lambda source, c: [_video()])
    monkeypatch.setattr(reading, "_spoken_words", lambda source, item, c: None)

    reading.poll(db, channel)
    db.commit()

    row = db.execute(sa.select(SourceItem)).scalar_one()
    assert row.extraction["transcript"] == {"read": False}
