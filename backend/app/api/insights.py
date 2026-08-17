"""Reading the traces.

**Strictly read-only.** No route here creates, changes or deletes anything, which is what
makes the page safe to open, reload, and leave open. If a mutation ever belongs on this
screen it belongs in a different router, so that guarantee stays checkable at a glance.

Deliberately not in Settings: Settings is for *choices*, Insights is for *observation*.
Burying a page worth a weekly look inside one touched twice a year guarantees it goes unread.
"""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import (
    ErrorCount,
    InsightsOverview,
    InsightsSummary,
    ModelUsage,
    ProviderComparison,
    SeriesPoint,
    SpanOut,
    TurnDetail,
    TurnOut,
)
from app.config import settings
from app.core import pricing
from app.db.models import User
from app.db.session import get_db
from app.services import insights as svc

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
        series=[
            SeriesPoint(**p) for p in svc.series(db, user.id, since=since, tz=settings.app_timezone)
        ],
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
    )
