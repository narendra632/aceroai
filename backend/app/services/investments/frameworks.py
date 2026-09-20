"""The framework, read from the database and turned into a score.

Three things live here and nothing else does:

* **Loading the theory.** `framework_versions` holds it; this module reads the current
  approved one and never reads `framework_data` directly outside seeding. That indirection is
  the whole reason the framework is data: a score made in March must remain explainable in
  October, which means the rules it used have to be retrievable rather than re-derived.
* **The structural score**, which is *arithmetic over an approved mapping and nothing else*.
  No model is involved and no model may be. Every number below comes from a row a person
  agreed with.
* **The propose-then-approve path**, which is how a company enters the framework at all.

⚠ **Two refusals are the point of this module, and both are easy to mistake for bugs.**

**An unapproved mapping scores zero.** A model may propose that a company clears a national
bottleneck; that proposal is worth nothing until a person agrees. Without this, a system that
reads enough news will eventually talk itself into believing an unrelated small-cap is
strategically essential, and the score has no way to tell that apart from the real thing.

**Off-framework scores `None`, not zero.** They are different answers. Zero means "measured
against this framework and found wanting". `None` means "this framework does not ask a
question about this company" — which is the honest verdict on SpaceX, because the framework
asks what *India* must build. Collapsing the two would mark a US holding as structurally
failing when it was never a candidate for the test.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import AbMapping, FrameworkVersion, Instrument
from app.services.errors import Invalid, NotFound
from app.services.investments import framework_data

ZERO = Decimal(0)

#: The default window a timing judgement is made against, when no proposal supplies one.
#: His horizon is months to quarters; a year is the generous reading of that.
DEFAULT_HORIZON_DAYS = 365

#: How long an approved mapping stands before it is re-proposed. A mapping says what a
#: company does *today*, and Kaynes moving from contract electronics into chip packaging is
#: exactly the change that would otherwise keep scoring against the old business for years.
MAPPING_VALID_DAYS = 365


# --- reading the theory ------------------------------------------------------------------


def current(db: Session, family: str = "india_ab") -> FrameworkVersion:
    """The newest APPROVED version of a framework family.

    ⚠ Approved, not newest. An unapproved version is a proposal — it is what a newly
    suggested bottleneck lands in — and scoring against it would let a suggestion take effect
    before anyone agreed to it.
    """
    row = db.execute(
        sa.select(FrameworkVersion)
        .where(FrameworkVersion.family == family, FrameworkVersion.approved_at.isnot(None))
        .order_by(FrameworkVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(f"no approved {family} framework — seed it before scoring against it")
    return row


def install(
    db: Session,
    spec: dict,
    *,
    family: str = "india_ab",
    notes: str | None = None,
    approved: bool = False,
) -> FrameworkVersion:
    """Write a new version of a framework. Unapproved unless asked otherwise.

    Never edits an existing row: the point of versioning is that the rules a past decision
    used are still readable exactly as they were.
    """
    highest = db.execute(
        sa.select(sa.func.max(FrameworkVersion.version)).where(FrameworkVersion.family == family)
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.UTC)
    row = FrameworkVersion(
        id=uuid.uuid4(),
        family=family,
        version=(highest or 0) + 1,
        spec=spec,
        effective_from=now,
        notes=notes,
        approved_at=now if approved else None,
    )
    db.add(row)
    db.flush()
    return row


def bottleneck(spec: dict, b_id: str | None) -> dict | None:
    """One bottleneck out of the spec, resolving the aliases his notes carry.

    His framework says B8.2 *is* B3.1 and B9.1 *is* B1.2 — the same bottleneck reached from
    two different imperatives. One canonical row with aliases, so a crossing cannot be counted
    twice by arriving at it from both directions.
    """
    if not b_id:
        return None
    for row in spec.get("bottlenecks", ()):
        if row["id"] == b_id or b_id in (row.get("aliases") or ()):
            return row
    return None


@dataclass(frozen=True)
class Multiple:
    """What a rupee of owner earnings is worth in a sector, and how sure we are of that."""

    sector: str
    value: Decimal
    source: str  # NOTES (his own number) | ANCHOR (set from market level) | FALLBACK
    why: str

    @property
    def is_fallback(self) -> bool:
        """⚠ True when this sector has no multiple of its own and the default was used.

        The interface must say so. A company silently valued at the default multiple gets a
        margin of safety that looks computed and was in fact guessed.
        """
        return self.source == "FALLBACK"


def multiple_for(spec: dict, sector: str | None) -> Multiple:
    """The fair multiple for a sector, or the default with a flag saying it was the default."""
    table = spec.get("multiples", {})
    row = table.get(sector or "")
    if row is None:
        fallback = table.get("DEFAULT", {"multiple": "20", "why": "no table entry"})
        return Multiple(
            sector=sector or "UNCLASSIFIED",
            value=Decimal(str(fallback["multiple"])),
            source="FALLBACK",
            why=(
                f"no multiple is set for {sector or 'an unclassified company'}; "
                f"using the default of {fallback['multiple']}"
            ),
        )
    return Multiple(
        sector=sector or "",
        value=Decimal(str(row["multiple"])),
        source=row.get("source", "ANCHOR"),
        why=row.get("why", ""),
    )


def values_on_earnings(spec: dict, sector: str | None) -> bool:
    """Whether this sector is valued on profit rather than owner earnings.

    True for banks. Depreciation and capex are immaterial to one, borrowings are raw material
    rather than leverage, and cash conversion means nothing — so the owner-earnings method
    does not merely mis-measure a bank, it measures something that does not exist.
    """
    return (sector or "") in set(spec.get("earnings_only_sectors", ()))


# --- the structural score ----------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    name: str
    points: Decimal
    available: Decimal
    detail: str


@dataclass(frozen=True)
class AbScore:
    """The structural score: how much durable demand the framework says this company has.

    `total is None` means the framework does not apply — see the module docstring.
    """

    total: Decimal | None
    available: Decimal
    components: list[Component] = field(default_factory=list)
    #: Why the score is None or zero, in a sentence the interface can show unchanged.
    unavailable_because: str | None = None
    #: ⚠ True when the crossing count is a floor rather than an established figure. The score
    #: is real but may be understated, and nothing should present it as a ceiling.
    breadth_is_floor: bool = False

    @property
    def is_scored(self) -> bool:
        return self.total is not None


def _fy_start(label: str | None) -> dt.date | None:
    """`FY27` → 1 April 2026. India's financial year is named for the year it ENDS in."""
    if not label:
        return None
    digits = "".join(c for c in label if c.isdigit())
    if len(digits) != 2:
        return None
    return dt.date(2000 + int(digits) - 1, 4, 1)


