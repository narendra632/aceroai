"""Gap filling, live refresh and corporate actions, against the database — no network.

One `httpx.MockTransport` stands in for every source at once, routing by host. Each test
controls exactly which days each source can supply, and asserts on what was written.

The clock is fixed: trades on Monday 7 Sep 2026, "now" is Friday 11 Sep at 20:00 IST — after
NSE's close and before the US one.
"""

import datetime as dt
import io
import json
import uuid
import zipfile
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import httpx
import pytest
import sqlalchemy as sa

from app.config import settings
from app.db.models import FxObservation, Portfolio, PriceObservation, Transaction
from app.jobs import prices as price_jobs
from app.services.investments import history, pricing
from app.services.marketdata import feed, http, nse
from tests.conftest import make_instrument

IST = ZoneInfo("Asia/Kolkata")
MONDAY = dt.date(2026, 9, 7)
NOW = dt.datetime(2026, 9, 11, 20, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "coingecko_api_key", "CG-test")
    monkeypatch.setattr(settings, "twelve_data_api_key", "td-test")
    monkeypatch.setattr(feed, "FILE_PAUSE", 0)


@pytest.fixture
def book(db, user):
    inst = {
        "NSE": make_instrument(
            db,
            symbol="PYTNSE",
            exchange="NSE",
            name="Pytest Industries India",
            asset_class="EQUITY_IN",
            currency="INR",
        ),
        "MF": make_instrument(
            db,
            symbol="PYTFUND",
            exchange="MF_IN",
            name="Pytest Fund Direct Growth",
            asset_class="MF_IN",
            currency="INR",
            amfi_scheme_code="999001",
        ),
        "US": make_instrument(
            db,
            symbol="PYTUS",
            exchange="NASDAQ",
            name="Pytest Stateside",
            asset_class="EQUITY_US",
            currency="USD",
        ),
        "COIN": make_instrument(
            db,
            symbol="PYTCOIN",
            exchange="CRYPTO",
            name="Pytestcoin",
            asset_class="CRYPTO",
            currency="INR",
            coingecko_id="pytcoin",
        ),
    }
    portfolio = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-feed", kind="REAL")
    db.add(portfolio)
    db.flush()
    for key, price, fx in (
        ("NSE", "100", "1"),
        ("MF", "50", "1"),
        ("US", "10", "95"),
        ("COIN", "5", "1"),
    ):
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=portfolio.id,
                instrument_id=inst[key].id,
                txn_type="BUY",
                trade_date=MONDAY,
                quantity=D("2"),
                price=D(price),
                currency=inst[key].currency,
                fx_rate_inr=D(fx),
                entry_source="IMPORT",
            )
        )
    db.commit()
    portfolio.instruments = inst
    return portfolio


