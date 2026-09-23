"""When something is written about a theme rather than a company.

A video titled *"Why defence manufacturing is the decade's trade"* names no company at all, so
the mention matcher sees nothing and the item is filed and forgotten. The framework already
knows which chokepoints matter and who sits on each — so a theme is not a dead end, it is a
lookup, and that is the difference between the bottleneck list being a filing cabinet and
being a routing table.

⚠ A theme is never evidence. It raises no proposal and changes no score.
"""

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from app.db.models import AbMapping, Candidate, ListedCompany, SourceItem
from app.services.investments import framework_data, frameworks, reading, themes
from tests.conftest import make_instrument

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    row = frameworks.install(db, spec, approved=True)
    db.commit()
    return row


# --- reading a theme out of text ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Why defence manufacturing matters: ammunition and explosives demand", ["B4.2"]),
        ("The transformer shortage: power transmission capex is the story", ["B1.1"]),
        ("Solar cell and module manufacturing finally has scale in India", ["B1.5"]),
        ("Battery energy storage and cell manufacturing is the next leg", ["B1.2"]),
        ("Data centre and compute infrastructure buildout is accelerating", ["B3.1"]),
    ],
)
def test_a_theme_resolves_to_its_own_bottleneck(spec, text, expected):
    assert themes.themes_in(text, spec) == expected


def test_a_shared_word_does_not_match_the_neighbouring_bottleneck(spec):
    """⚠ The rule that stops a theme matching its neighbour. *Solar Cell & Module
    Manufacturing* and *Battery Energy Storage & Cell Manufacturing* share "cell" and
    "manufacturing", so an article about solar modules matched both — and reporting a battery
    holding as newly relevant to a solar article is the routing table producing noise in the
    one place it is meant to produce precision."""
    found = themes.themes_in("solar cell and module manufacturing", spec)

    assert found == ["B1.5"]
    assert "B1.2" not in found


@pytest.mark.parametrize(
    "text",
    [
        "I paid my electricity bill and the power went out again",
        "A quiet week in the markets with nothing much happening",
        "the manufacturing sector generally had a reasonable quarter",
    ],
)
def test_ordinary_prose_is_about_no_theme(spec, text):
    """⚠ One word is not a theme. "power" appears in an article about anything, and a router
    firing on it would mark every grid holding as newly relevant every day — which is the same
    as reporting nothing."""
    assert themes.themes_in(text, spec) == []


def test_a_distinctive_single_word_may_stand_alone(spec):
    """A one-word bottleneck name can never reach two words, so the few inherently
    distinctive ones are allowed to match by themselves."""
    assert themes.themes_in("Nuclear is back on the table for planners", spec) == ["B1.4"]


# --- what the book is exposed to ---------------------------------------------------------------


def _mapped(db, spec, version, symbol, bottleneck, *, approved=True):
    inst = make_instrument(
        db,
        symbol=symbol,
        exchange="NSE",
        name=f"{symbol} Industries",
        asset_class="EQUITY_IN",
        currency="INR",
    )
    db.add(inst)
    db.flush()
    mapping = frameworks.propose_mapping(
        db,
        inst,
        b_bottleneck=bottleneck,
        spec=spec,
        framework_version_id=version.id,
        proposed_by="AGENT",
    )
    if approved:
        mapping.approved_at = NOW
    db.commit()
    return inst


def test_a_theme_names_what_the_book_already_holds(db, spec, version):
    """⚠ The half that matters most and the half nobody goes looking for."""
    _mapped(db, spec, version, "GRIDCO", "B1.1")

    exposure = themes.exposure_to(db, ["B1.1"], spec)

    assert exposure[0].held == ["GRIDCO"]
    assert exposure[0].name == "Power Transmission & HVDC"


def test_an_unapproved_mapping_is_not_exposure(db, spec, version):
    """⚠ An unapproved mapping is a claim nobody has agreed with yet. Counting it would let a
    suggestion create the exposure it then explains."""
    _mapped(db, spec, version, "UNAPPROVED", "B1.1", approved=False)

    assert themes.exposure_to(db, ["B1.1"], spec)[0].held == []


def test_a_queued_candidate_on_that_theme_is_shown_too(db, spec, version):
    company = ListedCompany(
        id=uuid.uuid4(),
        symbol="QUEUEDCO",
        exchange="NSE",
        name="Queuedco Limited",
        series="EQ",
        refreshed_at=NOW,
    )
    db.add(company)
    db.flush()
    db.add(
        Candidate(
            id=uuid.uuid4(),
            listed_company_id=company.id,
            status="QUEUED",
            first_seen_at=NOW,
            last_seen_at=NOW,
            proposed_bottleneck="B4.2",
        )
    )
    db.commit()

    assert themes.exposure_to(db, ["B4.2"], spec)[0].queued == ["QUEUEDCO"]


# --- through the poll -----------------------------------------------------------------------------