def ab_score(
    mapping: AbMapping | None,
    spec: dict,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    today: dt.date | None = None,
) -> AbScore:
    """Score one company's place in the framework. Deterministic; no model involved."""
    today = today or dt.date.today()
    available = Decimal(10)

    if mapping is None:
        return AbScore(
            ZERO, available, unavailable_because="this company has no framework mapping yet"
        )
    if mapping.off_framework:
        return AbScore(
            None,
            available,
            unavailable_because=(
                "outside the framework by construction — it asks what India must build, and "
                "this company is not answering that question"
            ),
        )
    if mapping.approved_at is None:
        # ⚠ The guard the whole score rests on. A proposal is not a finding.
        return AbScore(
            ZERO,
            available,
            unavailable_because=(
                "its framework mapping is proposed but not approved, so it scores nothing yet"
            ),
        )

    rules = spec.get("ab_weights", framework_data.AB_WEIGHTS)
    components: list[Component] = []

    # --- breadth: how many imperatives this bottleneck unblocks -------------------------
    count = mapping.crosses_a_count or 0
    points = ZERO
    for threshold, award in rules["breadth"]["bands"]:
        if count >= threshold:
            points = Decimal(award)
            break
    floor = mapping.crossings_status == "PARTIAL"
    components.append(
        Component(
            "breadth",
            points,
            Decimal(rules["breadth"]["max"]),
            (
                f"blocks at least {count} of the ten imperatives — the full set was never "
                "established, so this may be understated"
                if floor
                else f"blocks {count} of the ten imperatives"
            ),
        )
    )

    # --- crisis acceleration -------------------------------------------------------------
    crisis = Decimal(rules["crisis"]["max"]) if mapping.is_crisis_accelerated else ZERO
    components.append(
        Component(
            "crisis",
            crisis,
            Decimal(rules["crisis"]["max"]),
            "a named shock pulled this spending forward"
            if mapping.is_crisis_accelerated
            else "no named shock accelerates this",
        )
    )

    # --- timing fit ------------------------------------------------------------------------
    inflection = mapping.inflection_quarter
    horizon_end = today + dt.timedelta(days=horizon_days)
    if inflection == "NOW":
        timing, why = Decimal(rules["timing"]["max"]), "inflecting now"
    else:
        start = _fy_start(inflection)
        if start is None:
            timing, why = ZERO, "no inflection is stated, so timing scores nothing"
        elif start <= horizon_end:
            timing, why = Decimal(1), f"inflects in {inflection}, inside the holding period"
        else:
            timing, why = ZERO, f"inflects in {inflection}, beyond the holding period"
    components.append(Component("timing", timing, Decimal(rules["timing"]["max"]), why))

    # --- government commitment -------------------------------------------------------------
    # ⚠ Scores zero until source ingestion lands in Phase 3. The rule requires a committed
    # spend figure traceable to an ingested document, and the framework document itself is
    # not one. Awarding the point from the framework's own prose would be the system citing
    # itself, which is exactly the move the sourcing rule exists to forbid.
    components.append(
        Component(
            "commitment",
            ZERO,
            Decimal(rules["commitment"]["max"]),
            "no ingested source yet carries the committed-spend figure",
        )
    )

    # --- investability ----------------------------------------------------------------------
    grade = mapping.investability or "RED"
    invest = Decimal(str(rules["investability"].get(grade, 0)))
    components.append(
        Component(
            "investability",
            invest,
            Decimal(rules["investability"]["max"]),
            f"investability {grade.lower()}",
        )
    )

    total = sum((c.points for c in components), ZERO)
    return AbScore(total, available, components, breadth_is_floor=floor)