class Sources:
    """Every provider, faked. Tests adjust the attributes to shape what each will say."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        #: day -> "ok" | "404" | "500"; days not listed are "ok".
        self.bhav: dict[dt.date, str] = {}
        self.coingecko_fails = False
        #: USDT close Binance reports for every day.
        self.binance_close = "0.5"

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def seen(self, fragment: str) -> list[httpx.Request]:
        return [r for r in self.requests if fragment in str(r.url)]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if "BhavCopy" in url:
            day = dt.datetime.strptime(url.split("_0_0_0_")[1][:8], "%Y%m%d").date()
            mode = self.bhav.get(day, "ok")
            if mode != "ok":
                return httpx.Response(int(mode))
            price = 100 + day.day  # a different close each day
            csv = (
                "TradDt,FinInstrmId,ISIN,TckrSymb,SctySrs,ClsPric\n"
                f"{day},55555,INE000PYT001,PYTNSE,EQ,{price}.50\n"
            )
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("b.csv", csv)
            return httpx.Response(200, content=buf.getvalue())
        if "mfapi" in url:
            rows = [{"date": f"{d:02d}-09-2026", "nav": f"{50 + d:.3f}"} for d in range(7, 12)]
            return self._json({"data": rows})
        if "binance" in url:
            since = int(request.url.params["startTime"]) // 1000
            until = int(request.url.params["endTime"]) // 1000
            day = dt.datetime.fromtimestamp(since, dt.UTC)
            rows = []
            while day.timestamp() <= until:
                rows.append([int(day.timestamp() * 1000), "0", "0", "0", self.binance_close])
                day += dt.timedelta(days=1)
            return self._json(rows)
        if (
            "twelvedata" in url
            and "time_series" in url
            and request.url.params.get("start_date", "9999") < "2026-01-01"
        ):
            # A long USD/INR history, for converting Binance's USDT closes: ₹84 flat.
            first = dt.date.fromisoformat(request.url.params["start_date"])
            days = (dt.date(2026, 9, 11) - first).days
            return self._json(
                {
                    "values": [
                        {"datetime": str(first + dt.timedelta(days=i)), "close": "84"}
                        for i in range(days)
                    ]
                }
            )
        if "twelvedata" in url and "time_series" in url:
            if "USD" in url:
                days = range(7, 12)  # includes Friday 11th — still trading, must be dropped
                return self._json(
                    {
                        "values": [
                            {"datetime": f"2026-09-{d:02d}", "close": f"95.{d:02d}"} for d in days
                        ]
                    }
                )
            return self._json(
                {
                    "values": [
                        {"datetime": f"2026-09-{d:02d}", "close": f"1{d}.25"} for d in range(7, 12)
                    ]
                }
            )
        if "twelvedata" in url and "quote" in url:
            return self._json({"close": "19.5", "datetime": "2026-09-11", "is_market_open": True})
        if "coingecko" in url and "market_chart" in url:
            if self.coingecko_fails:
                return httpx.Response(503)
            base = dt.datetime(2026, 9, 7, tzinfo=dt.UTC)
            pts = [
                [int((base + dt.timedelta(days=i)).timestamp() * 1000), 5.0 + i] for i in range(5)
            ]
            return self._json({"prices": pts})
        if "coingecko" in url and "simple/price" in url:
            if self.coingecko_fails:
                return httpx.Response(503)
            return self._json({"pytcoin": {"inr": 6.25, "last_updated_at": int(NOW.timestamp())}})
        if "amfiindia" in url:
            return httpx.Response(200, text="999001;X;-;Pytest Fund;55.5;11-Sep-2026\n")
        return httpx.Response(404)

    @staticmethod
    def _json(body) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode())


@pytest.fixture
def sources(monkeypatch):
    s = Sources()
    monkeypatch.setattr(http, "client", s.client)
    return s


def observations(db, inst, source=None):
    stmt = sa.select(PriceObservation).where(PriceObservation.instrument_id == inst.id)
    if source:
        stmt = stmt.where(PriceObservation.source == source)
    return db.execute(stmt.order_by(PriceObservation.observed_at)).scalars().all()


# --- NSE ----------------------------------------------------------------------------------


def test_every_weekday_since_the_first_trade_gets_a_close(db, book, sources):
    feed.fill_closes(db, ("NSE",), now=NOW)
    rows = observations(db, book.instruments["NSE"])
    assert [r.observed_at.astimezone(IST).date() for r in rows] == [
        MONDAY + dt.timedelta(days=i) for i in range(5)
    ]
    assert rows[0].price == D("107.50") and rows[0].source == "NSE" and rows[0].kind == "CLOSE"


def test_a_close_is_stamped_when_the_market_closed(db, book, sources):
    """Stamped 15:30 IST on its day: at midnight it would read as nine hours older than it is,
    and the value curve would file it on the wrong day in some timezone."""
    feed.fill_closes(db, ("NSE",), now=NOW)
    first = observations(db, book.instruments["NSE"])[0]
    assert first.observed_at.astimezone(IST) == dt.datetime(2026, 9, 7, 15, 30, tzinfo=IST)


def test_the_exchange_file_teaches_the_token_and_isin(db, book, sources):
    feed.fill_closes(db, ("NSE",), now=NOW)
    db.refresh(book.instruments["NSE"])
    assert book.instruments["NSE"].angel_token == "55555"
    assert book.instruments["NSE"].isin == "INE000PYT001"


def test_filling_twice_writes_nothing_the_second_time(db, book, sources):
    feed.fill_closes(db, now=NOW)
    before = len(sources.requests)
    report = feed.fill_closes(db, now=NOW)
    assert sum(report.written.values()) == 0
    assert not sources.seen("BhavCopy")[
        len([r for r in sources.requests[:before] if "BhavCopy" in str(r.url)]) :
    ]


def test_a_holiday_is_skipped_and_not_asked_for_forever(db, book, sources):
    """A 404 day stops being "missing" once a later close exists — no holiday calendar."""
    wednesday = dt.date(2026, 9, 9)
    sources.bhav[wednesday] = "404"
    feed.fill_closes(db, ("NSE",), now=NOW)
    days = [r.observed_at.astimezone(IST).date() for r in observations(db, book.instruments["NSE"])]
    assert wednesday not in days and len(days) == 4

    sources.requests.clear()
    feed.fill_closes(db, ("NSE",), now=NOW + dt.timedelta(days=3))  # the next Monday
    assert not any(wednesday.strftime("%Y%m%d") in str(r.url) for r in sources.requests)


def test_an_unreachable_file_falls_back_to_angel_candles(db, book, sources, monkeypatch):
    for key in ("angel_one_api_key", "angel_one_client_code", "angel_one_mpin"):
        monkeypatch.setattr(settings, key, "x")
    monkeypatch.setattr(settings, "angel_one_totp_secret", "JBSWY3DPEHPK3PXP")
    thursday = dt.date(2026, 9, 10)
    sources.bhav[thursday] = "500"
    # A first run learns the token from the days that did work.
    original = sources.handle

    def with_angel(request):
        path = request.url.path
        if path.endswith("loginByPassword"):
            sources.requests.append(request)
            return Sources._json({"status": True, "data": {"jwtToken": "j"}})
        if path.endswith("getCandleData"):
            sources.requests.append(request)
            return Sources._json(
                {
                    "status": True,
                    "data": [
                        ["2026-09-10T00:00:00+05:30", 1, 1, 1, 110.75, 1],
                    ],
                }
            )
        return original(request)

    sources.handle = with_angel
    report = feed.fill_closes(db, ("NSE",), now=NOW)
    angel = observations(db, book.instruments["NSE"], source="ANGEL_ONE")
    assert [(r.observed_at.astimezone(IST).date(), r.price) for r in angel] == [
        (thursday, D("110.75"))
    ]
    assert report.written["ANGEL_ONE"] == 1


# --- the other sources --------------------------------------------------------------------


def test_fund_navs_are_stamped_on_their_own_date(db, book, sources):
    feed.fill_closes(db, ("MF",), now=NOW)
    rows = observations(db, book.instruments["MF"])
    assert len(rows) == 5 and all(r.kind == "NAV" and r.source == "AMFI" for r in rows)
    assert rows[-1].observed_at.astimezone(IST).date() == dt.date(2026, 9, 11)


def test_an_unfinished_us_session_is_not_stored_as_a_close(db, book, sources):
    """At 20:00 IST Friday, New York is mid-morning: Friday's bar is not a close yet."""
    feed.fill_closes(db, ("US",), now=NOW)
    days = [r.observed_at.date() for r in observations(db, book.instruments["US"])]
    assert days == [dt.date(2026, 9, d) for d in (7, 8, 9, 10)]
    rates = db.execute(sa.select(FxObservation).order_by(FxObservation.observed_at)).scalars().all()
    assert [r.observed_at.date() for r in rates] == [dt.date(2026, 9, d) for d in (7, 8, 9, 10)]
    assert rates[0].rate == D("95.07")


