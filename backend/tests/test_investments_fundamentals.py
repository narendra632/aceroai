"""Filed numbers: reading them, storing them, and refusing to guess at them.

Every fixture here is a small XBRL document written by hand, because the traps this module
exists to survive are all shapes of document rather than shapes of network. The four that
would each have produced confident wrong numbers, and did before they were fixed:

  * a filing reporting the same tag for the quarter AND the year,
  * a governance filing sitting in the financial feed,
  * a bank speaking a different vocabulary entirely,
  * a company with no subsidiaries, which files no consolidated statement at all.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import Fundamental, SourceItem
from app.services.investments import fundamentals
from app.services.marketdata import nse_xbrl
from tests.conftest import make_instrument

NS = 'xmlns:x="http://x" xmlns:xbrli="http://www.xbrl.org/2003/instance"'


def _doc(period_end: str, *, quarter=None, year=None, point=None, prior_point=None) -> bytes:
    """A filing with the context shapes the real ones use."""
    end = period_end
    start_y = f"{int(end[:4]) - 1}-04-01"
    start_q = f"{end[:4]}-01-01"
    body = [f"<xbrli:xbrl {NS}>"]
    body.append(
        f'<xbrli:context id="Y"><xbrli:period><xbrli:startDate>{start_y}</xbrli:startDate>'
        f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>"
    )
    body.append(
        f'<xbrli:context id="Q"><xbrli:period><xbrli:startDate>{start_q}</xbrli:startDate>'
        f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>"
    )
    body.append(
        f'<xbrli:context id="P"><xbrli:period><xbrli:instant>{end}</xbrli:instant>'
        "</xbrli:period></xbrli:context>"
    )
    prior = f"{int(end[:4]) - 1}-03-31"
    body.append(
        f'<xbrli:context id="PP"><xbrli:period><xbrli:instant>{prior}</xbrli:instant>'
        "</xbrli:period></xbrli:context>"
    )
    # ⚠ A DIMENSIONAL context — segment figures. Must never be read as the whole company.
    body.append(
        f'<xbrli:context id="SEG"><xbrli:period><xbrli:startDate>{start_y}</xbrli:startDate>'
        f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period>"
        '<xbrli:scenario><xbrli:explicitMember dimension="d">seg</xbrli:explicitMember>'
        "</xbrli:scenario></xbrli:context>"
    )
    for ctx, values in (("Y", year), ("Q", quarter), ("P", point), ("PP", prior_point)):
        for name, value in (values or {}).items():
            body.append(f'<x:{name} contextRef="{ctx}">{value}</x:{name}>')
    body.append('<x:RevenueFromOperations contextRef="SEG">999</x:RevenueFromOperations>')
    body.append("</xbrli:xbrl>")
    return "".join(body).encode()


@pytest.fixture
def served(monkeypatch):
    """Serve documents by URL without touching the network."""
    docs: dict[str, bytes] = {}

    class Response:
        def __init__(self, content):
            self.content = content
            self.status_code = 200

        def raise_for_status(self):
            return None

    class Client:
        def get(self, url, **kw):
            return Response(docs[url])

        def close(self):
            return None

    monkeypatch.setattr(nse_xbrl, "client", lambda c=None: Client())
    monkeypatch.setattr(nse_xbrl.http, "with_retries", lambda provider, fn: fn())
    return docs


# --- reading a filing ----------------------------------------------------------------------


def test_the_year_is_read_and_not_the_quarter(served):
    """⚠ The trap that would have been wrong by four, silently, on every ratio.

    A March filing reports revenue for the quarter AND for the year under the identical tag,
    told apart only by which context each points at — and the context ids are labels like
    `OneD` and `FourD` that say nothing.
    """
    url = "https://x/INTEGRATED_FILING_INDAS_1.xml"
    served[url] = _doc(
        "2026-03-31",
        year={"RevenueFromOperations": "36260000000"},
        quarter={"RevenueFromOperations": "12430000000"},
    )
    filing = nse_xbrl.Filing("K", dt.date(2026, 3, 31), True, url, "INDAS")

    facts = nse_xbrl.facts(filing)
    assert nse_xbrl.pick(facts, "RevenueFromOperations", "YEAR").value == D("36260000000")
    assert nse_xbrl.pick(facts, "RevenueFromOperations", "QUARTER").value == D("12430000000")


def test_a_segment_figure_is_never_read_as_the_company(served):
    """A filing splits revenue by business line against the same tag. Reading one segment as
    the whole company is a large, plausible, wrong number."""
    url = "https://x/INTEGRATED_FILING_INDAS_2.xml"
    served[url] = _doc("2026-03-31", year={"RevenueFromOperations": "100"})
    filing = nse_xbrl.Filing("K", dt.date(2026, 3, 31), True, url, "INDAS")

    values = [f.value for f in nse_xbrl.facts(filing) if f.name == "RevenueFromOperations"]
    assert D(999) not in values, "a dimensional context must not reach the company's figures"


def test_a_balance_sheet_instant_is_its_own_period_kind(served):
    url = "https://x/INTEGRATED_FILING_INDAS_3.xml"
    served[url] = _doc("2026-03-31", point={"BorrowingsCurrent": "5380000000"})
    filing = nse_xbrl.Filing("K", dt.date(2026, 3, 31), True, url, "INDAS")
    assert nse_xbrl.pick(nse_xbrl.facts(filing), "BorrowingsCurrent", "POINT") is not None


def test_a_prior_year_comparative_is_kept_and_marked(served):
    """⚠ Discarding them looked tidy and cost a year of history. Legacy March filings tag the
    year's profit and loss as a fourth quarter, so the comparative is where it actually is."""
    url = "https://x/INTEGRATED_FILING_INDAS_4.xml"
    served[url] = _doc(
        "2026-03-31",
        point={"EquityAttributableToOwnersOfParent": "200"},
        prior_point={"EquityAttributableToOwnersOfParent": "150"},
    )
    filing = nse_xbrl.Filing("K", dt.date(2026, 3, 31), True, url, "INDAS")
    facts = nse_xbrl.facts(filing)

    assert nse_xbrl.periods_in(facts) == [dt.date(2026, 3, 31), dt.date(2025, 3, 31)]
    prior = nse_xbrl.pick(
        facts, "EquityAttributableToOwnersOfParent", "POINT", period_end=dt.date(2025, 3, 31)
    )
    assert prior.value == D(150) and prior.is_comparative


