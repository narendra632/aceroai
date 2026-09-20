"""The framework: what it scores, what it refuses to score, and why they differ.

The assertions that matter most here are the two **refusals**, because both look like bugs
from the outside and both are the point:

  * an unapproved mapping scores **zero**, however good the company,
  * an off-framework company scores **None**, which is not zero.

A test suite that only checked the arithmetic would pass happily while a model talked an
unrelated small-cap into national importance.
"""

import datetime as dt
import uuid
from decimal import Decimal as D

import pytest
import sqlalchemy as sa

from app.db.models import AbMapping, FrameworkVersion, Instrument
from app.services.errors import Invalid, NotFound
from app.services.investments import framework_data, frameworks
from tests.conftest import make_instrument

TODAY = dt.date.today()


@pytest.fixture
def spec():
    return framework_data.spec()


@pytest.fixture
def version(db, spec):
    row = frameworks.install(db, spec, notes="pytest", approved=True)
    db.commit()
    return row


def _instrument(db, symbol="FWTEST", sector="EMS_ELECTRONICS"):
    inst = make_instrument(
        db,
        symbol=symbol,
        exchange="NSE",
        name=f"{symbol} Industries",
        asset_class="EQUITY_IN",
        currency="INR",
        sector=sector,
    )
    db.add(inst)
    db.flush()
    return inst


# --- the theory as data ------------------------------------------------------------------


def test_the_framework_is_stored_not_compiled_in(db, version, spec):
    """A score made in March must still be explainable in October, which means the rules it
    used have to be readable rather than re-derived from whatever the code says today."""
    loaded = frameworks.current(db)
    assert loaded.id == version.id
    assert len(loaded.spec["imperatives"]) == 10
    assert len(loaded.spec["bottlenecks"]) == len(spec["bottlenecks"])


def test_an_unapproved_version_is_not_the_current_one(db, spec):
    frameworks.install(db, spec, approved=True)
    proposed = frameworks.install(db, {**spec, "note": "a suggestion"}, approved=False)
    db.commit()

    assert frameworks.current(db).id != proposed.id, (
        "a proposed framework must not take effect before anyone agrees to it"
    )


def test_scoring_without_a_framework_is_refused_rather_than_guessed(db):
    with pytest.raises(NotFound):
        frameworks.current(db)


def test_an_alias_resolves_to_one_canonical_bottleneck(spec):
    """His notes say B9.1 IS B1.2 and B8.2 IS B3.1 — the same bottleneck reached from two
    imperatives. One row with aliases, so a crossing cannot be counted twice."""
    assert frameworks.bottleneck(spec, "B9.1")["id"] == "B1.2"
    assert frameworks.bottleneck(spec, "B8.2")["id"] == "B3.1"
    assert frameworks.bottleneck(spec, "B404") is None


# --- multiples -----------------------------------------------------------------------------


def test_a_known_sector_uses_his_own_number(spec):
    m = frameworks.multiple_for(spec, "CAPITAL_GOODS_POWER_EQUIPMENT")
    assert m.value == D(28) and m.source == "NOTES" and not m.is_fallback


def test_an_unknown_sector_is_flagged_rather_than_silently_defaulted(spec):
    """⚠ The whole point. A company valued at the default gets a margin of safety that looks
    computed and was guessed, and nothing would ever prompt anyone to set a real number."""
    m = frameworks.multiple_for(spec, "SEAWEED_FARMING")
    assert m.value == D(20)
    assert m.is_fallback
    assert "no multiple is set" in m.why


def test_a_bank_is_valued_on_profit_not_owner_earnings(spec):
    """Proven, not assumed: HDFC Bank files under a banking taxonomy with interest earned and
    expended where an industrial has revenue and finance costs. Without this the portfolio's
    anchor holding scores as a value trap and the gates block it for ever."""
    assert frameworks.values_on_earnings(spec, "PRIVATE_BANK")
    assert not frameworks.values_on_earnings(spec, "EMS_ELECTRONICS")


# --- the two refusals ------------------------------------------------------------------------


