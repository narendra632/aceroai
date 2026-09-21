"""HTTP for the Investments page.

Thin by design: every figure here comes from `services/investments/`, which the assistant's
tools also call. A rule implemented in only one of the two is a rule the other one skips.

⚠ Two things this module must never do:

* **Return a bare dict.** Every route declares a response model, because `jsonable_encoder`
  turns a `Decimal` into a float and money stops being exact on the way out.
* **Trust a costed draft from the client.** `POST /transactions` takes the same raw inputs as
  the draft route and re-runs `entry.prepare`, so charges and validation are computed
  server-side both times. Accepting a client's own draft would let a bug — or a doctored
  request — write a transaction with zero charges.
"""

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import (
    AbScoreOut,
    ActiveIn,
    ApproveIn,
    AssetTotalOut,
    AttentionOut,
    AttributionOut,
    BookLineOut,
    BooksOut,
    BottleneckOut,
    ClaimOut,
    CorporateActionOut,
    CrossingsIn,
    CurveOut,
    DecideIn,
    DismissIn,
    DraftIn,
    DraftOut,
    DropIn,
    DropOut,
    FiredTriggerOut,
    FlagOut,
    FrameworkOut,
    GateOut,
    HeardOut,
    HoldingDetailOut,
    HoldingOut,
    MappingOut,
    MeasureOut,
    PriceRefreshOut,
    PromoteIn,
    ProposalOut,
    ProposalsOut,
    QualityOut,
    QueueLineOut,
    ReadingOut,
    RemapIn,
    ResearchQueueOut,
    ReverseIn,
    ScheduleFaOut,
    SourceOut,
    SummaryOut,
    TotalsOut,
    TransactionOut,
    TriggerOut,
)
from app.db.models import (
    AbMapping,
    AgentRun,
    Candidate,
    Claim,
    CorporateAction,
    Decision,
    Instrument,
    InvalidationTrigger,
    ListedCompany,
    Proposal,
    Source,
    Transaction,
    User,
)
from app.db.session import get_db
from app.services.errors import NotFound
from app.services.investments import (
    books,
    corpactions,
    entry,
    frameworks,
    fundamentals,
    history,
    overview,
    pricing,
    proposals,
    reading,
    schedulefa,
    scoring,
    watching,
)
from app.services.investments import portfolio as pf
from app.services.marketdata import feed

router = APIRouter(prefix="/api/investments", tags=["investments"])

ZERO = Decimal(0)


def _totals_out(totals, cost_basis_inr: Decimal) -> TotalsOut:
    return TotalsOut(
        cost_basis_inr=cost_basis_inr,
        invested_inr=totals.invested_inr,
        market_value_inr=totals.market_value_inr,
        unrealised_inr=totals.unrealised_inr,
        unrealised_pct=(
            totals.unrealised_inr / totals.invested_inr if totals.invested_inr else None
        ),
        realised_inr=totals.realised_inr,
        market_value_all_inr=totals.market_value_all_inr,
        unrealised_all_inr=totals.unrealised_all_inr,
        unrealised_all_pct=(
            totals.unrealised_all_inr / totals.invested_all_inr if totals.invested_all_inr else None
        ),
        ring_fenced_inr=totals.ring_fenced_inr,
        unpriced=totals.unpriced,
        stale=totals.stale,
        is_complete=totals.is_complete,
    )