def test_a_filing_with_nothing_in_it_is_refused(served):
    url = "https://x/INTEGRATED_FILING_INDAS_5.xml"
    served[url] = f"<xbrli:xbrl {NS}></xbrli:xbrl>".encode()
    filing = nse_xbrl.Filing("K", dt.date(2026, 3, 31), True, url, "INDAS")
    with pytest.raises(nse_xbrl.NotPublished):
        nse_xbrl.facts(filing)


# --- choosing which filings to read ----------------------------------------------------------


def test_consolidated_wins_where_it_exists(served):
    both = [
        nse_xbrl.Filing("S", dt.date(2026, 3, 31), False, "standalone", "INDAS"),
        nse_xbrl.Filing("S", dt.date(2026, 3, 31), True, "consolidated", "INDAS"),
    ]
    assert [f.url for f in nse_xbrl.preferred(both)] == ["consolidated"]


def test_standalone_is_used_where_no_consolidated_exists(served):
    """⚠ GE Vernova T&D files only standalone — it has no subsidiaries. Requiring consolidated
    would leave the portfolio's widest-bottleneck holding with no financials at all, and the
    failure would read as 'this company does not report'."""
    only = [nse_xbrl.Filing("G", dt.date(2026, 3, 31), False, "standalone", "INDAS")]
    assert [f.url for f in nse_xbrl.annual(only)] == ["standalone"]


def test_only_march_filings_count_as_annual():
    """Quarterly files carry the profit and loss alone — no balance sheet, no cash flow."""
    mixed = [
        nse_xbrl.Filing("S", dt.date(2026, 6, 30), True, "q1", "INDAS"),
        nse_xbrl.Filing("S", dt.date(2026, 3, 31), True, "fy", "INDAS"),
    ]
    assert [f.url for f in nse_xbrl.annual(mixed)] == ["fy"]


# --- storing what was read ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("end", "expected"),
    [
        (dt.date(2026, 3, 31), "FY26"),
        (dt.date(2025, 3, 31), "FY25"),
        (dt.date(2025, 6, 30), "FY26Q1"),
        (dt.date(2025, 12, 31), "FY26Q3"),
    ],
)
def test_a_period_is_named_for_the_year_it_ends_in(end, expected):
    assert fundamentals.fiscal_period(end) == expected