def test_an_unapproved_mapping_scores_zero_however_good_the_bottleneck(db, version, spec):
    """The guard the whole structural score rests on."""
    inst = _instrument(db)
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    score = frameworks.ab_score(mapping, spec)
    assert score.total == D(0), "a proposal is not a finding"
    assert "not approved" in (score.unavailable_because or "")

    frameworks.approve_mapping(db, mapping)
    db.commit()
    assert frameworks.ab_score(mapping, spec).total > D(0)


def test_off_framework_scores_none_which_is_not_zero(db, version, spec):
    """⚠ Different answers. Zero is 'measured and found wanting'. None is 'this framework
    does not ask a question about this company' — the honest verdict on a US holding."""
    inst = _instrument(db, symbol="FWUSA", sector=None)
    mapping = frameworks.propose_mapping(
        db,
        inst,
        b_bottleneck=None,
        spec=spec,
        framework_version_id=version.id,
        off_framework=True,
    )
    frameworks.approve_mapping(db, mapping)
    db.commit()

    score = frameworks.ab_score(mapping, spec)
    assert score.total is None
    assert not score.is_scored
    assert "India" in (score.unavailable_because or "")


def test_a_company_with_no_mapping_at_all_scores_zero_and_says_so(spec):
    score = frameworks.ab_score(None, spec)
    assert score.total == D(0)
    assert "no framework mapping" in (score.unavailable_because or "")


def test_a_bottleneck_outside_the_framework_cannot_be_mapped_to(db, version, spec):
    inst = _instrument(db)
    with pytest.raises(Invalid):
        frameworks.propose_mapping(
            db, inst, b_bottleneck="B99.9", spec=spec, framework_version_id=version.id
        )


def test_an_off_framework_mapping_cannot_also_name_a_bottleneck(db, version, spec):
    inst = _instrument(db)
    with pytest.raises(Invalid):
        frameworks.propose_mapping(
            db,
            inst,
            b_bottleneck="B1.1",
            spec=spec,
            framework_version_id=version.id,
            off_framework=True,
        )


# --- the arithmetic ---------------------------------------------------------------------------


def test_the_widest_bottleneck_outscores_the_narrowest(db, version, spec):
    """B1.1 blocks six imperatives and inflects now; B3.2 blocks one and inflects FY30+."""
    wide = _instrument(db, symbol="FWWIDE")
    narrow = _instrument(db, symbol="FWNARROW")
    scores = {}
    for inst, b_id in ((wide, "B1.1"), (narrow, "B3.2")):
        m = frameworks.propose_mapping(
            db, inst, b_bottleneck=b_id, spec=spec, framework_version_id=version.id
        )
        frameworks.approve_mapping(db, m)
        scores[b_id] = frameworks.ab_score(m, spec)
    db.commit()

    assert scores["B1.1"].total > scores["B3.2"].total
    # 4 breadth + 0 crisis (his is IMPLIED, not EXPLICIT) + 2 timing + 0 commitment + 1 green
    assert scores["B1.1"].total == D(7)
    # 1 breadth + 0 crisis + 0 timing (FY30) + 0 commitment + 0 red
    assert scores["B3.2"].total == D(1)


def test_a_crisis_accelerated_bottleneck_earns_its_two_points(db, version, spec):
    inst = _instrument(db, symbol="FWAMMO")
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B4.2", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    db.commit()

    score = frameworks.ab_score(m, spec)
    crisis = next(c for c in score.components if c.name == "crisis")
    assert crisis.points == D(2)
    assert "shock" in crisis.detail


def test_the_government_commitment_point_is_withheld_until_a_source_exists(db, version, spec):
    """⚠ The rule requires a spend figure traceable to an ingested document, and the framework
    document is not one. Awarding it from the framework's own prose is the system citing
    itself — exactly what the sourcing rule forbids."""
    inst = _instrument(db, symbol="FWGRID")
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    db.commit()

    commitment = next(c for c in frameworks.ab_score(m, spec).components if c.name == "commitment")
    assert commitment.points == D(0)
    assert "no ingested source" in commitment.detail