def test_crypto_history_never_asks_past_the_plans_window(db, user, sources):
    """The trade is two years old; the Demo plan refuses more than 365 days."""
    coin = make_instrument(
        db,
        symbol="PYTOLD",
        exchange="CRYPTO",
        name="Old coin",
        asset_class="CRYPTO",
        currency="INR",
        coingecko_id="pytold",
    )
    p = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-old", kind="REAL")
    db.add(p)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=p.id,
            instrument_id=coin.id,
            txn_type="BUY",
            trade_date=dt.date(2024, 9, 1),
            quantity=D("1"),
            price=D("1"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    feed.fill_closes(db, ("CRYPTO",), now=NOW)
    asked = [r for r in sources.seen("market_chart") if "pytold" in str(r.url)]
    assert asked and asked[0].url.params["days"] == "365"


def test_one_failing_source_does_not_stop_the_others(db, book, sources):
    sources.coingecko_fails = True
    report = feed.fill_closes(db, now=NOW)
    assert "CRYPTO" in report.failed
    assert observations(db, book.instruments["NSE"]) and observations(db, book.instruments["MF"])


def test_filled_prices_draw_the_value_line(db, book, sources):
    """The point of all of it: a curve with values, where before there were none."""
    assert all(p.value_inr is None for p in history.curve(db, book.id, until=NOW.date()))
    feed.fill_closes(db, now=NOW)
    points = history.curve(db, book.id, until=NOW.date())
    assert points[0].value_inr is not None


# --- live refresh -------------------------------------------------------------------------


def test_a_fresh_book_makes_no_requests(db, book, sources):
    feed.fill_closes(db, now=NOW)
    feed.refresh_stale(db, now=NOW)  # prices crypto and the rate live
    sources.requests.clear()
    report = feed.refresh_stale(db, now=NOW + dt.timedelta(minutes=5))
    assert sources.requests == []
    assert sum(report.written.values()) == 0


def test_a_stale_price_is_refreshed_live(db, book, sources):
    feed.fill_closes(db, now=NOW)
    later = NOW + dt.timedelta(hours=6)  # crypto's limit is four hours
    feed.refresh_stale(db, now=later)
    mark = pricing.latest(db, [book.instruments["COIN"].id], at=later)[book.instruments["COIN"].id]
    assert mark.price == D("6.25") and mark.source == "COINGECKO"


def test_a_source_that_fails_is_left_alone_for_a_while(db, book, sources):
    """Opening the page twice must not wait out three timeouts twice."""
    sources.coingecko_fails = True
    first = feed.refresh_stale(db, now=NOW)
    assert "COINGECKO" in first.failed
    sources.requests.clear()
    feed.refresh_stale(db, now=NOW)
    assert sources.seen("coingecko") == []


def test_the_page_route_reports_what_it_did(auth_client, db, book, sources):
    r = auth_client.post("/api/investments/prices/refresh")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"written", "failed"}