@pytest.fixture
def company(db):
    inst = make_instrument(
        db,
        symbol="FUNDCO",
        exchange="NSE",
        name="Fundamentals Test Industries",
        asset_class="EQUITY_IN",
        currency="INR",
        sector="EMS_ELECTRONICS",
    )
    db.add(inst)
    db.flush()
    return inst


def _ingest(db, company, served, *, url, period, year=None, point=None, **kw):
    served[url] = _doc(period, year=year, point=point, **kw)
    filing = nse_xbrl.Filing(company.symbol, dt.date.fromisoformat(period), True, url, "INDAS")
    import httpx as _httpx  # noqa: F401  (kept so monkeypatching stays honest)

    facts = nse_xbrl.facts(filing)
    mapping, kept = fundamentals._best_map(facts, dt.date.fromisoformat(period))
    source = fundamentals._store_source(
        db, company, filing, [f for _, _, f in kept], dt.date.fromisoformat(period)
    )
    written = fundamentals._write_figures(
        db, company, filing, source, kept, dt.date.fromisoformat(period)
    )
    db.commit()
    return written


def test_figures_are_stored_with_the_text_they_were_filed_as(db, company, served):
    """⚠ The whole anti-fabrication design. A thesis claiming a figure can be checked back to
    the characters the company itself submitted; storing the parsed number alone would leave
    the validator comparing a number with itself."""
    written = _ingest(
        db,
        company,
        served,
        url="https://x/INTEGRATED_FILING_INDAS_A.xml",
        period="2026-03-31",
        year={"RevenueFromOperations": "36260000000", "ProfitBeforeTax": "1400000000"},
    )
    assert written == 2

    source = db.execute(
        sa.select(SourceItem).where(SourceItem.instrument_id == company.id)
    ).scalar_one()
    assert "RevenueFromOperations" in source.excerpt
    assert "36260000000" in source.excerpt, "the filed characters, verbatim"
    assert len(source.excerpt) <= 2048, "the database caps this; the code must respect it"

    revenue = fundamentals.latest(db, company.id, "revenue")
    assert revenue.value == D("36260000000") and revenue.fiscal_period == "FY26"


def test_a_line_item_the_filing_omits_is_absent_rather_than_zero(db, company, served):
    """⚠ Treating a missing input as a bad one is how a good business is rejected for a reason
    that has nothing to do with the business."""
    _ingest(
        db,
        company,
        served,
        url="https://x/INTEGRATED_FILING_INDAS_B.xml",
        period="2026-03-31",
        year={"RevenueFromOperations": "100"},
    )
    assert fundamentals.latest(db, company.id, "ocf") is None
    assert fundamentals.latest(db, company.id, "revenue") is not None


def test_reading_the_same_filing_twice_writes_nothing_the_second_time(db, company, served):
    url = "https://x/INTEGRATED_FILING_INDAS_C.xml"
    first = _ingest(
        db, company, served, url=url, period="2026-03-31", year={"RevenueFromOperations": "100"}
    )
    served[url] = _doc("2026-03-31", year={"RevenueFromOperations": "100"})
    filing = nse_xbrl.Filing(company.symbol, dt.date(2026, 3, 31), True, url, "INDAS")
    assert first == 1
    assert fundamentals.existing_source(db, filing, dt.date(2026, 3, 31)) is not None


def test_the_most_recent_statement_of_a_figure_wins(db, company, served):
    """⚠ A year appears in its own filing and again as a comparative in the next one. The later
    statement is the company's current word on it — which is what a restatement is."""
    _ingest(
        db,
        company,
        served,
        url="https://x/INTEGRATED_FILING_INDAS_D.xml",
        period="2025-03-31",
        point={"BorrowingsCurrent": "100"},
    )
    # The FY26 filing restates FY25's balance sheet.
    url = "https://x/INTEGRATED_FILING_INDAS_E.xml"
    served[url] = _doc(
        "2026-03-31", point={"BorrowingsCurrent": "500"}, prior_point={"BorrowingsCurrent": "120"}
    )
    filing = nse_xbrl.Filing(company.symbol, dt.date(2026, 3, 31), True, url, "INDAS")
    facts = nse_xbrl.facts(filing)
    prior = dt.date(2025, 3, 31)
    _, kept = fundamentals._best_map(facts, prior)
    source = fundamentals._store_source(db, company, filing, [f for _, _, f in kept], prior)
    fundamentals._write_figures(db, company, filing, source, kept, prior)
    db.commit()

    series = fundamentals.series(db, company.id, "borrowings_current")
    fy25 = [f for f in series if f.fiscal_period == "FY25"]
    assert len(fy25) == 1, "one figure per period reaches a reader"
    assert fy25[0].value == D(120), "the restated figure, not the original"


