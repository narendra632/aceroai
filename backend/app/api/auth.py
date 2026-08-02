from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import COOKIE_NAME, get_current_user
from app.api.schemas import LoginIn
from app.config import settings
from app.core.security import TOKEN_TTL_DAYS, create_access_token, verify_password
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_MAX_AGE = TOKEN_TTL_DAYS * 24 * 60 * 60


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = create_access_token(str(user.id))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        # dev: Lax/insecure over http. prod: SameSite=None; Secure so the cookie is
        # sent cross-site from the Vercel frontend (see app.config).
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        path="/",
    )
    return {"email": user.email}


@router.post("/logout")
def logout(response: Response) -> dict:
    # Match the set attributes so the browser reliably clears the cookie.
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
    )
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"email": user.email}
