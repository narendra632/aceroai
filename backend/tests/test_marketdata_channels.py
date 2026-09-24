"""Adding a channel from whatever a person pasted.

⚠ This exists because the registered channels are measurably the wrong ones — read on
24 Sep 2026, twelve recent uploads across the three named zero NSE-listed companies between
them. A finding about the sources is only useful if the sources can be changed, and requiring
a `UC…` id would make changing them a research task.
"""

import httpx
import pytest

from app.services.marketdata import feeds
from app.services.marketdata import http as md_http
from app.services.marketdata.http import ProviderError

CHANNEL_PAGE = (
    '<html><head><meta property="og:title" content="Yadnya Investment Academy">'
    '</head><body><script>{"externalId":"UCUWbS9qoyLKTdOlvgK1GBlA","x":1}</script></body></html>'
)


@pytest.fixture
def youtube(monkeypatch):
    state = {"body": CHANNEL_PAGE, "urls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["urls"].append(str(request.url))
        return httpx.Response(200, text=state["body"])

    monkeypatch.setattr(
        md_http, "client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(md_http, "BACKOFF", (0.0, 0.0))
    return state


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        ("@Yadnyaa", "https://www.youtube.com/@Yadnyaa"),
        ("Yadnyaa", "https://www.youtube.com/@Yadnyaa"),
        ("https://www.youtube.com/@Yadnyaa", "https://www.youtube.com/@Yadnyaa"),
        ("https://youtube.com/c/Old", "https://youtube.com/c/Old"),
        (
            "UCUWbS9qoyLKTdOlvgK1GBlA",
            "https://www.youtube.com/channel/UCUWbS9qoyLKTdOlvgK1GBlA",
        ),
    ],
)
def test_every_form_a_person_might_paste_resolves(youtube, pasted, expected):
    """Verified against the real site on 24 Sep 2026 for all five forms."""
    channel = feeds.resolve_channel(pasted)
    assert channel.channel_id == "UCUWbS9qoyLKTdOlvgK1GBlA"
    assert channel.title == "Yadnya Investment Academy"
    assert youtube["urls"] == [expected]


def test_a_page_that_is_not_a_channel_says_so_rather_than_looking_like_an_outage(youtube):
    """⚠ A video link, a playlist, a search page and a typo all land here, and they need a
    different fix from a network failure. Naming it as a network problem would send someone
    to check their connection."""
    youtube["body"] = "<html><body>no channel here</body></html>"
    with pytest.raises(ProviderError) as caught:
        feeds.resolve_channel("https://www.youtube.com/watch?v=abc")
    assert caught.value.reason == "that page is not a channel"


def test_nothing_pasted_is_refused_before_a_request_is_made(youtube):
    with pytest.raises(ProviderError):
        feeds.resolve_channel("   ")
    assert youtube["urls"] == []


def test_the_channel_id_is_read_from_either_field_the_page_uses(youtube):
    """`externalId` and `channelId` both appear and are the same value; which one the page
    carries has changed before."""
    youtube["body"] = '<html>{"channelId":"UCjOVNkq-_HY9Q_LQv0FwlqA"}</html>'
    assert feeds.resolve_channel("@x").channel_id == "UCjOVNkq-_HY9Q_LQv0FwlqA"
