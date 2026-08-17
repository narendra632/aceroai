"""Trace capture: every model call recorded, nothing about it able to break a reply.

The two guarantees the whole design rests on are the first two tests here. If either
fails, the feature is worse than not having it.
"""

import json

from sqlalchemy import select

from app.db.models import Span, Turn
from tests.test_chat import _parse_sse


def _call(id_, name, args):
    return {"id": id_, "name": name, "arguments": json.dumps(args)}


def _turns(db, user, kind=None):
    stmt = select(Turn).where(Turn.user_id == user.id).order_by(Turn.started_at)
    if kind:
        stmt = stmt.where(Turn.kind == kind)
    return list(db.execute(stmt).scalars().all())


# --- the guarantees ----------------------------------------------------------------


def test_a_trace_write_failure_never_affects_the_reply(auth_client, db, user, monkeypatch):
    """An observability system that can break the thing it observes is worse than none."""

    def explode(*args, **kwargs):
        raise RuntimeError("trace storage is down")

    monkeypatch.setattr("app.core.telemetry.Timeline.persist", explode)

    events = _parse_sse(auth_client.post("/api/chat", json={"message": "hello"}).text)
    kinds = [e for e, _ in events]

    # Deltas arrive as separate SSE frames, so reassemble before asserting.
    assert "".join(d for e, d in events if e == "delta") == "Hello, there."
    assert kinds[-1] == "done"
    assert "error" not in kinds


def test_traces_never_store_message_text(auth_client, db, user):
    """`messages` already holds the content. Duplicating it here would double both the
    disk footprint and the blast radius of a leak."""
    secret = "my bank password is hunter2"
    auth_client.post("/api/chat", json={"message": secret})

    for turn in _turns(db, user):
        assert secret not in json.dumps(
            {c.name: str(getattr(turn, c.name)) for c in turn.__table__.columns}
        )
        for span in db.execute(select(Span).where(Span.turn_id == turn.id)).scalars():
            assert secret not in json.dumps(span.meta or {})
            assert secret not in span.name


# --- what gets recorded -------------------------------------------------------------


def test_a_chat_turn_is_recorded_with_its_stages(auth_client, db, user):
    auth_client.post("/api/chat", json={"message": "hello"})

    chat = _turns(db, user, kind="chat")
    assert len(chat) == 1
    turn = chat[0]
    assert turn.ok is True
    assert turn.duration_ms is not None
    assert turn.provider and turn.model
    assert turn.tokens_in == 5 and turn.tokens_out == 3  # from the fake provider

    spans = (
        db.execute(select(Span).where(Span.turn_id == turn.id).order_by(Span.seq)).scalars().all()
    )
    names = [s.name for s in spans]
    assert "persist_user" in names
    assert "memory_recall" in names
    assert "build_context" in names
    assert any(n.startswith("llm_round") for n in names)
    assert [s.seq for s in spans] == sorted(s.seq for s in spans)


def test_a_failed_turn_is_recorded_not_lost(auth_client, db, user, monkeypatch):
    """A dashboard that only shows successes hides the thing you most need to see."""

    async def boom(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        raise RuntimeError("provider exploded")
        yield  # pragma: no cover

    monkeypatch.setattr("app.core.llm.stream_with_tools", boom)

    auth_client.post("/api/chat", json={"message": "hello"})

    chat = _turns(db, user, kind="chat")
    assert len(chat) == 1
    assert chat[0].ok is False
    assert chat[0].error_type == "RuntimeError"


def test_a_tool_turn_records_its_round_count_and_tool_spans(auth_client, db, user, monkeypatch):
    state = {"i": 0}
    turns_script = [
        [("tool_calls", [_call("c1", "list_tasks", {})])],
        [("delta", "All done.")],
    ]

    async def fake(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        script = turns_script[min(state["i"], len(turns_script) - 1)]
        state["i"] += 1
        if usage is not None:
            usage["tokens_in"] = 900
            usage["tokens_out"] = 30
        for kind, payload in script:
            yield kind, payload

    monkeypatch.setattr("app.core.llm.stream_with_tools", fake)

    auth_client.post("/api/chat", json={"message": "what are my tasks"})

    turn = _turns(db, user, kind="chat")[0]
    assert turn.rounds == 2
    # Two rounds at 900/30 each — the accumulation, stored.
    assert turn.tokens_in == 1800
    assert turn.tokens_out == 60

    names = [s.name for s in db.execute(select(Span).where(Span.turn_id == turn.id)).scalars()]
    assert "tool:list_tasks" in names


# --- the spend that used to be invisible ---------------------------------------------


def test_recall_embedding_is_recorded_as_its_own_turn(auth_client, db, user):
    """An embedding fires on every message and was billed but never counted."""
    auth_client.post("/api/chat", json={"message": "hello"})

    embeds = _turns(db, user, kind="embed")
    assert len(embeds) == 1
    assert embeds[0].session_id is None  # background work has no conversation
    assert embeds[0].model


def test_the_fact_extractor_is_recorded_as_its_own_turn(auth_client, db, user, monkeypatch):
    """A SECOND full model call fires after every message. It was the largest invisible
    line in the bill."""
    monkeypatch.setattr("app.config.settings.memory_extraction_enabled", True)

    auth_client.post("/api/chat", json={"message": "I collect vinyl records"})

    for _ in range(60):
        rows = _turns(db, user, kind="memory_extract")
        if rows:
            break
        import time as _t

        _t.sleep(0.05)
        db.expire_all()

    assert rows, "the extractor ran but was never recorded"
    assert rows[0].kind == "memory_extract"


def test_one_message_produces_several_attributable_calls(auth_client, db, user, monkeypatch):
    """The headline finding: a single message is not a single model call."""
    monkeypatch.setattr("app.config.settings.memory_extraction_enabled", True)

    auth_client.post("/api/chat", json={"message": "I play the sitar"})

    for _ in range(60):
        kinds = {t.kind for t in _turns(db, user)}
        if {"chat", "embed", "memory_extract"} <= kinds:
            break
        import time as _t

        _t.sleep(0.05)
        db.expire_all()

    assert {"chat", "embed", "memory_extract"} <= kinds, f"only recorded: {kinds}"


# --- cost ---------------------------------------------------------------------------


def test_cost_is_frozen_with_the_pricing_version_that_produced_it(auth_client, db, user):
    from app.core import pricing

    auth_client.post("/api/chat", json={"message": "hello"})

    turn = _turns(db, user, kind="chat")[0]
    assert turn.pricing_version == pricing.PRICING_VERSION
    # The fake provider reports real token counts, and the default model is priced.
    assert turn.cost_usd is not None


def test_a_cancelled_extraction_is_not_recorded_as_a_success(db, user, monkeypatch):
    """Every server restart cancels pending extractions. `CancelledError` derives from
    BaseException, so it slips past `except Exception` — without an explicit branch those
    turns were stored as successful and free, quietly diluting the error rate."""
    import asyncio as aio

    from app.core import memory

    async def hang(*args, **kwargs):
        await aio.sleep(60)

    monkeypatch.setattr("app.core.llm.complete", hang)

    async def run():
        task = aio.create_task(memory.extract_and_store(user.id, "hi", "hello", known=[]))
        await aio.sleep(0.1)
        task.cancel()
        try:
            await task
        except aio.CancelledError:
            pass

    aio.run(run())

    rows = _turns(db, user, kind="memory_extract")
    assert rows, "a cancelled extraction still consumed time and must be recorded"
    assert rows[0].ok is False
    assert rows[0].error_type == "CancelledError"
