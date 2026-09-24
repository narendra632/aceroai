"""Reading the spoken words, and refusing to pretend it worked when it did not.

A title advertises; a transcript reports. Almost everything here is about the difference
between *this video said nothing* and *this video could not be read*, because YouTube's
caption endpoint fails in the one way that looks exactly like success: HTTP 200 with an empty
body. Code that trusted the status line would have filed every video as having no transcript
and every channel as having named nobody.
"""

import json

import httpx
import pytest

from app.services.marketdata import http as md_http
from app.services.marketdata import transcript

PLAYER = "/youtubei/v1/player"


def _player_body(tracks):
    return {
        "playabilityStatus": {"status": "OK"},
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": tracks}},
    }


def _track(lang="en", kind=None, url="https://t.example/cc"):
    row = {"languageCode": lang, "baseUrl": url}
    if kind:
        row["kind"] = kind
    return row


def _json3(*lines):
    return json.dumps({"events": [{"segs": [{"utf8": line}]} for line in lines]})


@pytest.fixture
def youtube(monkeypatch):
    """A fake YouTube. `routes` maps a path fragment to (status, body)."""
    state = {
        "player": _player_body([_track()]),
        "captions": (200, _json3("hello world")),
        "calls": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append(str(request.url))
        if PLAYER in request.url.path:
            body = state["player"]
            if isinstance(body, Exception):
                raise body
            return httpx.Response(200, json=body)
        status, text = state["captions"]
        return httpx.Response(status, text=text)

    monkeypatch.setattr(
        md_http, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(md_http, "BACKOFF", (0.0, 0.0))
    return state


def test_the_spoken_words_are_read(youtube):
    youtube["captions"] = (200, _json3("Kaynes Technology ", "had a strong quarter"))
    got = transcript.fetch("abc123")
    assert got is not None
    assert got.text == "Kaynes Technology had a strong quarter"
    assert got.words == 6
    assert got.is_matchable


def test_a_caption_line_break_does_not_split_a_company_name(youtube):
    """⚠ Caption files wrap mid-sentence. "Kaynes\\nTechnology" is one company written across
    two lines, and a matcher looking for the name would see two words that are not it."""
    youtube["captions"] = (200, _json3("we like Kaynes\n", "Technology a lot"))
    assert "Kaynes Technology" in transcript.fetch("abc123").text


def test_a_two_hundred_with_an_empty_body_is_a_failure_not_a_silent_video(youtube):
    """⚠ The failure mode this module exists against. The old caption route still answers 200
    and serves nothing, and a status check alone would call that success — filing every video
    as captionless and every channel as having named nobody."""
    youtube["captions"] = (200, "")
    assert transcript.fetch("abc123") is None


def test_a_video_with_no_captions_answers_none_rather_than_empty_text(youtube):
    youtube["player"] = _player_body([])
    assert transcript.fetch("abc123") is None


def test_an_unreachable_endpoint_is_none_and_never_an_exception(youtube):
    """⚠ A failed transcript is a thinner reading of one item, not a failed poll of a whole
    channel. The item is still stored, because a video nobody could read must stay countable
    as a video that was published."""
    youtube["player"] = httpx.ConnectError("no", request=httpx.Request("POST", "https://x"))
    assert transcript.fetch("abc123") is None


def test_a_published_track_is_preferred_over_a_machine_transcription(youtube):
    """⚠ Not a quality preference — it decides what a MISS means. Auto-generated Hindi missing
    a company is close to no evidence; a published English transcript missing it is real
    evidence the video did not mention it, and the attribution measure divides by that."""
    youtube["player"] = _player_body(
        [
            _track("hi", "asr", "https://t.example/hi"),
            _track("en", None, "https://t.example/en"),
        ]
    )
    transcript.fetch("abc123")
    assert any("t.example/en" in call for call in youtube["calls"])
    assert not any("t.example/hi" in call for call in youtube["calls"])


def test_a_hindi_transcript_is_read_and_flagged_as_unmatchable(youtube):
    """⚠ Measured on the real channels: both Indian ones publish Devanagari captions. Storing
    them and reporting "named no companies" would be a claim about the video rather than about
    the reader, and the wrong one."""
    youtube["player"] = _player_body([_track("hi", "asr")])
    youtube["captions"] = (200, _json3("आज हम मार्केट करेक्शन पे बात करते हैं"))
    got = transcript.fetch("abc123")
    assert got.language == "hi"
    assert got.is_auto
    assert not got.is_matchable
    assert "not in Latin script" in got.note()


def test_the_note_says_how_much_was_read_and_of_what_kind(youtube):
    youtube["player"] = _player_body([_track("en", "asr")])
    youtube["captions"] = (200, _json3("one two three"))
    assert transcript.fetch("abc123").note() == "3 words of auto-generated en captions"
