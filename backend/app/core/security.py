import datetime as dt

import bcrypt
import jwt

from app.config import settings

JWT_ALGO = "HS256"
TOKEN_TTL_DAYS = 30


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": dt.datetime.now(dt.UTC) + dt.timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGO)


def decode_access_token(token: str) -> str:
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGO])["sub"]
