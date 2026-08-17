"""Token accounting across a turn.

Written during §0 to *capture* defect B before fixing it, as an `xfail(strict=True)`: the
suite stayed green while the bug existed, and the moment it was fixed the unexpected PASS
failed the run and forced this cleanup. A plain failing test would have been noise someone
learned to ignore.

What it was catching: one `usage` dict per turn that each tool round ASSIGNED into, so a
turn billed 2,500 in / 130 out recorded 1,500 / 90 — the last round alone. The fix splits
the two levels apart: `set_usage` assigns within a request (providers repeat cumulative
totals), `add_usage` sums across requests, and `handler` folds a fresh per-round dict into
the turn.
"""

import json

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


def test_multi_round_usage_is_the_total_not_the_last_round(auth_client, db, user, monkeypatch):
    monkeypatch.setattr("app.core.llm.stream_with_tools", _rounds_fake(TWO_ROUNDS))

    auth_client.post("/api/chat", json={"message": "what are my tasks"})

    msg = _last_assistant_message(db, user)
    assert (msg.tokens_in, msg.tokens_out) == (BILLED_IN, BILLED_OUT)


# --- provider normalisation (defect A) ---------------------------------------------

from types import SimpleNamespace  # noqa: E402

from app.core.providers.base import add_usage, set_usage  # noqa: E402
from app.core.providers.google import _read_usage as google_usage  # noqa: E402
from app.core.providers.openai_provider import _read_usage as openai_usage  # noqa: E402


def test_google_thinking_tokens_are_no_longer_dropped():
    """`candidates_token_count` excludes thinking, which is billed at the output rate.
    Reading only that field understated the expensive half of every turn."""
    usage: dict = {}
    google_usage(
        usage,
        SimpleNamespace(
            prompt_token_count=1000,
            candidates_token_count=200,
            thoughts_token_count=350,
            cached_content_token_count=64,
        ),
    )
    assert usage == {
        "tokens_in": 1000,
        "tokens_out": 200,
        "tokens_thinking": 350,
        "tokens_cached": 64,
    }


def test_openai_reasoning_is_split_out_of_completion_tokens():
    """OpenAI packages reasoning INSIDE completion_tokens while Gemini reports it beside
    candidates. Copying the raw field across would make the two silently incomparable."""
    usage: dict = {}
    openai_usage(
        usage,
        SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=550,  # includes the 350 reasoning tokens
            completion_tokens_details=SimpleNamespace(reasoning_tokens=350),
            prompt_tokens_details=SimpleNamespace(cached_tokens=64),
        ),
    )
    # tokens_out must mean VISIBLE output on both providers: 550 - 350.
    assert usage["tokens_out"] == 200
    assert usage["tokens_thinking"] == 350
    assert usage["tokens_in"] == 1000


def test_both_providers_agree_on_identical_work():
    """The same turn must cost the same on paper regardless of who served it."""
    g: dict = {}
    o: dict = {}
    google_usage(
        g,
        SimpleNamespace(
            prompt_token_count=800,
            candidates_token_count=120,
            thoughts_token_count=90,
            cached_content_token_count=None,
        ),
    )
    openai_usage(
        o,
        SimpleNamespace(
            prompt_tokens=800,
            completion_tokens=210,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=90),
            prompt_tokens_details=None,
        ),
    )
    assert g["tokens_in"] == o["tokens_in"] == 800
    assert g["tokens_out"] == o["tokens_out"] == 120
    assert g["tokens_thinking"] == o["tokens_thinking"] == 90


def test_a_provider_reporting_nothing_leaves_no_zeroes():
    """A missing count is unknown, not zero. Recording 0 would quietly understate a total
    that something else might later add to."""
    usage: dict = {}
    set_usage(usage, tokens_in=None, tokens_out=None)
    assert usage == {}


def test_set_assigns_within_a_request_while_add_sums_across_them():
    """The distinction that defect B came from, asserted directly."""
    request: dict = {}
    set_usage(request, tokens_in=100)
    set_usage(request, tokens_in=250)  # a later chunk repeats the cumulative total
    assert request["tokens_in"] == 250, "within a request, the last report wins"

    turn: dict = {}
    add_usage(turn, {"tokens_in": 250})
    add_usage(turn, {"tokens_in": 400})  # a second round is additional spend
    assert turn["tokens_in"] == 650, "across requests, totals add"