def _transactions_out(db: Session, portfolio_id: uuid.UUID) -> list[TransactionOut]:
    rows = list(
        db.execute(
            sa.select(Transaction, Instrument.symbol)
            .join(Instrument, Transaction.instrument_id == Instrument.id)
            .where(Transaction.portfolio_id == portfolio_id)
            .order_by(Transaction.trade_date.desc(), Transaction.created_at.desc())
        ).all()
    )
    # Which rows have been superseded, and by what. Resolved here rather than per row so the
    # history is one query regardless of how many corrections it contains.
    replaced_by = {t.supersedes_id: t.id for t, _ in rows if t.supersedes_id is not None}
    return [
        TransactionOut(
            id=t.id,
            instrument_id=t.instrument_id,
            symbol=symbol,
            txn_type=t.txn_type,
            trade_date=t.trade_date,
            quantity=t.quantity,
            price=t.price,
            currency=t.currency,
            fx_rate_inr=t.fx_rate_inr,
            charges_inr=t.charges_inr or ZERO,
            prepaid_tax_inr=t.prepaid_tax_inr or ZERO,
            net_inr=overview.cash_effect_inr(t),
            entry_source=t.entry_source,
            note=t.note,
            created_at=t.created_at,
            supersedes_id=t.supersedes_id,
            superseded_by_id=replaced_by.get(t.id),
        )
        for t, symbol in rows
    ]


@router.get("/summary")
def get_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SummaryOut:
    """Holdings, marks, totals and both returns — one walk over the ledger.

    Split across four routes these would run the fold four times and could disagree with
    each other if a write landed between them.
    """
    book = overview.real_book(db, user.id)
    view = overview.summary(db, book.id, user.id)
    return SummaryOut(
        portfolio_id=view.portfolio_id,
        name=view.name,
        kind=view.kind,
        as_of=view.as_of,
        holdings=[HoldingOut.model_validate(h) for h in view.holdings],
        totals=_totals_out(view.totals, view.cost_basis_inr),
        by_asset_class=[AssetTotalOut.model_validate(a) for a in view.by_asset_class],
        unpriced_cost_inr=view.unpriced_cost_inr,
        returns=view.returns,
        corporate_actions=[CorporateActionOut.model_validate(a) for a in view.corporate_actions],
    )


