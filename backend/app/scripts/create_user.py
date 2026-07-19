"""Run from backend/:  uv run python -m app.scripts.create_user"""

from getpass import getpass

from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal


def main() -> None:
    email = input("email: ").strip()
    password = getpass("password: ")
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password(password)))
        db.commit()
    print(f"created user {email}")


if __name__ == "__main__":
    main()