# --- mappings: propose, approve, supersede -----------------------------------------------


def live_mapping(db: Session, instrument_id: uuid.UUID) -> AbMapping | None:
    """The mapping in force for a company — the one nothing has superseded."""
    return db.execute(
        sa.select(AbMapping)
        .where(AbMapping.instrument_id == instrument_id, AbMapping.superseded_by_id.is_(None))
        .order_by(AbMapping.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def propose_mapping(
    db: Session,
    instrument: Instrument,
    *,
    b_bottleneck: str | None,
    spec: dict,
    framework_version_id: uuid.UUID,
    proposed_by: str = "AGENT",
    rationale: str | None = None,
    off_framework: bool = False,
) -> AbMapping:
    """Suggest where a company sits. Supersedes any previous mapping; scores nothing yet.

    The structural facts — which imperatives, how many, crisis, timing, investability — are
    copied from the BOTTLENECK, not invented per company. That is deliberate: the framework's
    claims are about the bottleneck, and letting a per-company row restate them would allow
    the same bottleneck to be worth more under one company than another.
    """
    if off_framework and b_bottleneck:
        raise Invalid("an off-framework mapping names no bottleneck")

    row = bottleneck(spec, b_bottleneck)
    if not off_framework and row is None:
        raise Invalid(
            f"{b_bottleneck!r} is not a bottleneck in this framework — propose it as a new "
            "one first, or mark the company off-framework"
        )

    previous = live_mapping(db, instrument.id)
    mapping = AbMapping(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        a_imperatives=list(row["crosses"]) if row else None,
        b_bottleneck=row["id"] if row else None,
        crosses_a_count=len(row["crosses"]) if row else 0,
        crossings_status=row["crossings_status"] if row else "UNSUPPORTED",
        is_crisis_accelerated=bool(row and row.get("crisis") == "EXPLICIT"),
        inflection_quarter=row.get("inflection") if row else None,
        investability=row.get("investability") if row else None,
        rationale=rationale,
        proposed_by=proposed_by,
        off_framework=off_framework,
        framework_version_id=framework_version_id,
    )
    db.add(mapping)
    db.flush()
    if previous is not None:
        previous.superseded_by_id = mapping.id
    db.flush()
    return mapping


def approve_mapping(db: Session, mapping: AbMapping, *, note: str | None = None) -> AbMapping:
    """Agree with a proposed mapping. This is the one click that lets it score."""
    if mapping.superseded_by_id is not None:
        raise Invalid("that mapping has been superseded; approve the one that replaced it")
    if mapping.approved_at is not None:
        return mapping
    mapping.approved_at = dt.datetime.now(dt.UTC)
    mapping.approved_note = note
    mapping.review_after = dt.date.today() + dt.timedelta(days=MAPPING_VALID_DAYS)
    db.flush()
    return mapping


@dataclass(frozen=True)
class Attention:
    """One thing the framework needs a person for, in the words the interface will use."""

    kind: str  # UNAPPROVED · EXPIRED · BREADTH_FLOOR · NO_MULTIPLE · UNMAPPED
    instrument_id: uuid.UUID | None
    symbol: str
    detail: str


def needs_attention(db: Session, spec: dict, *, today: dt.date | None = None) -> list[Attention]:
    """Everything blocking a complete score, as a list a person can work through.

    ⚠ This is the mechanism that keeps the framework honest as the book grows. A company
    added next year with no mapping, a sector with no multiple, a mapping that has gone stale
    — each would otherwise degrade a score silently, and a silently wrong score is worse than
    a missing one because nothing prompts anyone to fix it.
    """
    today = today or dt.date.today()
    out: list[Attention] = []

    tracked = list(
        db.execute(
            sa.select(Instrument).where(
                Instrument.deleted_at.is_(None),
                Instrument.is_tracked.is_(True),
                Instrument.asset_class.in_(("EQUITY_IN", "EQUITY_US")),
            )
        ).scalars()
    )

    for inst in tracked:
        mapping = live_mapping(db, inst.id)
        if mapping is None:
            out.append(
                Attention(
                    "UNMAPPED",
                    inst.id,
                    inst.symbol,
                    "has no framework mapping, so it cannot be scored structurally",
                )
            )
            continue
        if mapping.approved_at is None:
            out.append(
                Attention(
                    "UNAPPROVED",
                    inst.id,
                    inst.symbol,
                    f"a mapping to {mapping.b_bottleneck or 'off-framework'} is proposed "
                    "and scores nothing until you agree with it",
                )
            )
        elif mapping.review_after and mapping.review_after <= today:
            out.append(
                Attention(
                    "EXPIRED",
                    inst.id,
                    inst.symbol,
                    "its mapping is over a year old — confirm the company still does "
                    "what it did when this was agreed",
                )
            )
        if mapping.crossings_status == "PARTIAL" and not mapping.off_framework:
            out.append(
                Attention(
                    "BREADTH_FLOOR",
                    inst.id,
                    inst.symbol,
                    f"{mapping.b_bottleneck} is recorded as blocking at least "
                    f"{mapping.crosses_a_count} "
                    f"imperative{'' if mapping.crosses_a_count == 1 else 's'}; the full set "
                    "was never "
                    "established, so its structural score may be understated",
                )
            )
        if not mapping.off_framework and multiple_for(spec, inst.sector).is_fallback:
            out.append(
                Attention(
                    "NO_MULTIPLE",
                    inst.id,
                    inst.symbol,
                    f"no fair multiple is set for {inst.sector or 'its sector'}, so the "
                    "default is being used and the margin of safety is a guess",
                )
            )
    return out


def revise_crossings(
    db: Session,
    *,
    b_bottleneck: str,
    crosses: list[str],
    note: str | None = None,
    status: str = "CONFIRMED",
) -> FrameworkVersion:
    """Establish which imperatives a bottleneck actually blocks.

    ⚠ This is the repair for the one real defect in how the framework was first loaded. The
    source notes spell the crossing set out for eight bottlenecks and leave it unstated for
    the rest, and the largest component of the structural score is that count. Until this
    existed, the interface could say "this figure is a floor" and offer no way to raise it —
    information dressed as an action, which is worse than silence.

    It writes a **new framework version**, because a crossing set is a claim about India and
    changing one changes the rules every later score is measured against. Live mappings onto
    that bottleneck are brought forward **keeping their approval**: what the user agreed to
    was "this company clears this bottleneck", and that claim has not changed — only how wide
    the bottleneck is, which is what they are deciding here.
    """
    spec = dict(current(db).spec)
    rows = [dict(r) for r in spec.get("bottlenecks", ())]
    target = None
    for row in rows:
        if row["id"] == b_bottleneck or b_bottleneck in (row.get("aliases") or ()):
            target = row
            break
    if target is None:
        raise Invalid(f"{b_bottleneck!r} is not a bottleneck in this framework")

    known = {a["id"] for a in spec.get("imperatives", ())}
    unknown = sorted(set(crosses) - known)
    if unknown:
        raise Invalid(f"not imperatives in this framework: {', '.join(unknown)}")
    if not crosses:
        raise Invalid("a bottleneck blocks at least one imperative, or it is not a bottleneck")
    if status not in ("CONFIRMED", "PARTIAL"):
        raise Invalid("a revised crossing set is either confirmed or still a floor")

    target["crosses"] = sorted(set(crosses))
    target["crossings_status"] = status
    spec["bottlenecks"] = rows

    version = install(
        db,
        spec,
        notes=note or f"{target['id']} crossings revised to {len(target['crosses'])}",
        approved=True,
    )

    # Bring live mappings onto the new version. Approval is kept deliberately — see above.
    live = db.execute(
        sa.select(AbMapping).where(
            AbMapping.b_bottleneck == target["id"], AbMapping.superseded_by_id.is_(None)
        )
    ).scalars()
    for mapping in live:
        mapping.a_imperatives = list(target["crosses"])
        mapping.crosses_a_count = len(target["crosses"])
        mapping.crossings_status = status
        mapping.framework_version_id = version.id
    db.flush()
    return version
