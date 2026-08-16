import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_user
from app.api.schemas import MessageIn, MessageOut, SessionOut, SessionPatch
from app.config import settings
from app.core.handler import handle_message
from app.db.models import User
from app.db.session import get_db
from app.services import sessions as svc

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    body: MessageIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    if body.session_id is not None:
        svc.get_session(db, user.id, body.session_id)

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
    return [SessionOut.model_validate(s) for s in svc.list_sessions(db, user.id)]


@router.patch("/sessions/{session_id}")
def rename_session(
    session_id: uuid.UUID,
    body: SessionPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionOut:
    return SessionOut.model_validate(svc.rename_session(db, user.id, session_id, body.title))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a conversation so it can be undone. Its messages are kept, and
    learned profile facts are deliberately untouched — memory about the user outlives
    any single conversation."""
    svc.delete_session(db, user.id, session_id)


@router.post("/sessions/{session_id}/restore")
def restore_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionOut:
    return SessionOut.model_validate(svc.restore_session(db, user.id, session_id))


@router.post("/sessions/{session_id}/regenerate", status_code=status.HTTP_204_NO_CONTENT)
def regenerate(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Drop the trailing assistant reply so the client can re-send the turn. A no-op if
    the last message is the user's — there is then nothing to regenerate."""
    svc.drop_last_reply(db, user.id, session_id)


@router.get("/sessions/{session_id}/messages")
def get_history(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    return [MessageOut.model_validate(m) for m in svc.list_messages(db, user.id, session_id)]
