import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

COOKIE_NAME = "access_token"

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _UNAUTHENTICATED
    try:
        user_id = decode_access_token(token)
        user = db.get(User, uuid.UUID(user_id))
    except Exception as exc:  # invalid/expired token or bad uuid
        raise _UNAUTHENTICATED from exc
    if user is None:
        raise _UNAUTHENTICATED
    return user