def test_a_partial_crossing_count_is_reported_as_a_floor(db, version, spec):
    """⚠ The bug this design exists to avoid: his notes spell out crossings for eight
    bottlenecks and leave the rest unstated. Scoring a gap in the write-up as a fact about
    India would mark ammunition structurally narrow because that section is short."""
    inst = _instrument(db, symbol="FWAMMO2")
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B4.2", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    db.commit()

    score = frameworks.ab_score(m, spec)
    assert score.breadth_is_floor
    breadth = next(c for c in score.components if c.name == "breadth")
    assert "at least" in breadth.detail and "understated" in breadth.detail

    # A confirmed one makes no such claim.
    other = _instrument(db, symbol="FWGRID2")
    m2 = frameworks.propose_mapping(
        db, other, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m2)
    db.commit()
    assert not frameworks.ab_score(m2, spec).breadth_is_floor


def test_timing_depends_on_the_holding_period(db, version, spec):
    """An inflection in FY28 is inside a three-year horizon and outside a one-month one."""
    inst = _instrument(db, symbol="FWNUKE")
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.4", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    db.commit()

    near = frameworks.ab_score(m, spec, horizon_days=30, today=dt.date(2026, 9, 20))
    far = frameworks.ab_score(m, spec, horizon_days=1095, today=dt.date(2026, 9, 20))
    assert _points(near, "timing") == D(0)
    assert _points(far, "timing") == D(1)


def _points(score, name):
    return next(c.points for c in score.components if c.name == name)


# --- mappings over time -----------------------------------------------------------------------


