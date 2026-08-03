import datetime as dt
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.schemas import JournalIn, JournalOut, JournalUpdate
from app.db.models import User
from app.db.session import get_db
from app.services import journal as svc

router = APIRouter(prefix="/api/journal", tags=["journal"])


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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[JournalOut]:
    rows = svc.list_entries(db, user.id, start=start, end=end)
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
    svc.delete_entry(db, user.id, entry_id)