@router.post("/prices/refresh")
def refresh_prices(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PriceRefreshOut:
    """Fetch live prices for holdings whose price is stale, and only those.

    The page calls this in the background when it opens and reloads if anything was written,
    so the figures appear at once and freshen a moment later. The assistant's portfolio tools
    call the same `feed.refresh_stale` — one implementation, two callers.

    Never fails because a source did: an unreachable source is named in `failed`.
    """
    report = feed.refresh_stale(db)
    return PriceRefreshOut(written=sum(report.written.values()), failed=sorted(report.failed))


@router.get("/holdings/{symbol}")
def get_holding(
    symbol: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HoldingDetailOut:
    """One holding: its lots, where each sits against its boundary, what selling would mean,
    the currency split where it is foreign, and its own transactions and observed prices."""
    book = overview.real_book(db, user.id)
    detail = overview.holding_detail(db, book.id, user.id, symbol)
    return HoldingDetailOut(
        holding=HoldingOut.model_validate(detail.holding),
        lots=detail.lots,
        if_sold_now=detail.if_sold_now,
        currency_split=detail.currency_split,
        transactions=[
            t
            for t in _transactions_out(db, book.id)
            if t.instrument_id == detail.holding.instrument_id
        ],
        observations=detail.observations,
        moves=detail.moves,
    )


@router.get("/transactions")
def list_transactions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    """The whole ledger, newest first — **including superseded rows.**

    They are marked rather than filtered. Hiding them would make the history tidier and
    destroy the property the append-only design exists for: seeing what you believed at the
    time, and that you corrected it.
    """
    book = overview.real_book(db, user.id)
    return _transactions_out(db, book.id)


@router.get("/history")
def get_history(
    since: dt.date | None = None,
    until: dt.date | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurveOut:
    """Cost and value over time, plus any movement too large to be a price movement."""
    book = overview.real_book(db, user.id)
    points = history.curve(db, book.id, since=since, until=until)
    covered = history.covered_range(points)
    return CurveOut(
        points=points,
        covered_from=covered[0] if covered else None,
        covered_to=covered[1] if covered else None,
        covered_days=sum(1 for point in points if point.value_inr is not None),
        total_days=len(points),
        moves=history.suspicious_moves(db, book.id),
    )


def _draft(db: Session, portfolio_id: uuid.UUID, body: DraftIn) -> entry.Draft:
    return entry.prepare(
        db,
        portfolio_id,
        symbol=body.symbol,
        txn_type=body.txn_type,
        quantity=body.quantity,
        price=body.price,
        trade_date=body.trade_date,
        exchange=body.exchange,
        name=body.name,
        asset_class=body.asset_class,
        currency=body.currency,
        fx_rate_inr=body.fx_rate_inr,
    )


def _draft_out(draft: entry.Draft) -> DraftOut:
    return DraftOut(
        symbol=draft.instrument_symbol,
        name=draft.instrument_name,
        exchange=draft.exchange,
        asset_class=draft.asset_class,
        txn_type=draft.txn_type,
        trade_date=draft.trade_date,
        quantity=draft.quantity,
        price=draft.price,
        currency=draft.currency,
        fx_rate_inr=draft.fx_rate_inr,
        charges_inr=draft.charges_inr,
        prepaid_tax_inr=draft.prepaid_tax_inr,
        gross_inr=draft.gross_inr,
        net_inr=draft.net_inr,
        warnings=draft.warnings,
        creates_instrument=draft.creates_instrument,
    )


@router.post("/transactions/draft")
def draft_transaction(
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DraftOut:
    """Validate and cost a transaction **without writing it.**

    The first of two steps on purpose. What comes back is what will be recorded — charges,
    prepaid tax, net rupees, every warning — so a person confirms a real thing rather than an
    intention.
    """
    book = overview.real_book(db, user.id)
    return _draft_out(_draft(db, book.id, body))


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
def record_transaction(
    body: DraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionOut:
    """Write it.

    ⚠ Takes the same raw inputs as the draft route and re-runs `prepare`. It deliberately
    does **not** accept a costed draft: charges the client could set are charges the client
    could set wrong.
    """
    book = overview.real_book(db, user.id)
    txn = entry.record(db, book.id, _draft(db, book.id, body), entry_source="FORM")
    db.commit()
    return next(t for t in _transactions_out(db, book.id) if t.id == txn.id)


@router.post("/transactions/{txn_id}/reverse")
def reverse_transaction(
    txn_id: uuid.UUID,
    body: ReverseIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionOut:
    """Correct a mistaken entry by recording the entry that supersedes it.

    ⚠ There is no DELETE route on this router, and there never will be. The ledger is
    append-only, and an endpoint whose name promises deletion would be a lie in the OpenAPI
    schema before it was one in the interface.
    """
    book = overview.real_book(db, user.id)
    # Scope the id to this user's book before touching it: an id is not an authorisation.
    owned = db.execute(
        sa.select(Transaction.id).where(
            Transaction.id == txn_id, Transaction.portfolio_id == book.id
        )
    ).scalar_one_or_none()
    if owned is None:
        raise NotFound("transaction")

    correction = entry.reverse(db, txn_id, note=body.note if body else None)
    db.commit()
    return next(t for t in _transactions_out(db, book.id) if t.id == correction.id)


# --- corporate actions ---------------------------------------------------------------------
#
# ⚠ These three routes exist because a split that is announced and not recorded is the one
# failure mode of this module that produces a large, alarming, entirely fictional number. The
# feed finds it; only the ledger can fix it; and the step between the two is a decision, so it
# is a button rather than something that happens silently.


def _owned_action(db: Session, action_id: uuid.UUID, portfolio_id: uuid.UUID) -> CorporateAction:
    """Fetch an action, having first checked it concerns something this book holds.

    An id is not an authorisation — the same rule the reverse route follows. An action is
    about an instrument rather than about a portfolio, so ownership is established through
    the book's own transactions.
    """
    action = db.get(CorporateAction, action_id)
    if action is None:
        raise NotFound("corporate action")
    touched = db.execute(
        sa.select(Transaction.id)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.instrument_id == action.instrument_id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if touched is None:
        raise NotFound("corporate action")
    return action


@router.get("/corporate-actions")
def list_corporate_actions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CorporateActionOut]:
    """Outstanding splits and bonuses, plus recently applied ones so they can be checked."""
    book = overview.real_book(db, user.id)
    return [
        CorporateActionOut.model_validate(a)
        for a in corpactions.views(db, book.id, corpactions.listing(db))
    ]


@router.post("/corporate-actions/{action_id}/apply")
def apply_corporate_action(
    action_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CorporateActionOut:
    """Write the quantity change into the ledger.

    The transaction it writes is an ordinary append-only entry, visible in the history and
    retired by the ordinary correction path if the exchange or the match was wrong.
    """
    book = overview.real_book(db, user.id)
    action = _owned_action(db, action_id, book.id)
    corpactions.apply(db, book.id, action)
    db.commit()
    db.refresh(action)
    return CorporateActionOut.model_validate(corpactions.view(db, book.id, action))


@router.post("/corporate-actions/{action_id}/dismiss")
def dismiss_corporate_action(
    action_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CorporateActionOut:
    """Mark an action as not applying to this book, clearing the holding's flag."""
    book = overview.real_book(db, user.id)
    action = _owned_action(db, action_id, book.id)
    corpactions.dismiss(db, action)
    db.commit()
    db.refresh(action)
    return CorporateActionOut.model_validate(corpactions.view(db, book.id, action))


@router.get("/schedule-fa")
def get_schedule_fa(
    year: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScheduleFaOut:
    """Foreign holdings as Schedule FA asks for them, for one calendar year.

    ⚠ The calendar year, not the financial year — Schedule FA is the one Indian tax figure
    reported on 1 January to 31 December, so it cannot be read off anything else here.
    """
    book = overview.real_book(db, user.id)
    return ScheduleFaOut.model_validate(
        schedulefa.report(db, book.id, year or dt.date.today().year)
    )


# --- the framework ----------------------------------------------------------------------
#
# ⚠ These routes exist so that the one guard the structural score rests on is a real gesture
# a person makes. A model may propose that a company clears a national bottleneck; the claim
# is worth nothing until someone agrees with it here. Read the approve route as the whole
# reason the score can be trusted, not as a piece of interface plumbing.


def _mapping_out(
    db: Session,
    spec: dict,
    inst: Instrument,
    mapping,
    held: set[uuid.UUID],
    mark=None,
) -> MappingOut:
    row = frameworks.bottleneck(spec, mapping.b_bottleneck)
    multiple = frameworks.multiple_for(spec, inst.sector)

    # ⚠ Market cap is price x shares, and shares come from the filing (paid-up capital over
    # face value) rather than from anywhere convenient. Without BOTH the margin of safety
    # reports unknown rather than assuming anything about the price.
    periods = fundamentals.by_period(db, inst.id, limit=6)
    years = [p for p in periods if "Q" not in p]
    shares = scoring._shares(periods, years[0]) if years else None
    price = mark.price if mark else None
    market_cap = (price * shares) if (price is not None and shares) else None

    quality = scoring.quality_score(db, inst, spec, market_cap=market_cap)
    flags = scoring.computed_flags(db, inst, price=price)
    # Two or more red flags standing is what "the narrative is running" looks like when only
    # the measured half of the checklist has been answered.
    reflexive = sum(1 for f in flags if f.verdict == "YES") >= 2
    return MappingOut(
        id=mapping.id,
        instrument_id=inst.id,
        symbol=inst.symbol,
        name=inst.name,
        sector=inst.sector,
        multiple=multiple.value,
        multiple_is_fallback=multiple.is_fallback,
        multiple_why=multiple.why,
        b_bottleneck=mapping.b_bottleneck,
        bottleneck_name=row["name"] if row else None,
        a_imperatives=list(mapping.a_imperatives or []),
        crosses_a_count=mapping.crosses_a_count,
        crossings_status=mapping.crossings_status,
        is_crisis_accelerated=mapping.is_crisis_accelerated,
        inflection_quarter=mapping.inflection_quarter,
        investability=mapping.investability,
        rationale=mapping.rationale,
        proposed_by=mapping.proposed_by,
        approved_at=mapping.approved_at,
        review_after=mapping.review_after,
        off_framework=mapping.off_framework,
        is_held=inst.id in held,
        score=AbScoreOut.model_validate(frameworks.ab_score(mapping, spec)),
        quality=QualityOut(
            earned=quality.earned,
            available=quality.available,
            ratio=quality.ratio,
            parts=[
                {"name": p.name, "points": p.points, "available": p.available, "detail": p.detail}
                for p in quality.parts
            ],
            unknown=quality.unknown,
            is_complete=quality.is_complete,
        ),
        flags=[FlagOut.model_validate(f) for f in flags],
        quadrant=scoring.quadrant(quality, reflexive),
        years_read=len(years),
    )


def _tracked_equities(db: Session) -> list[Instrument]:
    return list(
        db.execute(
            sa.select(Instrument)
            .where(
                Instrument.deleted_at.is_(None),
                Instrument.is_tracked.is_(True),
                Instrument.asset_class.in_(("EQUITY_IN", "EQUITY_US")),
            )
            .order_by(Instrument.symbol)
        ).scalars()
    )


@router.get("/framework")
def get_framework(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FrameworkOut:
    """The framework in force, where every tracked company sits in it, and what needs you."""
    book = overview.real_book(db, user.id)
    version = frameworks.current(db)
    spec = version.spec
    held = {p.instrument_id for p in pf.positions(db, book.id)}

    tracked = _tracked_equities(db)
    marks = pricing.latest(db, [i.id for i in tracked])
    mappings = []
    for inst in tracked:
        mapping = frameworks.live_mapping(db, inst.id)
        if mapping is not None:
            mappings.append(_mapping_out(db, spec, inst, mapping, held, marks.get(inst.id)))

    return FrameworkOut(
        version=version.version,
        approved_at=version.approved_at,
        imperatives=spec.get("imperatives", []),
        bottlenecks=[BottleneckOut.model_validate(b) for b in spec.get("bottlenecks", [])],
        mappings=mappings,
        attention=[AttentionOut.model_validate(a) for a in frameworks.needs_attention(db, spec)],
    )


def _owned_mapping(db: Session, mapping_id: uuid.UUID):
    mapping = db.get(AbMapping, mapping_id)
    if mapping is None:
        raise NotFound("mapping")
    return mapping


@router.post("/framework/mappings/{mapping_id}/approve")
def approve_mapping(
    mapping_id: uuid.UUID,
    body: ApproveIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MappingOut:
    """Agree that this company clears this bottleneck.

    ⚠ This single click is what lets the company score at all. Before it, the mapping is a
    suggestion and the structural score is zero however strong the company looks — which is
    the design, not a defect.
    """
    book = overview.real_book(db, user.id)
    version = frameworks.current(db)
    mapping = _owned_mapping(db, mapping_id)
    frameworks.approve_mapping(db, mapping, note=body.note if body else None)
    db.commit()

    inst = db.get(Instrument, mapping.instrument_id)
    held = {p.instrument_id for p in pf.positions(db, book.id)}
    return _mapping_out(db, version.spec, inst, mapping, held)


@router.post("/framework/mappings/{mapping_id}/remap")
def remap(
    mapping_id: uuid.UUID,
    body: RemapIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MappingOut:
    """Correct where a company sits — a different bottleneck, or out of the framework.

    The replacement is written UNAPPROVED and supersedes the old one, so the company drops
    to zero until it is confirmed. A re-mapping is a fresh claim, not one that inherits the
    agreement given to the claim it replaced.
    """
    book = overview.real_book(db, user.id)
    version = frameworks.current(db)
    mapping = _owned_mapping(db, mapping_id)
    inst = db.get(Instrument, mapping.instrument_id)
    if inst is None:
        raise NotFound("instrument")

    fresh = frameworks.propose_mapping(
        db,
        inst,
        b_bottleneck=None if body.off_framework else body.b_bottleneck,
        spec=version.spec,
        framework_version_id=version.id,
        proposed_by="USER",
        rationale=body.rationale,
        off_framework=body.off_framework,
    )
    db.commit()
    held = {p.instrument_id for p in pf.positions(db, book.id)}
    return _mapping_out(db, version.spec, inst, fresh, held)


@router.post("/framework/bottlenecks/{b_bottleneck}/crossings")
def revise_crossings(
    b_bottleneck: str,
    body: CrossingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FrameworkOut:
    """Establish which imperatives a bottleneck actually blocks.

    ⚠ The repair for the one real defect in how the framework was first loaded: the source
    notes establish the crossing set for eight bottlenecks and leave the rest unstated, and
    that count is the largest component of the structural score. Before this the interface
    could say "this figure is a floor" and offer no way to raise it.

    Writes a **new framework version**. Companies mapped to the bottleneck keep their
    approval, because what was agreed — that the company clears this bottleneck — has not
    changed; only how wide the bottleneck is, which is what is being decided here.
    """
    frameworks.revise_crossings(
        db,
        b_bottleneck=b_bottleneck,
        crosses=body.crosses,
        status=body.status,
        note=body.note,
    )
    db.commit()
    return get_framework(user=user, db=db)


# --- proposals ------------------------------------------------------------------------------
#
# ⚠ Nothing here places an order or touches the real book. Approving updates the paper book the
# system's own decisions build up; what the user does in life is their word, entered the same
# way every other transaction is. The gap between the two books is one of the most interesting
# numbers this module produces, and merging them would destroy it.


def _proposal_out(db: Session, row: Proposal) -> ProposalOut:
    inst = db.get(Instrument, row.instrument_id)
    decision = db.execute(
        sa.select(Decision).where(Decision.proposal_id == row.id)
    ).scalar_one_or_none()
    triggers = list(
        db.execute(
            sa.select(InvalidationTrigger)
            .where(InvalidationTrigger.proposal_id == row.id)
            .order_by(InvalidationTrigger.created_at)
        ).scalars()
    )
    claims = list(
        db.execute(
            sa.select(Claim).where(Claim.proposal_id == row.id).order_by(Claim.created_at)
        ).scalars()
    )
    return ProposalOut(
        id=row.id,
        symbol=inst.symbol if inst else "?",
        name=inst.name if inst else "?",
        action=row.action,
        status=proposals.effective_status(db, row),
        blocked_by=row.blocked_by,
        target_amount_inr=row.target_amount_inr,
        target_qty=row.target_qty,
        horizon_days=row.horizon_days,
        thesis=row.thesis,
        confidence=row.confidence,
        ab_score=row.ab_score,
        quality_earned=row.quality_earned,
        quality_available=row.quality_available,
        reflexivity_flags_yes=row.reflexivity_flags_yes,
        quadrant=row.quadrant,
        price_snapshot=row.price_snapshot or {},
        gates=[
            GateOut(
                gate=name,
                passed=bool(result.get("passed")),
                not_applicable=bool(result.get("not_applicable")),
                detail=str(result.get("detail", "")),
            )
            for name, result in (row.gate_results or {}).items()
        ],
        triggers=[TriggerOut.model_validate(t) for t in triggers],
        claims=[ClaimOut.model_validate(c) for c in claims],
        created_at=row.created_at,
        decided_at=decision.decided_at if decision else None,
        decision_reason=decision.reason_text if decision else None,
    )


@router.get("/proposals")
def list_proposals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalsOut:
    """What is waiting for you, and what recently happened — refusals included.

    ⚠ Blocked suggestions are returned deliberately. A rule whose cost is invisible is a rule
    nobody can evaluate, and seeing what the rails refused is the only way to judge whether
    they protect or merely obstruct.
    """
    mirror = proposals.mirror(db, user.id)
    db.commit()
    runs = db.execute(
        sa.select(sa.func.count(), sa.func.max(AgentRun.finished_at)).select_from(AgentRun)
    ).one()
    fired = list(
        db.execute(
            sa.select(InvalidationTrigger, Instrument.symbol)
            .join(Instrument, InvalidationTrigger.instrument_id == Instrument.id)
            .where(InvalidationTrigger.status == "FIRED")
            .order_by(InvalidationTrigger.fired_at.desc())
            .limit(20)
        ).all()
    )
    return ProposalsOut(
        open=[_proposal_out(db, p) for p in proposals.open_proposals(db, mirror.id)],
        recent=[_proposal_out(db, p) for p in proposals.recent(db, mirror.id)],
        runs_recorded=runs[0] or 0,
        last_run_at=runs[1],
        fired=[
            FiredTriggerOut(
                id=t.id,
                symbol=symbol,
                description=t.description,
                metric_key=t.metric_key,
                fired_at=t.fired_at,
                evidence=t.fired_evidence or {},
            )
            for t, symbol in fired
        ],
        measures=[MeasureOut.model_validate(m) for m in watching.measures(db)],
    )


@router.post("/proposals/{proposal_id}/decide")
def decide_proposal(
    proposal_id: uuid.UUID,
    body: DecideIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalOut:
    """Approve, reject or modify — with a reason, which the database requires.

    ⚠ The reason is not politeness. It is the data that eventually reveals what kinds of
    suggestion keep being turned down, and that is the only route by which the system ever
    learns anything about its own judgement.
    """
    mirror = proposals.mirror(db, user.id)
    row = db.get(Proposal, proposal_id)
    # An id is not an authorisation — the same rule every other write route follows.
    if row is None or row.portfolio_id != mirror.id:
        raise NotFound("proposal")

    proposals.decide(
        db,
        row,
        user_id=user.id,
        outcome=body.outcome.upper(),
        reason=body.reason,
        modified_amount_inr=body.modified_amount_inr,
        via="WEB",
    )
    db.commit()
    return _proposal_out(db, row)


@router.get("/books")
def get_books(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BooksOut:
    """Every book, valued at the same prices at the same moment.

    ⚠ The same prices, deliberately. Valuing one book at yesterday's close and another at
    today's live price would produce a difference that is entirely an artefact of when each
    was read, and it would look exactly like a result.
    """
    books.ensure(db, user.id, "MIRROR")
    books.ensure(db, user.id, "AI_CLEAN")
    books.seed_mirror(db, user.id)
    db.commit()

    comparison = books.compare(db, user.id)
    return BooksOut(
        lines=[BookLineOut.model_validate(line) for line in comparison.lines],
        as_of=comparison.as_of,
        readable=comparison.readable,
        unaided=books.unaided(db, user.id),
    )


# --- the reading layer -----------------------------------------------------------------------
#
# ⚠ Every instrument every source names is recorded, held or not, acted on or not. Judging a
# source on the ideas that were acted on measures the reader's filter rather than the source:
# forty companies named, three looked at, one that worked reads as 33% instead of 2.5%.


@router.get("/reading")
def get_reading(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReadingOut:
    """Where the system reads from, what has been said lately, and whether it was worth it."""
    sources = reading.registered(db)
    return ReadingOut(
        sources=[SourceOut.model_validate(s) for s in sources],
        heard=[HeardOut.model_validate(h) for h in reading.recent(db, days=days)],
        attribution=[
            AttributionOut(
                source=a.source,
                trust_tier=a.trust_tier,
                named=a.named,
                directional=a.directional,
                scored=a.scored,
                pending=a.pending,
                became_proposals=a.became_proposals,
                hit_rate=MeasureOut.model_validate(a.hit_rate),
            )
            for a in reading.attributions(db)
        ],
        awaiting_approval=sum(1 for s in sources if s.approved_at is None),
    )


@router.post("/reading/sources/{source_id}/approve")
def approve_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceOut:
    """Start reading from a source.

    ⚠ A decision, not a setting, which is why it has its own route rather than riding on a
    settings toggle. Approving a commentator changes what the system can be talked into — and
    the sourcing gate still refuses a proposal that rests on tier 3 alone, so this widens what
    is *read*, never what is *acted on*.
    """
    source = db.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise NotFound("source")
    reading.approve(db, source)
    db.commit()
    return SourceOut.model_validate(source)


@router.post("/reading/sources/{source_id}/active")
def set_source_active(
    source_id: uuid.UUID,
    body: ActiveIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SourceOut:
    """Switch a source on or off.

    ⚠ Off, never deleted. A removed source would orphan every mention that cited it and
    quietly rewrite the attribution history along with it.
    """
    source = db.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise NotFound("source")
    reading.set_active(db, source, active=body.is_active)
    db.commit()
    return SourceOut.model_validate(source)


# --- the research queue ----------------------------------------------------------------------
#
# ⚠ Without this the system can only ever say hold, trim or sell. A research analyst that can
# only comment on what you already own is a bookkeeper with opinions.


@router.get("/research")
def get_research_queue(
    include_closed: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResearchQueueOut:
    """Companies something named that you neither hold nor watch."""
    statuses = (
        ("QUEUED", "ANALYSING", "PROMOTED", "DISMISSED")
        if include_closed
        else ("QUEUED", "ANALYSING")
    )
    size, refreshed = db.execute(
        sa.select(sa.func.count(), sa.func.max(ListedCompany.refreshed_at)).where(
            ListedCompany.delisted_at.is_(None)
        )
    ).one()
    return ResearchQueueOut(
        lines=[QueueLineOut.model_validate(line) for line in reading.queue(db, statuses=statuses)],
        universe_size=size,
        universe_refreshed_at=refreshed,
    )


@router.post("/research/{candidate_id}/promote")
def promote_candidate(
    candidate_id: uuid.UUID,
    body: PromoteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueueLineOut:
    """Start following a candidate, so it is priced, filed and scored.

    ⚠ An explicit act, because it is the moment the candidate starts costing something. Until
    now it has been a name in a list.
    """
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFound("candidate")
    reading.promote(db, candidate, sector=body.sector)
    db.commit()
    line = next(
        (row for row in reading.queue(db, statuses=("PROMOTED",)) if row.id == candidate_id),
        None,
    )
    if line is None:
        raise NotFound("candidate")
    return QueueLineOut.model_validate(line)


@router.post("/research/{candidate_id}/dismiss")
def dismiss_candidate(
    candidate_id: uuid.UUID,
    body: DismissIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueueLineOut:
    """Drop a candidate, with a reason.

    ⚠ The reason is data, not politeness — it is the only record of what kinds of idea keep
    being refused, and the database refuses a dismissal without one.
    """
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFound("candidate")
    reading.dismiss(db, candidate, body.reason)
    db.commit()
    line = next(
        (row for row in reading.queue(db, statuses=("DISMISSED",)) if row.id == candidate_id),
        None,
    )
    if line is None:
        raise NotFound("candidate")
    return QueueLineOut.model_validate(line)


@router.post("/inbox")
def drop_into_inbox(
    body: DropIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DropOut:
    """Drop a link, a video or a note, and have it filed against the companies it names.

    ⚠ **You become a measured source.** What you drop is recorded exactly the way a channel's
    uploads are, with the same mention rows behind it — which is what eventually answers
    whether the tips you act on beat the exchange feed you ignore.
    """
    result = reading.drop(db, url=body.url, text=body.text)
    db.commit()
    return DropOut(
        stored=result.stored,
        title=result.title,
        url=result.url,
        trust_tier=result.trust_tier,
        named=result.named,
        discovered=result.discovered,
        already_followed=result.already_followed,
        note=result.note,
    )
