import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.api.schemas import MessageIn, MessageOut, SessionOut
from app.config import settings
from app.core.handler import handle_message
from app.db.models import ChatSession, Message, User
from app.db.session import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


def _owned_session(db: Session, session_id: uuid.UUID, user: User) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise _NOT_FOUND
    return session


@router.post("")
async def chat(
    body: MessageIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    if body.session_id is not None:
        _owned_session(db, body.session_id, user)

    # Explicit user control: "think harder" routes this turn to deeper reasoning.
    effort = settings.reasoning_effort_deep if body.deep else None

    async def events():
        async for event, data in handle_message(
            db, user, body.message, "web", body.session_id, reasoning_effort=effort
        ):
            yield {"event": event, "data": data}

    return EventSourceResponse(events())


@router.get("/sessions")
def list_sessions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[SessionOut]:
    rows = (
        db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(ChatSession.last_active_at.desc())
        )
        .scalars()
        .all()
    )
    return [SessionOut.model_validate(r) for r in rows]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a conversation and its messages. Owner-scoped; learned profile facts are
    deliberately kept — memory about the user outlives any single conversation."""
    session = _owned_session(db, session_id, user)
    db.execute(delete(Message).where(Message.session_id == session.id))
    db.delete(session)
    db.commit()


@router.get("/sessions/{session_id}/messages")
def get_history(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    _owned_session(db, session_id, user)
    rows = (
        db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        .scalars()
        .all()
    )
    return [MessageOut.model_validate(r) for r in rows]