# --- corporate actions --------------------------------------------------------------------


def _feed_with(monkeypatch, *actions):
    monkeypatch.setattr(price_jobs.nse, "corporate_actions", lambda: list(actions))


def test_a_bonus_on_a_held_stock_is_announced_once(db, user, book, monkeypatch):
    _feed_with(
        monkeypatch,
        nse.CorporateAction("Pytest Industries India Limited", "BONUS 1:1", dt.date(2026, 9, 25)),
    )
    first = price_jobs.corporate_actions_watch(db, user)
    assert first.notify is not None and "PYTNSE" in first.notify.title
    from app.jobs.registry import get
    from app.jobs.runner import _deliver

    _deliver(db, user, get("corporate_actions_watch"), first)
    again = price_jobs.corporate_actions_watch(db, user)
    assert again.notify is None


def test_a_dividend_is_not_announced(db, user, book, monkeypatch):
    _feed_with(
        monkeypatch,
        nse.CorporateAction("Pytest Industries India Limited", "DIVIDEND - RS 5", None),
    )
    assert price_jobs.corporate_actions_watch(db, user).notify is None


def test_a_company_not_held_is_not_announced(db, user, book, monkeypatch):
    _feed_with(monkeypatch, nse.CorporateAction("Someone Else Limited", "BONUS 1:1", None))
    assert price_jobs.corporate_actions_watch(db, user).notify is None


def _old_coin(db, user, bought: dt.date):
    coin = make_instrument(
        db,
        symbol="PYTOLD",
        exchange="CRYPTO",
        name="Old coin",
        asset_class="CRYPTO",
        currency="INR",
        coingecko_id="pytold",
    )
    p = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-old", kind="REAL")
    db.add(p)
    db.flush()
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=p.id,
            instrument_id=coin.id,
            txn_type="BUY",
            trade_date=bought,
            quantity=D("1"),
            price=D("40"),
            currency="INR",
            entry_source="IMPORT",
        )
    )
    db.commit()
    return coin


def test_crypto_older_than_the_window_comes_from_binance_in_rupees(db, user, sources):
    """Every day back to the purchase, at Binance's USDT close × that day's USD/INR."""
    bought = dt.date(2025, 3, 1)
    coin = _old_coin(db, user, bought)
    feed.fill_closes(db, ("CRYPTO",), now=NOW)

    rows = observations(db, coin, source="BINANCE")
    assert rows, "the gap before CoinGecko's window was not filled"
    first = rows[0]
    # Stamped like CoinGecko: the close of 28 Feb at 00:00 UTC on 1 Mar, the purchase day.
    assert first.observed_at == dt.datetime(2025, 3, 1, tzinfo=dt.UTC)
    assert first.price == D("42.000000")  # 0.5 USDT × ₹84
    newer = observations(db, coin, source="COINGECKO")
    assert rows[-1].observed_at.date() == newer[0].observed_at.date() - dt.timedelta(days=1), (
        "the older history must end the day before CoinGecko's begins"
    )
    days = {r.observed_at.date() for r in observations(db, coin)}
    expected = (NOW.astimezone(dt.UTC).date() - bought).days + 1
    assert len(days) == expected, "one close for every day since the purchase, no holes"


def test_the_backfill_stops_asking_once_the_gap_is_closed(db, user, sources):
    _old_coin(db, user, dt.date(2025, 3, 1))
    feed.fill_closes(db, ("CRYPTO",), now=NOW)
    sources.requests.clear()
    feed.fill_closes(db, ("CRYPTO",), now=NOW)
    assert sources.seen("binance") == []


def test_the_value_line_starts_at_the_first_purchase(db, user, sources):
    """The point of the backfill: no chart that begins a year after the money went in."""
    bought = dt.date(2025, 3, 1)
    coin = _old_coin(db, user, bought)
    feed.fill_closes(db, ("CRYPTO",), now=NOW)
    book_id = db.execute(
        sa.select(Transaction.portfolio_id).where(Transaction.instrument_id == coin.id)
    ).scalar_one()
    covered = history.covered_range(history.curve(db, book_id, until=NOW.date()))
    assert covered is not None and covered[0] == bought
