"""Each price adapter against recorded response shapes — no network.

Responses are built on `httpx.MockTransport`, so these exercise the real request
construction (URL, headers, body) and the real parsing. The shapes are the ones the live
probe returned on 2026-09-19 (`openspec/changes/add-market-data/tasks.md` §0).
"""

import csv
import datetime as dt
import io
import json
import re
import zipfile
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.services.marketdata import amfi, angel_one, binance, coingecko, http, nse, twelve_data
from app.services.marketdata.http import ProviderError


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def json_response(body, status=200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode())


# --- the shared layer ---------------------------------------------------------------------


def test_a_client_error_is_not_retried():
    """A wrong key is exactly as wrong a second later; retrying spends the allowance."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    c = mock(handler)
    with pytest.raises(ProviderError, match="HTTP 401"):
        http.with_retries("X", lambda: c.get("https://example.test/").raise_for_status())
    assert len(calls) == 1


def test_a_server_error_is_retried_then_reported():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    c = mock(handler)
    with pytest.raises(ProviderError, match="HTTP 503"):
        http.with_retries("X", lambda: c.get("https://example.test/").raise_for_status())
    assert len(calls) == http.ATTEMPTS


def test_money_is_parsed_as_decimal_never_float():
    """`Decimal(731.1)` is 731.1000000000000227… — the number must never be a float at all."""
    parsed = http.json_decimal(httpx.Response(200, content=b'{"ltp": 731.1}'))
    assert parsed["ltp"] == D("731.1")
    assert isinstance(parsed["ltp"], D)


# --- Angel One ----------------------------------------------------------------------------


@pytest.fixture
def angel_keys(monkeypatch):
    for key, value in (
        ("angel_one_api_key", "k"),
        ("angel_one_client_code", "C1"),
        ("angel_one_mpin", "1234"),
        ("angel_one_totp_secret", "JBSWY3DPEHPK3PXP"),
    ):
        monkeypatch.setattr(settings, key, value)
    angel_one.reset_session()
    yield
    angel_one.reset_session()


def test_the_angel_adapter_names_only_its_three_routes():
    """⚠ The security property of the whole integration: this module cannot place, modify or
    inspect a trade, because it does not know where those routes are. SmartAPI's order,
    holdings, positions and GTT routes all live on the same host as its quotes."""
    source = Path(angel_one.__file__).read_text(encoding="utf-8")
    routes = set(re.findall(r'"(/(?:rest|gtt-service)/[^"]+)"', source))
    assert routes == set(angel_one.ROUTES)
    code = source.split('"""', 2)[2]  # everything after the module docstring
    for forbidden in (
        "placeOrder",
        "modifyOrder",
        "cancelOrder",
        "getHolding",
        "getPosition",
        "gtt",
        "getTradeBook",
        "getOrderBook",
        "convertPosition",
    ):
        assert forbidden not in code, forbidden


def test_the_angel_adapter_refuses_a_route_it_does_not_list(angel_keys):
    with pytest.raises(ProviderError, match="not permitted"):
        angel_one._post(mock(lambda r: json_response({})), "/rest/secure/x/order/v1/placeOrder", {})


def _angel_handler(log, *, quote_first=None):
    def handler(request):
        log.append(request)
        path = request.url.path
        if path.endswith("loginByPassword"):
            return json_response({"status": True, "data": {"jwtToken": f"jwt{len(log)}"}})
        if path.endswith("/quote"):
            if quote_first is not None and not any(r.url.path.endswith("/quote") for r in log[:-1]):
                return json_response(quote_first)
            return json_response(
                {
                    "status": True,
                    "data": {
                        "fetched": [{"symbolToken": "1333", "ltp": 731.05}],
                        "unfetched": [],
                    },
                }
            )
        if path.endswith("getCandleData"):
            return json_response(
                {
                    "status": True,
                    "data": [
                        ["2026-09-17T00:00:00+05:30", 717.5, 719.4, 713.0, 713.0, 1],
                        ["2026-09-18T00:00:00+05:30", 715.25, 733.8, 715.25, 731.0, 1],
                    ],
                }
            )
        return httpx.Response(404)

    return handler


def test_a_quote_is_exact_and_authenticated(angel_keys):
    log = []
    prices = angel_one.quote_ltp(["1333"], mock(_angel_handler(log)))
    assert prices == {"1333": D("731.05")}
    login, quote = log
    body = json.loads(login.content)
    assert body["clientcode"] == "C1" and len(body["totp"]) == 6
    assert quote.headers["Authorization"] == "Bearer jwt1"
    assert quote.headers["X-PrivateKey"] == "k"