def _item(external_id, title, body=""):
    from app.services.marketdata import feeds

    return feeds.Item(
        external_id=external_id,
        title=title,
        url=f"https://example.invalid/{external_id}",
        published_at=NOW,
        body=body,
        feed="youtube",
    )


@pytest.fixture
def channel(db):
    row = reading.register(
        db,
        kind="YOUTUBE",
        name="pytest channel",
        handle="UCtheme00000000000000",
        trust_tier=reading.COMMENTARY,
        approved=True,
    )
    db.commit()
    return row


def test_an_article_naming_no_company_still_lands_somewhere(db, channel, version, monkeypatch):
    """⚠ The whole point. Before this, a sector article produced nothing at all."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("v1", "Why defence manufacturing is the trade", "ammunition and explosives")
        ],
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.mentions == 0, "no company was named"
    assert result.themes == ["B4.2"]
    item = db.execute(sa.select(SourceItem)).scalar_one()
    assert item.extraction["themes"] == ["B4.2"]


def test_a_theme_is_recorded_even_when_a_company_was_named(db, channel, version, spec, monkeypatch):
    """⚠ An article can be about a theme AND a company, and treating the two as alternatives
    would lose the sector read on exactly the pieces most worth having it for."""
    _mapped(db, spec, version, "SOLARCO", "B1.5")
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("v1", "SOLARCO leads solar cell and module manufacturing", "scale at last")
        ],
    )

    result = reading.poll(db, channel)
    db.commit()

    assert "B1.5" in result.themes


def test_no_approved_framework_means_no_theme_reading(db, channel, monkeypatch):
    """⚠ Routing attention with bottlenecks nobody has agreed to yet would let an unapproved
    framework decide what gets looked at."""
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [_item("v1", "ammunition and explosives demand", "defence")],
    )

    result = reading.poll(db, channel)
    db.commit()

    assert result.themes == []


# --- over the wire --------------------------------------------------------------------------------


def test_the_themes_route_reports_only_what_you_are_exposed_to(
    auth_client, db, channel, version, spec, monkeypatch
):
    """⚠ A theme nobody holds anything on is news about the world and no news about this
    portfolio, and a list including it would bury the ones that matter."""
    _mapped(db, spec, version, "AMMOCO", "B4.2")
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            # One theme the book is exposed to, one it is not.
            _item("v1", "ammunition and explosives demand is structural", "defence"),
            _item("v2", "agri-tech and supply chain is quietly compounding", "farming"),
        ],
    )
    reading.poll(db, channel)
    db.commit()

    body = auth_client.get("/api/investments/themes").json()

    assert [row["bottleneck_id"] for row in body["themes"]] == ["B4.2"]
    assert body["themes"][0]["held"] == ["AMMOCO"]
    assert body["themes"][0]["mentions"] == 1


def test_themes_are_ordered_by_how_much_attention_they_got(
    auth_client, db, channel, version, spec, monkeypatch
):
    _mapped(db, spec, version, "AMMOCO", "B4.2")
    _mapped(db, spec, version, "GRIDCO", "B1.1")
    monkeypatch.setattr(
        reading,
        "_fetch",
        lambda source, c: [
            _item("v1", "power transmission and hvdc capex", "grid"),
            _item("v2", "ammunition and explosives demand", "defence"),
            _item("v3", "more on ammunition and explosives", "defence again"),
        ],
    )
    reading.poll(db, channel)
    db.commit()

    body = auth_client.get("/api/investments/themes").json()["themes"]

    assert [row["bottleneck_id"] for row in body] == ["B4.2", "B1.1"]
    assert body[0]["mentions"] == 2


def test_the_route_is_quiet_before_a_framework_is_approved(auth_client, db):
    assert auth_client.get("/api/investments/themes").json()["themes"] == []


def test_instruments_on_a_theme_are_the_approved_ones(db, spec, version):
    """Used to pull companies forward for a re-score. ⚠ Approved only, or the system would
    choose what to look at by means of what it proposed."""
    held = _mapped(db, spec, version, "APPROVEDCO", "B1.1")
    _mapped(db, spec, version, "PENDINGCO", "B1.1", approved=False)

    assert themes.instruments_on(db, ["B1.1"]) == [held.id]


def test_a_superseded_mapping_is_not_exposure(db, spec, version):
    """A company remapped elsewhere is no longer on the old bottleneck, and a routing table
    that kept it there would send attention to a company that moved."""
    inst = _mapped(db, spec, version, "MOVEDCO", "B1.1")
    frameworks.propose_mapping(
        db,
        inst,
        b_bottleneck="B4.2",
        spec=spec,
        framework_version_id=version.id,
        proposed_by="USER",
    )
    db.commit()

    live = (
        db.execute(
            sa.select(AbMapping).where(
                AbMapping.instrument_id == inst.id, AbMapping.superseded_by_id.is_(None)
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 1
    assert themes.exposure_to(db, ["B1.1"], spec)[0].held == []