def test_a_new_mapping_supersedes_the_old_one_rather_than_joining_it(db, version, spec):
    inst = _instrument(db)
    first = frameworks.propose_mapping(
        db, inst, b_bottleneck="B2.2", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, first)
    db.commit()

    second = frameworks.propose_mapping(
        db, inst, b_bottleneck="B2.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    assert first.superseded_by_id == second.id
    assert frameworks.live_mapping(db, inst.id).id == second.id
    # ⚠ And the replacement is unapproved, so the company drops to zero until confirmed —
    # a re-mapping is a new claim, not an inherited one.
    assert frameworks.ab_score(second, spec).total == D(0)


def test_a_superseded_mapping_cannot_be_approved(db, version, spec):
    inst = _instrument(db)
    first = frameworks.propose_mapping(
        db, inst, b_bottleneck="B2.2", spec=spec, framework_version_id=version.id
    )
    frameworks.propose_mapping(
        db, inst, b_bottleneck="B2.1", spec=spec, framework_version_id=version.id
    )
    db.commit()
    with pytest.raises(Invalid):
        frameworks.approve_mapping(db, first)


def test_approving_sets_an_expiry_so_a_judgement_does_not_stand_for_ever(db, version, spec):
    """A mapping says what a company does TODAY. Kaynes moving from contract electronics into
    chip packaging is exactly the change that would otherwise score the old business for years."""
    inst = _instrument(db)
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B2.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    db.commit()
    assert m.review_after == TODAY + dt.timedelta(days=frameworks.MAPPING_VALID_DAYS)


# --- what needs a person ------------------------------------------------------------------------


def test_everything_blocking_a_complete_score_is_listed_for_a_person(db, version, spec):
    """⚠ A silently wrong score is worse than a missing one: nothing prompts anyone to fix it."""
    unmapped = _instrument(db, symbol="FWNONE")
    proposed = _instrument(db, symbol="FWPROP")
    no_multiple = _instrument(db, symbol="FWSEA", sector="SEAWEED_FARMING")

    frameworks.propose_mapping(
        db, proposed, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    ok = frameworks.propose_mapping(
        db, no_multiple, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, ok)
    db.commit()

    items = frameworks.needs_attention(db, spec)
    by_symbol = {(i.symbol, i.kind) for i in items}
    assert ("FWNONE", "UNMAPPED") in by_symbol
    assert ("FWPROP", "UNAPPROVED") in by_symbol
    assert ("FWSEA", "NO_MULTIPLE") in by_symbol
    assert unmapped.symbol == "FWNONE"


def test_an_expired_mapping_is_raised_for_re_confirmation(db, version, spec):
    inst = _instrument(db, symbol="FWOLD")
    m = frameworks.propose_mapping(
        db, inst, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, m)
    m.review_after = TODAY - dt.timedelta(days=1)
    db.commit()

    kinds = {i.kind for i in frameworks.needs_attention(db, spec) if i.symbol == "FWOLD"}
    assert "EXPIRED" in kinds


# --- the seed --------------------------------------------------------------------------------


def test_the_seed_installs_once_and_then_writes_nothing(db, user):
    """⚠ Found live: Postgres has no tuple, so a tuple in the spec came back a list and an
    unchanged framework compared unequal to itself — installing a new version every run."""
    from app.scripts import seed_framework

    first = seed_framework.seed(db, write=True)
    second = seed_framework.seed(db, write=True)

    assert "installed" in first["framework"] or "unchanged" in first["framework"]
    assert "unchanged" in second["framework"], second["framework"]
    assert db.query(FrameworkVersion).filter_by(family="india_ab").count() >= 1


def test_the_seed_proposes_and_never_approves(db, user):
    """A rule with an exception for trusted sources is a rule that acquires more exceptions."""
    from app.scripts import seed_framework

    seed_framework.seed(db, write=True)
    approved = db.query(AbMapping).filter(AbMapping.approved_at.isnot(None)).count()
    assert approved == 0, "seeding must leave every mapping awaiting a person"


def test_every_seeded_mapping_names_a_real_bottleneck_or_is_off_framework():
    from app.scripts import seed_framework

    spec = framework_data.spec()
    for symbol, b_id in seed_framework.MAPPINGS.items():
        if b_id is None:
            continue
        assert frameworks.bottleneck(spec, b_id) is not None, f"{symbol} -> {b_id}"
    assert set(seed_framework.WHY) == set(seed_framework.MAPPINGS), (
        "every mapping needs the sentence a person reads before agreeing with it"
    )


def test_every_bottleneck_crosses_a_real_imperative():
    spec = framework_data.spec()
    ids = {a["id"] for a in spec["imperatives"]}
    seen: set[str] = set()
    for row in spec["bottlenecks"]:
        assert row["crosses"], row["id"]
        assert not set(row["crosses"]) - ids, row["id"]
        assert row["id"] not in seen, f"duplicate bottleneck {row['id']}"
        seen.add(row["id"])


def test_the_spec_survives_a_json_round_trip_unchanged():
    """The idempotency of the seed depends on this, and nothing else asserts it."""
    import json

    spec = framework_data.spec()
    assert json.loads(json.dumps(spec)) == spec, (
        "a tuple or Decimal here returns as something else and reinstalls the framework daily"
    )


def test_the_sector_of_every_seeded_instrument_has_a_multiple():
    """⚠ Otherwise a holding is silently valued at the default and nobody is told."""
    from app.scripts import seed_investments

    spec = framework_data.spec()
    for entry in (*seed_investments.INSTRUMENTS, *seed_investments.WATCHLIST):
        sector = entry[6].get("sector")
        if sector is None:
            continue
        assert not frameworks.multiple_for(spec, sector).is_fallback, sector


def test_every_indian_equity_in_the_seed_has_a_framework_mapping():
    """A tracked Indian company with no mapping can never be scored, and nothing would say so
    until someone wondered why it never appeared in a proposal."""
    from app.scripts import seed_framework, seed_investments

    indian = {
        e[0]
        for e in (*seed_investments.INSTRUMENTS, *seed_investments.WATCHLIST)
        if e[3] == "EQUITY_IN"
    }
    assert indian - set(seed_framework.MAPPINGS) == set()


# --- over the wire ------------------------------------------------------------------------


@pytest.fixture
def wired(db, user, version, spec):
    """A book with one held company and one watchlist company, both proposed."""
    from app.db.models import Portfolio, Transaction

    book = Portfolio(id=uuid.uuid4(), user_id=user.id, name="pytest-fw", kind="REAL")
    db.add(book)
    db.flush()

    held = _instrument(db, symbol="FWHELD", sector="CAPITAL_GOODS_POWER_EQUIPMENT")
    watched = _instrument(db, symbol="FWWATCH", sector="DEFENCE_MANUFACTURING")
    db.add(
        Transaction(
            id=uuid.uuid4(),
            portfolio_id=book.id,
            instrument_id=held.id,
            txn_type="BUY",
            trade_date=TODAY - dt.timedelta(days=10),
            quantity=D(5),
            price=D("100.00"),
            currency="INR",
            fx_rate_inr=D(1),
            entry_source="IMPORT",
        )
    )
    for inst, b_id in ((held, "B1.1"), (watched, "B4.2")):
        frameworks.propose_mapping(
            db, inst, b_bottleneck=b_id, spec=spec, framework_version_id=version.id
        )
    db.commit()
    book.held, book.watched = held, watched
    return book


def test_the_framework_route_shows_held_and_watched_alike(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    by_symbol = {m["symbol"]: m for m in body["mappings"]}

    assert by_symbol["FWHELD"]["is_held"] is True
    assert by_symbol["FWWATCH"]["is_held"] is False, (
        "a watchlist company must be scored without being a holding"
    )
    assert len(body["bottlenecks"]) == 31
    assert len(body["imperatives"]) == 10


def test_an_unapproved_mapping_arrives_scoring_zero_with_its_reason(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    held = next(m for m in body["mappings"] if m["symbol"] == "FWHELD")
    assert held["approved_at"] is None
    assert held["score"]["total"] == "0"
    assert "not approved" in held["score"]["unavailable_because"]


def test_approving_over_the_wire_is_what_makes_it_score(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    held = next(m for m in body["mappings"] if m["symbol"] == "FWHELD")

    approved = auth_client.post(
        f"/api/investments/framework/mappings/{held['id']}/approve",
        json={"note": "yes, transmission"},
    )
    assert approved.status_code == 200
    out = approved.json()
    assert out["approved_at"] is not None
    assert D(out["score"]["total"]) == D(7)
    # ⚠ Money and scores cross as strings, like everything else in this module.
    assert isinstance(out["score"]["total"], str)


def test_remapping_drops_the_company_back_to_zero_until_reconfirmed(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    held = next(m for m in body["mappings"] if m["symbol"] == "FWHELD")
    auth_client.post(f"/api/investments/framework/mappings/{held['id']}/approve")

    moved = auth_client.post(
        f"/api/investments/framework/mappings/{held['id']}/remap",
        json={"b_bottleneck": "B2.1", "off_framework": False, "rationale": "moved to OSAT"},
    )
    assert moved.status_code == 200
    out = moved.json()
    assert out["b_bottleneck"] == "B2.1"
    assert out["approved_at"] is None
    assert D(out["score"]["total"]) == D(0), "a re-mapping is a fresh claim, not an inherited one"


def test_the_fallback_multiple_is_reported_over_the_wire(auth_client, db, wired, version, spec):
    odd = _instrument(db, symbol="FWSEAWIRE", sector="SEAWEED_FARMING")
    frameworks.propose_mapping(
        db, odd, b_bottleneck="B1.1", spec=spec, framework_version_id=version.id
    )
    db.commit()

    body = auth_client.get("/api/investments/framework").json()
    row = next(m for m in body["mappings"] if m["symbol"] == "FWSEAWIRE")
    assert row["multiple_is_fallback"] is True
    assert "no multiple is set" in row["multiple_why"]


def test_the_attention_list_reaches_the_interface(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    kinds = {(a["symbol"], a["kind"]) for a in body["attention"]}
    assert ("FWHELD", "UNAPPROVED") in kinds


# --- establishing a crossing set ------------------------------------------------------------


def test_revising_crossings_raises_the_score_and_versions_the_change(db, version, spec):
    """⚠ The repair for the defect the whole design was shaped around.

    B8.3 is recorded as blocking one imperative because that section of the notes is brief,
    not because financial infrastructure serves one national aim. Until this existed the
    interface could say "this is a floor" and offer no way to raise it — information dressed
    as an action, which is worse than silence because it sits in the list for ever.
    """
    inst = _instrument(db, symbol="FWBANK", sector="PRIVATE_BANK")
    mapping = frameworks.propose_mapping(
        db, inst, b_bottleneck="B8.3", spec=spec, framework_version_id=version.id
    )
    frameworks.approve_mapping(db, mapping)
    db.commit()

    before = frameworks.ab_score(mapping, spec)
    assert before.breadth_is_floor
    # 1 breadth + 0 crisis + 2 timing (NOW) + 0 commitment + 1 green
    assert before.total == D(4)

    revised = frameworks.revise_crossings(
        db, b_bottleneck="B8.3", crosses=["A1", "A6", "A8"], note="rupee settlement, capex"
    )
    db.commit()

    assert revised.version > version.version, "a crossing set is a claim; changing it versions"
    after = frameworks.ab_score(mapping, revised.spec)
    assert not after.breadth_is_floor
    # breadth 1 -> 3 on three crossings
    assert after.total == D(6)
    assert mapping.approved_at is not None, (
        "what was agreed — that this company clears this bottleneck — has not changed"
    )
    assert mapping.framework_version_id == revised.id


def test_a_revision_cannot_invent_an_imperative(db, version, spec):
    with pytest.raises(Invalid):
        frameworks.revise_crossings(db, b_bottleneck="B2.2", crosses=["A2", "A99"])


def test_a_bottleneck_must_block_something(db, version, spec):
    with pytest.raises(Invalid):
        frameworks.revise_crossings(db, b_bottleneck="B2.2", crosses=[])


def test_a_revision_of_an_unknown_bottleneck_is_refused(db, version, spec):
    with pytest.raises(Invalid):
        frameworks.revise_crossings(db, b_bottleneck="B77.7", crosses=["A2"])


def test_revising_over_the_wire_returns_the_whole_framework_again(auth_client, wired):
    body = auth_client.get("/api/investments/framework").json()
    watch = next(m for m in body["mappings"] if m["symbol"] == "FWWATCH")
    auth_client.post(f"/api/investments/framework/mappings/{watch['id']}/approve")

    before = auth_client.get("/api/investments/framework").json()
    was = next(m for m in before["mappings"] if m["symbol"] == "FWWATCH")
    assert was["crosses_a_count"] == 1

    revised = auth_client.post(
        "/api/investments/framework/bottlenecks/B4.2/crossings",
        json={"crosses": ["A4", "A6"], "status": "CONFIRMED", "note": "also the wider base"},
    )
    assert revised.status_code == 200
    now = next(m for m in revised.json()["mappings"] if m["symbol"] == "FWWATCH")
    assert now["crosses_a_count"] == 2
    assert now["crossings_status"] == "CONFIRMED"
    assert now["approved_at"] is not None


def test_the_seed_brings_live_mappings_onto_a_corrected_framework(db, user):
    """⚠ A mapping stores the bottleneck's facts as they stood when it was agreed, so
    correcting a crossing set in the data fixes a FRESH database and does nothing at all to one
    already seeded. Production would keep scoring the old count with nothing reporting it."""
    from app.scripts import seed_framework

    db.add(
        make_instrument(
            db,
            symbol="SYRMA",
            exchange="NSE",
            name="Syrma SGS Technology",
            asset_class="EQUITY_IN",
            currency="INR",
            sector="EMS_ELECTRONICS",
        )
    )
    db.flush()

    seed_framework.seed(db, write=True)
    syrma = db.execute(
        sa.select(AbMapping)
        .join(Instrument, AbMapping.instrument_id == Instrument.id)
        .where(Instrument.symbol == "SYRMA", AbMapping.superseded_by_id.is_(None))
    ).scalar_one()

    frameworks.approve_mapping(db, syrma)
    syrma.a_imperatives = ["A2"]
    syrma.crosses_a_count = 1
    syrma.crossings_status = "PARTIAL"
    db.commit()

    report = seed_framework.seed(db, write=True)
    db.refresh(syrma)

    assert report.get("refreshed", 0) >= 1
    assert syrma.crosses_a_count == 3, "the corrected crossing set must reach an existing row"
    assert syrma.crossings_status == "CONFIRMED"
    assert syrma.approved_at is not None, (
        "the company-to-bottleneck agreement is untouched; only the bottleneck's width changed"
    )