def test_a_refused_call_logs_in_again_once(angel_keys):
    """Any refusal, not a list of session codes: a missed code would cache a dead session."""
    log = []
    refused = {"status": False, "errorcode": "AG8001", "message": "Invalid Token"}
    prices = angel_one.quote_ltp(["1333"], mock(_angel_handler(log, quote_first=refused)))
    assert prices == {"1333": D("731.05")}
    assert sum(r.url.path.endswith("loginByPassword") for r in log) == 2


def test_a_session_is_reused_between_calls(angel_keys):
    log = []
    c = mock(_angel_handler(log))
    angel_one.quote_ltp(["1333"], c)
    angel_one.quote_ltp(["1333"], c)
    assert sum(r.url.path.endswith("loginByPassword") for r in log) == 1


def test_candles_keep_the_date_and_not_the_midnight_stamp(angel_keys):
    candles = angel_one.daily_candles(
        "1333", dt.date(2026, 9, 17), dt.date(2026, 9, 18), mock(_angel_handler([]))
    )
    assert candles == [(dt.date(2026, 9, 17), D("713.0")), (dt.date(2026, 9, 18), D("731.0"))]


# --- NSE ----------------------------------------------------------------------------------

BHAV_COLUMNS = ["TradDt", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "ClsPric"]


