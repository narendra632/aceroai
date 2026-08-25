"""Reading the traces.

**Strictly read-only.** No route here creates, changes or deletes anything, which is what
makes the page safe to open, reload, and leave open. If a mutation ever belongs on this
screen it belongs in a different router, so that guarantee stays checkable at a glance.

Deliberately not in Settings: Settings is for *choices*, Insights is for *observation*.
Burying a page worth a weekly look inside one touched twice a year guarantees it goes unread.
"""

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import (
    CapacityOut,
    ErrorCount,
    InsightsOverview,
    InsightsSummary,
    ModelUsage,
    ProviderComparison,
    RecalledFactOut,
    SeriesPoint,
    SpanOut,
    TurnDetail,
    TurnOut,
    VitalsOut,
)
from app.config import settings
from app.core import pricing
from app.db.models import User
from app.db.session import get_db
from app.services import insights as svc
from app.services import memory as memory_svc
from app.services import vitals as vitals_svc
from app.services.errors import NotFound

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])

# Ranges the UI offers. A brush-to-zoom control would be more flexible and worse: for
# "what did I spend", preset ranges are what people actually reach for.
MAX_DAYS = 365


def _since(days: int | None) -> dt.datetime | None:
    """None means everything ever recorded."""
    if days is None:
        return None
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=days)


@router.get("/overview")
def overview(
    days: int | None = Query(default=30, ge=1, le=MAX_DAYS),
    all_time: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InsightsOverview:
    """Everything the page needs, in one request.

    Six separate calls would each pay the same cold-connection cost to a VM in Oregon. The
    queries themselves are cheap; the round-trips are not.
    """
    since = None if all_time else _since(days)
    return InsightsOverview(
        summary=InsightsSummary(**svc.summary(db, user.id, since=since)),
        series=[SeriesPoint(**p) for p in svc.series(db, user.id, since=since)],
        by_model=[ModelUsage(**m) for m in svc.by_model(db, user.id, since=since)],
        by_provider=[ProviderComparison(**p) for p in svc.by_provider(db, user.id, since=since)],
        errors=[ErrorCount(**e) for e in svc.errors(db, user.id, since=since)],
        data_start=svc.data_start(db, user.id),
        pricing_version=pricing.PRICING_VERSION,
    )


@router.get("/turns")
def recent_turns(
    limit: int = Query(default=50, ge=1, le=200),
    kind: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TurnOut]:
    return [TurnOut.model_validate(t) for t in svc.recent(db, user.id, limit=limit, kind=kind)]


def _recalled_facts(db: Session, user_id: uuid.UUID, spans) -> list[RecalledFactOut]:
    """Resolve the fact ids on the `memory_recall` span into readable text.

    The span stores IDS, not text — traces record shape and never message content, and this
    keeps that rule intact while still answering "which facts did that turn use?" for a turn
    that is no longer open in the browser. The chat popover can only explain the session
    still on screen; this explains any turn ever recorded.

    Resolved live rather than snapshotted, so a fact that has since been corrected shows its
    current text. A fact forgotten in the meantime simply drops out — `get_fact` hides it,
    and a forgotten fact must be unreachable from every path, including this one.
    """
    span = next((s for s in spans if s.name == "memory_recall"), None)
    ids = (span.meta or {}).get("fact_ids") if span is not None else None
    if not ids:
        return []
    out: list[RecalledFactOut] = []
    for raw in ids:
        try:
            fact = memory_svc.get_fact(db, user_id, uuid.UUID(str(raw)))
        except (NotFound, ValueError):
            continue
        out.append(RecalledFactOut(id=fact.id, fact=fact.fact, category=fact.category))
    return out


@router.get("/turns/{turn_id}")
def turn_detail(
    turn_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TurnDetail:
    """One turn broken into its stages — the data behind the waterfall.

    This view is the reason the whole feature exists: it is what made a 12-second embedding
    stall obvious once, by reading raw logs. Here it is a click.
    """
    found = svc.turn_with_spans(db, user.id, turn_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="turn not found")
    turn, spans = found
    return TurnDetail(
        turn=TurnOut.model_validate(turn),
        spans=[SpanOut.model_validate(s) for s in spans],
        recalled=_recalled_facts(db, user.id, spans),
    )


@router.get("/vitals", response_model=VitalsOut)
def vitals(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VitalsOut:
    """What the machine is doing right now.

    ⚠ **Deliberately NOT part of `/health`.** That endpoint is unauthenticated — Caddy probes
    it, and it is what proves the backend is alive from outside the network when something
    breaks. Disk figures, memory totals and database size are infrastructure detail, and
    "the health endpoint grew a few useful fields" is exactly how an unauthenticated endpoint
    becomes a reconnaissance surface. `/health` returns `{"status": "ok"}` and nothing else.

    Read-only, so it does not violate this router's guarantee — but it is the one route here
    whose answer changes between two identical requests, which is why it forbids caching
    explicitly rather than relying on a client to know better.

    Every measurement may be absent. `/proc` is Linux-only, so on the development machine
    memory and load are `null` and the interface omits them. See `services/vitals`.
    """
    response.headers["Cache-Control"] = "no-store"

    def safe(read, *args):
        """One unreadable source degrades ONE FIELD, never the response.

        Each reader in `services/vitals` already handles its own expected failure. This is
        the structural version of the same promise: it holds for a reader that forgets, or
        one added later by someone who did not read this docstring.

        It matters because this endpoint is polled every ten seconds. A monitoring surface
        that can itself fail loudly does not report incidents, it manufactures them.
        """
        try:
            return read(*args)
        except Exception:  # noqa: BLE001 - a vital sign must never take the page with it
            log.warning("vital sign %s could not be read", getattr(read, "__name__", read))
            return None

    def cap(reading: vitals_svc.Capacity | None) -> CapacityOut | None:
        if reading is None:
            return None
        return CapacityOut(
            used_bytes=reading.used_bytes,
            total_bytes=reading.total_bytes,
            percent=round(reading.percent, 1),
        )

    return VitalsOut(
        disk=cap(safe(vitals_svc.disk)),
        memory=cap(safe(vitals_svc.memory)),
        load_1m=safe(vitals_svc.load_average),
        database_bytes=safe(vitals_svc.database_bytes, db),
        last_tick=safe(vitals_svc.last_tick),
        # Arithmetic on a module constant — it has no failure mode, and wrapping it would
        # imply one.
        uptime_seconds=round(vitals_svc.uptime_seconds(), 1),
        tick_interval_seconds=settings.job_tick_seconds,
        disk_warn_percent=settings.disk_warn_percent,
    )
