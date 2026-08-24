import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import JournalIn, JournalOut, JournalUpdate, ReviewOut
from app.db.models import GeneratedReview, User
from app.db.session import get_db
from app.services import journal as svc

router = APIRouter(prefix="/api/journal", tags=["journal"])

# Briefings live under /api/journal rather than a route of their own because they are the
# same shape as a journal entry — dated, one per day, reflective — and sit beside them in
# the interface as a second tab. The difference is authorship: the user wrote one, Acero
# wrote the other, and the UI never blurs that.


@router.post("", status_code=status.HTTP_201_CREATED)
def add_entry(
    body: JournalIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalOut:
    entry = svc.add_entry(
        db,
        user.id,
        content=body.content,
        mood=body.mood,
        tags=body.tags,
        channel="web",
        entry_date=body.entry_date,
    )
    return JournalOut.model_validate(entry)


@router.get("")
def list_entries(
    start: dt.date | None = None,
    end: dt.date | None = None,
    q: str | None = None,
    limit: int = Query(default=svc.LIST_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JournalOut]:
    """The journal grows without bound, so listing is paged and searchable rather than
    returning every entry ever written."""
    rows = svc.list_entries(db, user.id, start=start, end=end, q=q, limit=limit, offset=offset)
    return [JournalOut.model_validate(e) for e in rows]


@router.patch("/{entry_id}")
def update_entry(
    entry_id: uuid.UUID,
    body: JournalUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalOut:
    entry = svc.update_entry(db, user.id, entry_id, **body.model_dump(exclude_unset=True))
    return JournalOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft delete — reversible via /restore for as long as the client offers Undo."""
    svc.delete_entry(db, user.id, entry_id)


@router.post("/{entry_id}/restore")
def restore_entry(
    entry_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JournalOut:
    return JournalOut.model_validate(svc.restore_entry(db, user.id, entry_id))


@router.get("/briefings", response_model=list[ReviewOut])
def list_briefings(
    limit: int = Query(default=60, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewOut]:
    """What Acero wrote about the user's days, newest first.

    Read-only by design. A briefing is a record of what was said on a given morning or
    evening; editing it would make it a note the user wrote, which is what the journal is
    already for.
    """
    from sqlalchemy import select

    rows = (
        db.execute(
            select(GeneratedReview)
            .where(GeneratedReview.user_id == user.id)
            .order_by(GeneratedReview.period_start.desc(), GeneratedReview.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [ReviewOut.model_validate(r) for r in rows]