def bhav_zip(rows: list[dict]) -> bytes:
    text = io.StringIO()
    w = csv.DictWriter(text, fieldnames=BHAV_COLUMNS)
    w.writeheader()
    w.writerows(rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy.csv", text.getvalue())
    return buf.getvalue()


def test_the_bhavcopy_is_read_by_symbol_with_token_and_isin():
    rows = [
        {
            "TckrSymb": "GVT&D",
            "SctySrs": "EQ",
            "ClsPric": "4385.00",
            "FinInstrmId": "16783",
            "ISIN": "INE200A01026",
        },
        {
            "TckrSymb": "NIFTYBEES",
            "SctySrs": "N1",
            "ClsPric": "1.00",
            "FinInstrmId": "1",
            "ISIN": "X",
        },
    ]
    got = nse.bhavcopy(
        dt.date(2026, 9, 18), mock(lambda r: httpx.Response(200, content=bhav_zip(rows)))
    )
    assert set(got) == {"GVT&D"}
    assert got["GVT&D"] == nse.BhavRow("GVT&D", "INE200A01026", "16783", D("4385.00"))


@pytest.mark.parametrize(
    "response",
    [httpx.Response(404), httpx.Response(200, content=b"<html>not here</html>")],
    ids=["404", "html-with-200"],
)
def test_a_missing_bhavcopy_is_not_published_rather_than_failed(response):
    with pytest.raises(nse.NotPublished):
        nse.bhavcopy(dt.date(2026, 9, 19), mock(lambda r: response))


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Kaynes Technology India Limited - Ex-Date: 25-Sep-2026 </title>
<description>SERIES:EQ |PURPOSE:BONUS 1:1 |FACE VALUE:10 |</description></item>
<item><title>HDFC Bank Limited - Ex-Date: 22-Sep-2026 </title>
<description>SERIES:EQ |PURPOSE:DIVIDEND - RS 22 PER SHARE |FACE VALUE:1 |</description></item>
</channel></rss>"""


def test_the_corporate_action_feed_is_parsed():
    actions = nse.corporate_actions(mock(lambda r: httpx.Response(200, content=RSS)))
    assert actions[0] == nse.CorporateAction(
        "Kaynes Technology India Limited", "BONUS 1:1", dt.date(2026, 9, 25)
    )
    assert nse.changes_share_count(actions[0])
    assert not nse.changes_share_count(actions[1])


@pytest.mark.parametrize(
    ("company", "names", "expected"),
    [
        ("Kaynes Technology India Limited", ["Kaynes Technology", "KAYNES"], True),
        ("GE Vernova T&D India Limited", ["GE Vernova T&D India"], True),
        ("HDFC Life Insurance Company Limited", ["HDFC Bank", "HDFCBANK"], False),
        # A short name must not claim every company that starts with it.
        ("Kaynes Anything Limited", ["KAYNES"], False),
    ],
)
def test_company_matching(company, names, expected):
    assert nse.matches_company(nse.CorporateAction(company, "BONUS", None), names) is expected


# --- CoinGecko ----------------------------------------------------------------------------


def test_daily_history_drops_the_trailing_live_point(monkeypatch):
    monkeypatch.setattr(settings, "coingecko_api_key", "CG-x")
    midnight = int(dt.datetime(2026, 9, 18, tzinfo=dt.UTC).timestamp() * 1000)
    live = midnight + 37_000_000
    seen = []

    def handler(request):
        seen.append(request)
        return json_response({"prices": [[midnight, 7795820.5], [live, 7801000.0]]})

    points = coingecko.daily_history("bitcoin", 9999, mock(handler))
    assert points == [(dt.datetime(2026, 9, 18, tzinfo=dt.UTC), D("7795820.5"))]
    assert seen[0].url.params["days"] == "365", "the plan refuses more than 365"
    assert seen[0].headers["x-cg-demo-api-key"] == "CG-x"


def test_search_prefers_the_largest_coin_with_that_ticker(monkeypatch):
    monkeypatch.setattr(settings, "coingecko_api_key", "CG-x")
    body = {
        "coins": [
            {"id": "jasmy-fake", "symbol": "JASMY", "market_cap_rank": None},
            {"id": "jasmycoin", "symbol": "JASMY", "market_cap_rank": 180},
            {"id": "other", "symbol": "JAS", "market_cap_rank": 5},
        ]
    }
    assert coingecko.search_id("jasmy", mock(lambda r: json_response(body))) == "jasmycoin"


# --- Twelve Data --------------------------------------------------------------------------


def test_an_error_inside_a_200_is_still_an_error(monkeypatch):
    """Twelve Data reports rate limits as HTTP 200 with status "error" in the body."""
    monkeypatch.setattr(settings, "twelve_data_api_key", "td")
    body = {"code": 429, "status": "error", "message": "run out of API credits"}
    with pytest.raises(ProviderError, match="429"):
        twelve_data.quote("SPCX", mock(lambda r: json_response(body)))


def test_the_key_travels_in_a_header_never_the_url(monkeypatch):
    monkeypatch.setattr(settings, "twelve_data_api_key", "secret-td")
    seen = []

    def handler(request):
        seen.append(request)
        return json_response(
            {"close": "152.71001", "datetime": "2026-09-18", "is_market_open": False}
        )

    q = twelve_data.quote("SPCX", mock(handler))
    assert q == twelve_data.Quote(D("152.71001"), dt.date(2026, 9, 18), False)
    assert "secret-td" not in str(seen[0].url)
    assert seen[0].headers["Authorization"] == "apikey secret-td"


# --- AMFI ---------------------------------------------------------------------------------


def test_navall_is_parsed_from_both_ends_of_the_line():
    """The scheme name has been seen split across fields; count from the ends."""
    text = (
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;"
        "Net Asset Value;Date\n"
        "118989;INF179K01XQ0;-;HDFC Mid Cap Fund;Direct Plan;Growth Option;231.413;18-Sep-2026\n"
        "118955;INF179K01UT0;-;HDFC Flexi Cap Fund - Direct Growth;N.A.;18-Sep-2026\n"
    )
    navs = amfi.latest_navs({"118989", "118955"}, mock(lambda r: httpx.Response(200, text=text)))
    assert navs == {"118989": (D("231.413"), dt.date(2026, 9, 18))}


def test_nav_history_is_filtered_to_the_start_and_sorted():
    body = {
        "data": [
            {"date": "18-09-2026", "nav": "231.41300"},
            {"date": "17-09-2026", "nav": "230.00000"},
            {"date": "10-09-2026", "nav": "229.00000"},
        ]
    }
    got = amfi.nav_history("118989", dt.date(2026, 9, 15), mock(lambda r: json_response(body)))
    assert got == [(dt.date(2026, 9, 17), D("230.00000")), (dt.date(2026, 9, 18), D("231.41300"))]


# --- Binance ------------------------------------------------------------------------------


def test_binance_closes_are_paged_and_keep_the_candles_own_day():
    """1,000 candles per page; a full page means ask again from the day after the last."""
    day0 = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    pages = []

    def handler(request):
        since = dt.datetime.fromtimestamp(int(request.url.params["startTime"]) / 1000, dt.UTC)
        pages.append(since.date())
        count = 1000 if since == day0 else 3
        rows = [
            [int((since + dt.timedelta(days=i)).timestamp() * 1000), "1", "1", "1", f"0.{i + 1}"]
            for i in range(count)
        ]
        return json_response(rows)

    closes = binance.daily_closes("DOGEUSDT", day0.date(), dt.date(2026, 12, 31), mock(handler))
    assert pages == [dt.date(2024, 1, 1), dt.date(2024, 1, 1) + dt.timedelta(days=1000)]
    assert len(closes) == 1003
    assert closes[0] == (dt.date(2024, 1, 1), D("0.1"))
