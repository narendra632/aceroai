"""Token accounting across a turn.

Written during §0 of `add-knowledge-graph-and-observability` to *capture* the defects
before they are fixed, so the fix has evidence rather than a claim behind it.

The defect tests are `xfail(strict=True)` on purpose: the suite stays green today, and the
moment the accounting is fixed an unexpected PASS fails the run and forces the marker to be
removed. A plain failing test would just be noise someone learns to ignore.
"""

import json

import pytest
from sqlalchemy import select

from app.db.models import ChatSession, Message


def _call(id_, name, args):
    return {"id": id_, "name": name, "arguments": json.dumps(args)}


def _rounds_fake(rounds):
    """Fake `stream_with_tools` where each successive round reports its own usage.

    Mirrors how a real provider behaves: usage is per *request*, and a tool-using turn
    makes several requests. The last round repeats if called again.
    """
    state = {"i": 0}

    async def fake(messages, tools=None, model=None, usage=None, effort=None, provider=None):
        r = rounds[min(state["i"], len(rounds) - 1)]
        state["i"] += 1
        if usage is not None:
            usage["tokens_in"] = r["tokens_in"]
            usage["tokens_out"] = r["tokens_out"]
        for kind, payload in r["events"]:
            yield kind, payload

    return fake


def _last_assistant_message(db, user):
    return (
        db.execute(
            select(Message)
            .join(ChatSession, Message.session_id == ChatSession.id)
            .where(ChatSession.user_id == user.id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
        )
        .scalars()
        .first()
    )


# Two rounds: the model calls a tool, then answers. The provider billed both.
TWO_ROUNDS = [
    {
        "tokens_in": 1000,
        "tokens_out": 40,
        "events": [("tool_calls", [_call("c1", "list_tasks", {})])],
    },
    {"tokens_in": 1500, "tokens_out": 90, "events": [("delta", "All done.")]},
]
BILLED_IN = 2500  # 1000 + 1500
BILLED_OUT = 130  # 40 + 90


def test_single_round_usage_is_recorded(auth_client, db, user, monkeypatch):
    """The case that already works — a plain chat turn with one model round.

    Present so that when the multi-round fix lands, a regression here is distinguishable
    from a regression in the fix itself.
    """
    monkeypatch.setattr(
        "app.core.llm.stream_with_tools",
        _rounds_fake([{"tokens_in": 700, "tokens_out": 25, "events": [("delta", "Hi.")]}]),
    )

    auth_client.post("/api/chat", json={"message": "hello"})

    msg = _last_assistant_message(db, user)
    assert (msg.tokens_in, msg.tokens_out) == (700, 25)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT B (proposal.md): one `usage` dict is created per turn (handler.py) and each "
        "round ASSIGNS into it instead of accumulating, so only the final round survives. "
        "Remove this marker in task 5.4."
    ),
)
def test_multi_round_usage_is_the_total_not_the_last_round(auth_client, db, user, monkeypatch):
    monkeypatch.setattr("app.core.llm.stream_with_tools", _rounds_fake(TWO_ROUNDS))

    auth_client.post("/api/chat", json={"message": "what are my tasks"})

    msg = _last_assistant_message(db, user)
    assert (msg.tokens_in, msg.tokens_out) == (BILLED_IN, BILLED_OUT)


def test_multi_round_usage_currently_records_only_the_last_round(
    auth_client, db, user, monkeypatch
):
    """Pins the *current, wrong* behaviour so §0's claim is measured, not asserted.

    Delete this test in task 5.4 — once the fix lands it is documenting a bug that no
    longer exists, and a test that enforces a defect is worse than no test.
    """
    monkeypatch.setattr("app.core.llm.stream_with_tools", _rounds_fake(TWO_ROUNDS))

    auth_client.post("/api/chat", json={"message": "what are my tasks"})

    msg = _last_assistant_message(db, user)
    assert (msg.tokens_in, msg.tokens_out) == (1500, 90)
    assert msg.tokens_in < BILLED_IN  # 60% of the input tokens were never recorded
