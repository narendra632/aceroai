"""Telegram channel — a thin adapter over the Bot API using long-polling.

Every message flows through core/handler.handle_message; this file holds no
conversation logic (golden rule 1). Uses httpx directly — no extra dependency.
The bot pulls updates from Telegram (outbound calls), so it needs no hosting to
run: start the backend locally and message the bot from anywhere.
"""

import asyncio
import logging

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.handler import handle_message
from app.db.models import ChatSession, User
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 25
MSG_LIMIT = 4096  # Telegram's per-message character cap


def _api_url(method: str) -> str:
    return f"{API_BASE}/bot{settings.telegram_bot_token}/{method}"


async def get_updates(client: httpx.AsyncClient, offset: int | None) -> list[dict]:
    params: dict = {"timeout": POLL_TIMEOUT}
    if offset is not None:
        params["offset"] = offset
    r = await client.get(_api_url("getUpdates"), params=params)
    r.raise_for_status()
    return r.json().get("result", [])


async def send_message(client: httpx.AsyncClient, chat_id: int, text: str) -> None:
    for i in range(0, len(text) or 1, MSG_LIMIT):
        await client.post(
            _api_url("sendMessage"),
            json={"chat_id": chat_id, "text": text[i : i + MSG_LIMIT]},
        )


# --- DB helpers (sync; called via run_in_threadpool) ---


def _load_user(db: Session) -> User | None:
    # single-user app: the one (oldest) user
    return db.execute(select(User).order_by(User.created_at)).scalars().first()


def _link_chat(db: Session, user: User, chat_id: int) -> None:
    user.telegram_chat_id = chat_id
    db.commit()


def _latest_session(db: Session, user: User):
    return (
        db.execute(
            select(ChatSession.id)
            .where(ChatSession.user_id == user.id, ChatSession.channel == "telegram")
            .order_by(ChatSession.last_active_at.desc())
        )
        .scalars()
        .first()
    )


async def handle_update(update: dict, send) -> None:
    """Process one Telegram update. `send(chat_id, text)` is injected so this is
    unit-testable without the network."""
    message = update.get("message") or {}
    text = message.get("text")
    chat_id = (message.get("chat") or {}).get("id")
    if not text or chat_id is None:
        return

    db = SessionLocal()
    try:
        user = await run_in_threadpool(_load_user, db)
        if user is None:
            return
        linked = user.telegram_chat_id

        if text.strip() == "/start":
            if linked is None:
                await run_in_threadpool(_link_chat, db, user, chat_id)
                await send(chat_id, "Linked. You can chat with Acero here now.")
            elif linked == chat_id:
                await send(chat_id, "Already linked — go ahead.")
            else:
                await send(chat_id, "This bot is linked to another account.")
            return

        if linked != chat_id:
            await send(
                chat_id,
                "This chat is not authorized. Send /start to link if you're the owner.",
            )
            return

        session_id = await run_in_threadpool(_latest_session, db, user)
        parts: list[str] = []
        async for event, data in handle_message(db, user, text, "telegram", session_id):
            if event == "delta":
                parts.append(data)
            elif event == "error":
                await send(chat_id, f"⚠ {data}")
                return
        reply = "".join(parts).strip()
        if reply:
            await send(chat_id, reply)
    finally:
        db.close()


async def run_poller() -> None:
    """Long-poll Telegram and dispatch updates. A no-op without a token."""
    if not settings.telegram_bot_token:
        return
    log.info("telegram poller starting")
    offset: int | None = None
    async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 15) as client:

        async def send(chat_id: int, text: str) -> None:
            await send_message(client, chat_id, text)

        while True:
            try:
                for update in await get_updates(client, offset):
                    offset = update["update_id"] + 1
                    await handle_update(update, send)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("telegram poll error; backing off")
                await asyncio.sleep(3)
