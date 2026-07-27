import asyncio
import uuid

import app.channels.telegram as tg


class FakeUser:
    def __init__(self, chat_id: int | None):
        self.id = uuid.uuid4()
        self.telegram_chat_id = chat_id


def _msg(chat_id: int, text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def _run(update, send, monkeypatch, user, handler=None, session=None):
    monkeypatch.setattr(tg, "_load_user", lambda db: user)
    monkeypatch.setattr(tg, "_latest_session", lambda db, u: session)
    monkeypatch.setattr(tg, "_link_chat", lambda db, u, cid: setattr(u, "telegram_chat_id", cid))
    if handler is not None:
        monkeypatch.setattr(tg, "handle_message", handler)
    asyncio.run(tg.handle_update(update, send))


def test_authorized_message_routed_and_replied(monkeypatch):
    sent: list[tuple[int, str]] = []

    async def send(cid, text):
        sent.append((cid, text))

    async def fake_hm(db, user, text, channel, session_id):
        assert channel == "telegram"
        yield ("delta", "Hello ")
        yield ("delta", "there.")
        yield ("done", "mid")

    _run(_msg(111, "hi"), send, monkeypatch, FakeUser(111), handler=fake_hm)
    assert sent == [(111, "Hello there.")]


def test_start_links_first_time(monkeypatch):
    sent: list[tuple[int, str]] = []

    async def send(cid, text):
        sent.append((cid, text))

    user = FakeUser(None)
    _run(_msg(222, "/start"), send, monkeypatch, user)
    assert user.telegram_chat_id == 222
    assert "linked" in sent[-1][1].lower()


def test_stranger_rejected_without_calling_handler(monkeypatch):
    sent: list[tuple[int, str]] = []
    called = {"hm": False}

    async def send(cid, text):
        sent.append((cid, text))

    async def fake_hm(*args, **kwargs):
        called["hm"] = True
        yield ("done", "x")

    _run(_msg(999, "hello"), send, monkeypatch, FakeUser(555), handler=fake_hm)
    assert called["hm"] is False
    assert "not authorized" in sent[-1][1].lower()


def test_error_event_reported(monkeypatch):
    sent: list[tuple[int, str]] = []

    async def send(cid, text):
        sent.append((cid, text))

    async def fake_hm(db, user, text, channel, session_id):
        yield ("error", "boom")

    _run(_msg(111, "hi"), send, monkeypatch, FakeUser(111), handler=fake_hm)
    assert "boom" in sent[-1][1]


def test_non_text_update_ignored(monkeypatch):
    sent: list[tuple[int, str]] = []

    async def send(cid, text):
        sent.append((cid, text))

    # a sticker/photo update with no text — nothing should happen
    asyncio.run(tg.handle_update({"update_id": 2, "message": {"chat": {"id": 1}}}, send))
    assert sent == []


def test_poller_skips_without_token(monkeypatch):
    monkeypatch.setattr(tg.settings, "telegram_bot_token", "")
    asyncio.run(tg.run_poller())  # returns immediately, no hang