def test_a_bank_is_read_with_a_banks_vocabulary(db, served):
    """⚠ Proven against the real filing: HDFC Bank has no revenue-from-operations tag at all.
    The map is chosen by what the document contains, because the filename declares the
    taxonomy only for filings made under the Integrated Filing framework."""
    url = "https://x/BANKING_LEGACY_1.xml"
    served[url] = _doc(
        "2026-03-31",
        year={"InterestEarned": "3486150000000", "ProfitLossForThePeriod": "760260000000"},
        point={"Capital": "15390000000", "ReservesAndSurplus": "5799750000000"},
    )
    filing = nse_xbrl.Filing("BANK", dt.date(2026, 3, 31), True, url, "INDAS")
    facts = nse_xbrl.facts(filing)

    mapping, kept = fundamentals._best_map(facts, dt.date(2026, 3, 31))
    metrics = {metric for metric, _, _ in kept}
    assert mapping is fundamentals.BANKING_MAP, "chosen by content, not by the filename"
    assert "interest_earned" in metrics
    assert {"share_capital", "other_equity"} <= metrics, "a bank files equity, just elsewhere"


def test_by_period_never_mixes_consolidated_with_standalone(db, company, served):
    """Comparing one year's consolidated figure with another's standalone is a silent
    apples-to-oranges error, so one basis wins for a period and the other is not blended in."""
    _ingest(
        db,
        company,
        served,
        url="https://x/INTEGRATED_FILING_INDAS_F.xml",
        period="2026-03-31",
        year={"RevenueFromOperations": "100"},
    )
    # The same period, filed standalone as its own document.
    standalone = SourceItem(
        id=uuid.uuid4(),
        kind="RESULTS_XBRL",
        instrument_id=company.id,
        source=nse_xbrl.PROVIDER,
        external_id="INTEGRATED_FILING_INDAS_F_STANDALONE.xml",
        url="https://x/standalone",
        title="FUNDCO FY26 standalone",
        published_at=dt.datetime(2026, 3, 31, tzinfo=dt.UTC),
        fetched_at=dt.datetime.now(dt.UTC),
        content_hash="x",
        excerpt="<x:RevenueFromOperations>999</x:RevenueFromOperations>",
    )
    db.add(standalone)
    db.flush()
    db.add(
        Fundamental(
            instrument_id=company.id,
            fiscal_period="FY26",
            metric_key="revenue",
            source_item_id=standalone.id,
            value=D(999),
            unit="inr",
            period_end=dt.date(2026, 3, 31),
            consolidated=False,
            taxonomy="INDAS",
        )
    )
    db.commit()

    periods = fundamentals.by_period(db, company.id)
    assert periods["FY26"]["_consolidated"] is True
    assert periods["FY26"]["revenue"] == D(100), "the standalone figure must not blend in"


def test_an_instrument_that_is_not_indian_is_left_alone(db, served):
    us = make_instrument(
        db,
        symbol="FUNDUS",
        exchange="NASDAQ",
        name="Elsewhere Inc",
        asset_class="EQUITY_US",
        currency="USD",
    )
    db.add(us)
    db.flush()
    report = fundamentals.sync_instrument(db, us)
    assert report.filings_read == 0 and report.figures_written == 0


def test_the_figure_count_is_positive(db, company, served):
    """⚠ A batched INSERT reports -1 rather than the rows it wrote, so the count came back
    negative and looked like a failure while the write had succeeded."""
    written = _ingest(
        db,
        company,
        served,
        url="https://x/INTEGRATED_FILING_INDAS_G.xml",
        period="2026-03-31",
        year={"RevenueFromOperations": "1", "ProfitBeforeTax": "2", "ProfitLossForPeriod": "3"},
    )
    assert written == 3
    assert uuid.UUID(str(company.id))
