import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

COOKIE_NAME = "access_token"
_BEARER_PREFIX = "Bearer "

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


def _extract_token(request: Request) -> str | None:
    """Prefer an `Authorization: Bearer <token>` header (works cross-site in every
    browser), falling back to the cookie (used same-origin / in dev)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith(_BEARER_PREFIX):
        return auth[len(_BEARER_PREFIX) :].strip() or None
    return request.cookies.get(COOKIE_NAME)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
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
