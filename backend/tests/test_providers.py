"""Provider conformance + selection.

The conformance tests are the safety net for having two code paths: both providers must
translate their SDK's shapes into the *same* event contract, so a regression in either
shows up immediately rather than as "the assistant stopped doing things".

Fakes only — no network, no credentials, so CI stays free and green.
"""

import asyncio
import json
import types as pytypes

import pytest

from app.config import MODEL_CATALOG, settings
from app.core.providers.base import BillingError, ProviderError, RateLimitError, TransientError
from app.core.providers.google import GoogleProvider
from app.core.providers.google import _classify as classify_google
from app.core.providers.openai_provider import OpenAIProvider, _to_input
from app.core.providers.openai_provider import _classify as classify_openai
from app.services import user_settings

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Add a task.",
            "parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
        },
    }
]


# --- fake SDK payloads ---------------------------------------------------------------


def _google_chunk(parts):
    content = pytypes.SimpleNamespace(parts=parts)
    return pytypes.SimpleNamespace(
        candidates=[pytypes.SimpleNamespace(content=content)], usage_metadata=None
    )


def _google_part(text=None, call=None, signature=None):
    fc = None
    if call:
        fc = pytypes.SimpleNamespace(
            id=call.get("id"), name=call["name"], args=call.get("args", {})
        )
    return pytypes.SimpleNamespace(text=text, function_call=fc, thought_signature=signature)


def _openai_text(delta):
    """A visible-text delta event from the Responses stream."""
    return pytypes.SimpleNamespace(type="response.output_text.delta", delta=delta)


def _openai_item(**fields):
    """A completed output item — reasoning, function_call or message.

    Responses delivers a tool call whole, in one `output_item.done`, rather than as the
    argument fragments Chat Completions streamed.
    """
    return pytypes.SimpleNamespace(
        type="response.output_item.done", item=pytypes.SimpleNamespace(**fields)
    )


def _openai_done(status="completed", usage=None, **fields):
    return pytypes.SimpleNamespace(
        type=f"response.{status}",
        response=pytypes.SimpleNamespace(status=status, usage=usage, **fields),
    )


def _stub_google(monkeypatch, chunks):
    async def fake_stream(**kwargs):
        async def gen():
            for c in chunks:
                yield c

        return gen()

    provider = GoogleProvider()
    client = pytypes.SimpleNamespace(
        aio=pytypes.SimpleNamespace(
            models=pytypes.SimpleNamespace(generate_content_stream=fake_stream)
        )
    )
    monkeypatch.setattr(provider, "_get", lambda: client)
    return provider


def _stub_openai(monkeypatch, chunks, seen=None):
    async def fake_create(**kwargs):
        if seen is not None:
            seen.append(kwargs)

        async def gen():
            for c in chunks:
                yield c

        return gen()

    provider = OpenAIProvider()
    client = pytypes.SimpleNamespace(responses=pytypes.SimpleNamespace(create=fake_create))
    monkeypatch.setattr(provider, "_get", lambda: client)
    return provider


def _stub_openai_create(monkeypatch, create):
    """A provider whose `responses.create` is the given function."""
    provider = OpenAIProvider()
    monkeypatch.setattr(
        provider,
        "_get",
        lambda: pytypes.SimpleNamespace(responses=pytypes.SimpleNamespace(create=create)),
    )
    return provider


async def _drain(provider, **kw):
    text, calls = "", None
    async for kind, payload in provider.stream_with_tools(
        [{"role": "user", "content": "hi"}], **kw
    ):
        if kind == "delta":
            text += payload
        else:
            calls = payload
    return text, calls


# --- conformance: both providers, same contract --------------------------------------


def test_text_streaming_conformance(monkeypatch):
    g = _stub_google(
        monkeypatch,
        [_google_chunk([_google_part(text="He")]), _google_chunk([_google_part(text="llo")])],
    )
    o = _stub_openai(monkeypatch, [_openai_text("He"), _openai_text("llo")])
    for provider in (g, o):
        text, calls = asyncio.run(_drain(provider))
        assert text == "Hello"
        assert calls is None  # no tool_calls event on a plain text turn


def test_tool_call_conformance(monkeypatch):
    g = _stub_google(
        monkeypatch,
        [
            _google_chunk(
                [_google_part(call={"id": "c1", "name": "create_task", "args": {"title": "X"}})]
            )
        ],
    )
    o = _stub_openai(
        monkeypatch,
        [
            _openai_item(
                type="function_call",
                call_id="c1",
                name="create_task",
                arguments='{"title": "X"}',
            )
        ],
    )
    for provider in (g, o):
        _, calls = asyncio.run(_drain(provider, tools=TOOLS))
        assert calls and len(calls) == 1
        assert calls[0]["name"] == "create_task"
        assert json.loads(calls[0]["arguments"]) == {"title": "X"}
        assert calls[0]["id"]  # every call is addressable


def test_openai_sends_tools_and_effort_the_way_responses_wants_them(monkeypatch):
    """The bug this endpoint move fixes, pinned.

    On /v1/chat/completions the gpt-5.4 and 5.5 family returns 400 for function tools and
    a reasoning effort in the SAME request — and this app sends tools on every turn, so
    every message failed. Responses accepts both, but spells them differently: tools are
    flat rather than nested under "function", and the effort is a nested `reasoning`
    object rather than a top-level `reasoning_effort` string.
    """
    seen: list[dict] = []
    o = _stub_openai(monkeypatch, [_openai_text("hi")], seen=seen)
    asyncio.run(_drain(o, tools=TOOLS, effort="high"))

    sent = seen[0]
    assert sent["tools"] == [
        {
            "type": "function",
            "name": "create_task",
            "description": "Add a task.",
            "parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
        }
    ]
    assert sent["reasoning"] == {"effort": "high"}
    assert "reasoning_effort" not in sent  # the chat-completions spelling, which 400s
    assert sent["store"] is False, "a personal journal is never retained by the provider"


def test_openai_reasoning_gets_its_own_output_budget(monkeypatch):
    """Gemini's thinking budget is separate from max_output_tokens; OpenAI's is not.
    Sending the same 8192 to both would let a high-effort turn spend the entire allowance
    thinking and return an empty reply."""
    plain: list[dict] = []
    thinking: list[dict] = []
    asyncio.run(_drain(_stub_openai(monkeypatch, [_openai_text("x")], seen=plain)))
    asyncio.run(
        _drain(_stub_openai(monkeypatch, [_openai_text("x")], seen=thinking), effort="high")
    )

    assert thinking[0]["max_output_tokens"] > plain[0]["max_output_tokens"]


def test_google_returns_native_turn_for_thought_signature(monkeypatch):
    """The reason we went native: the model's own turn must come back so Gemini's
    thought_signature survives into the next request."""
    part = _google_part(call={"id": "c1", "name": "create_task"}, signature=b"sig-123")
    g = _stub_google(monkeypatch, [_google_chunk([part])])
    _, calls = asyncio.run(_drain(g, tools=TOOLS))
    native = calls[0]["raw"]
    assert native is not None, "Google provider must return the native turn"
    assert native.role == "model"
    assert any(getattr(p, "thought_signature", None) == b"sig-123" for p in native.parts)


def test_openai_returns_its_reasoning_for_the_next_round(monkeypatch):
    """The second reason for moving to Responses: reasoning survives a tool round.

    Chat Completions threw the model's reasoning away between rounds, so a turn that
    called three tools re-derived its thinking three times. Responses hands the reasoning
    item back (encrypted — we cannot read it, the model can), and it must reach the raw
    echo alongside the call so the next request can replay it.
    """
    o = _stub_openai(
        monkeypatch,
        [
            _openai_item(type="reasoning", id="rs_1", encrypted_content="opaque"),
            _openai_item(type="function_call", call_id="c1", name="create_task", arguments="{}"),
        ],
    )
    _, calls = asyncio.run(_drain(o, tools=TOOLS))

    echoed = calls[0]["raw"]
    assert [i["type"] for i in echoed] == ["reasoning", "function_call"]
    assert echoed[0]["encrypted_content"] == "opaque"


def test_openai_echoes_provider_raw_verbatim_on_the_next_request():
    """Those items go back untouched. Rebuilding them from our own chat-shaped copy would
    drop the reasoning, which is the only part we cannot reconstruct."""
    native = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
        {"type": "function_call", "call_id": "c1", "name": "create_task", "arguments": "{}"},
    ]
    items = _to_input(
        [
            {"role": "user", "content": "add a task"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "create_task", "arguments": "{}"},
                    }
                ],
                "_provider_raw": native,
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "create_task",
                "content": '{"ok": true}',
            },
        ]
    )

    assert items[1:3] == native  # verbatim, reasoning included
    assert items[3] == {
        "type": "function_call_output",
        "call_id": "c1",
        "output": '{"ok": true}',
    }


def test_openai_rebuilds_a_tool_turn_that_has_no_native_copy():
    """History reloaded from the database has no `_provider_raw`. The call must still be
    reconstructed, or the model sees a tool result answering nothing."""
    items = _to_input(
        [
            {
                "role": "assistant",
                "content": "one moment",
                "tool_calls": [
                    {
                        "id": "c9",
                        "type": "function",
                        "function": {"name": "list_tasks", "arguments": "{}"},
                    }
                ],
            }
        ]
    )
    assert items == [
        {"role": "assistant", "content": "one moment"},
        {"type": "function_call", "call_id": "c9", "name": "list_tasks", "arguments": "{}"},
    ]


def test_openai_empty_response_is_a_failure_not_an_empty_bubble(monkeypatch):
    """A run can end `incomplete` — usually reasoning ate the whole output allowance — and
    the SDK does not raise. Left alone the user gets a blank reply that Insights records as
    a success, which is the worst of both worlds."""
    o = _stub_openai(
        monkeypatch,
        [
            _openai_done(
                "incomplete", incomplete_details=pytypes.SimpleNamespace(reason="max_output_tokens")
            )
        ],
    )
    with pytest.raises(ProviderError, match="max_output_tokens"):
        asyncio.run(_drain(o, tools=TOOLS))


def test_openai_keeps_partial_output_when_a_run_is_cut_short(monkeypatch):
    """If words did arrive, truncation is worth a log line, not throwing them away."""
    o = _stub_openai(
        monkeypatch,
        [
            _openai_text("half a sen"),
            _openai_done(
                "incomplete", incomplete_details=pytypes.SimpleNamespace(reason="max_output_tokens")
            ),
        ],
    )
    text, _ = asyncio.run(_drain(o))
    assert text == "half a sen"


def _bad_request(param: str):
    """A real openai 400 complaining that `param` is unsupported."""
    import httpx
    import openai

    body = {
        "error": {
            "message": f"Unsupported parameter: '{param}' is not supported with this model.",
            "type": "invalid_request_error",
            "param": param,
            "code": "unsupported_parameter",
        }
    }
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1"))
    return openai.BadRequestError("unsupported", response=response, body=body)


def test_openai_renames_max_output_tokens_for_legacy_hosts(monkeypatch):
    """We send the modern name and adapt to whatever the API says, rather than keeping a
    model->capability table that rots every release."""
    seen: list[dict] = []

    async def create(**kwargs):
        seen.append(kwargs)
        if "max_output_tokens" in kwargs:
            raise _bad_request("max_output_tokens")  # legacy host
        return "ok"

    provider = _stub_openai_create(monkeypatch, create)

    assert asyncio.run(provider._create(model="m", input=[])) == "ok"
    assert "max_output_tokens" in seen[0]  # modern name tried first
    assert seen[1]["max_tokens"] == seen[0]["max_output_tokens"]  # renamed, not lost


def test_openai_drops_reasoning_when_a_model_rejects_the_nested_field(monkeypatch):
    """gpt-4.1 on Responses complains about `reasoning.effort` — a NESTED name, while the
    argument we actually sent is `reasoning`. Matching only exact names left the retry
    unable to act and the request failed outright."""
    seen: list[dict] = []

    async def create(**kwargs):
        seen.append(kwargs)
        if "reasoning" in kwargs:
            raise _bad_request("reasoning.effort")
        return "ok"

    provider = _stub_openai_create(monkeypatch, create)

    assert asyncio.run(provider._create(model="m", input=[], reasoning={"effort": "low"})) == "ok"
    assert "reasoning" not in seen[-1]


def test_openai_reads_param_from_message_when_body_is_empty(monkeypatch):
    """The SDK doesn't always populate the structured body — the message still names
    the parameter, and we must still adapt (this is what the live API actually sent)."""
    import httpx
    import openai

    from app.core.providers.openai_provider import _unsupported_param

    response = httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1"))
    exc = openai.BadRequestError(
        "Error code: 400 - Unsupported parameter: 'max_tokens' is not supported with this model.",
        response=response,
        body=None,
    )
    assert _unsupported_param(exc) == "max_tokens"


def test_openai_reraises_unrelated_bad_request(monkeypatch):
    """A 400 we can't adapt to must surface, not be retried into oblivion."""
    import openai

    async def create(**kwargs):
        raise _bad_request("some_param_we_never_send")

    provider = _stub_openai_create(monkeypatch, create)

    try:
        asyncio.run(provider._create(model="m", input=[]))
    except openai.BadRequestError:
        return
    raise AssertionError("expected the error to propagate")


def test_google_groups_parallel_tool_results_into_one_turn():
    """Regression: asking for two things at once makes Gemini emit two function calls.
    Gemini then requires the *same number* of response parts in a single following
    content — separate messages get rejected with INVALID_ARGUMENT."""
    _, contents = GoogleProvider._split(
        [
            {"role": "user", "content": "add two tasks"},
            {"role": "assistant", "content": None},
            {"role": "tool", "name": "create_task", "content": '{"ok": true}'},
            {"role": "tool", "name": "create_task", "content": '{"ok": true}'},
        ]
    )
    responses = [c for c in contents if any(p.function_response for p in c.parts)]
    assert len(responses) == 1, "parallel tool results must be one content, not many"
    assert len(responses[0].parts) == 2, "one response part per function call"
    assert all(p.function_response.name == "create_task" for p in responses[0].parts)


def test_google_tool_result_name_is_preserved():
    """Gemini pairs a response to its call by name, so the name must survive."""
    _, contents = GoogleProvider._split([{"role": "tool", "name": "list_tasks", "content": "{}"}])
    assert contents[0].parts[0].function_response.name == "list_tasks"


def test_google_translates_messages():
    system, contents = GoogleProvider._split(
        [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "name": "create_task", "content": '{"ok": true}'},
        ]
    )
    assert system == "be nice"  # system prompts go in their own field
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[-1].parts[0].function_response is not None


# --- error classification (the billing-vs-rate-limit fix) -----------------------------


def test_google_billing_vs_rate_limit():
    class Err(Exception):
        code = 429

    assert isinstance(
        classify_google(Err("Quota exceeded: billing account has no credit")), BillingError
    )
    assert isinstance(classify_google(Err("Too many requests per minute")), RateLimitError)


def test_google_transient_and_generic():
    class Err(Exception):
        code = 503

    assert isinstance(classify_google(Err("service unavailable")), TransientError)
    assert isinstance(classify_google(ValueError("weird")), ProviderError)


def test_openai_billing_vs_rate_limit():
    """OpenAI also returns 429 for an exhausted quota, so the message decides."""
    import httpx
    import openai

    def make(msg):
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1"))
        return openai.RateLimitError(msg, response=response, body=None)

    billing = make("You exceeded your current quota, please check your billing")
    limited = make("Rate limit reached for requests")
    assert isinstance(classify_openai(billing), BillingError)
    assert isinstance(classify_openai(limited), RateLimitError)


# --- per-user selection ---------------------------------------------------------------


def test_resolve_falls_back_to_defaults(user):
    provider, model = user_settings.resolve(user)
    assert provider == settings.llm_provider
    assert model == settings.model_chat


def test_resolve_uses_user_choice(db, user, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    user.llm_provider = "openai"
    user.model_chat = "gpt-5.1"
    user.model_deep = "gpt-5"
    db.commit()
    assert user_settings.resolve(user) == ("openai", "gpt-5.1")
    assert user_settings.resolve(user, deep=True) == ("openai", "gpt-5")


def test_resolve_ignores_provider_without_credentials(db, user, monkeypatch):
    """A provider whose key was removed must not wedge chat."""
    monkeypatch.setattr(settings, "openai_api_key", "")
    user.llm_provider = "openai"
    db.commit()
    provider, _ = user_settings.resolve(user)
    assert provider == settings.llm_provider


def test_embedding_is_pinned_and_independent_of_chat_provider(db, user, monkeypatch):
    """Switching chat provider must NOT change the embedding model — otherwise every
    stored profile_facts vector becomes meaningless."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    before = user_settings.get_settings(db, user)["embedding"]
    user.llm_provider = "openai"
    db.commit()
    after = user_settings.get_settings(db, user)["embedding"]
    assert before == after
    assert after["pinned"] is True
    assert after["model"] == settings.embed_model
    assert after["dimensions"] == settings.embed_dim


def test_catalog_lists_configured_providers():
    assert set(MODEL_CATALOG) == {"google", "openai"}
    assert all(MODEL_CATALOG.values())


# --- adapting to what a model actually accepts ---------------------------------------


def test_both_phrasings_of_a_rejected_parameter_are_understood():
    """OpenAI reports an unusable parameter two different ways depending on which way the
    mismatch runs, and only one is machine-readable. Matching just that one meant every
    NON-reasoning model (gpt-4.1, gpt-4o) failed outright the moment an effort was sent —
    which is every turn. Observed live before this was fixed.
    """
    from app.core.providers.openai_provider import _unsupported_param

    class Err(Exception):
        body = None

    newer_model_rejects_legacy = Err(
        "Error code: 400 - {'error': {'message': \"Unsupported parameter: "
        "'max_tokens' is not supported with this model.\"}}"
    )
    older_model_rejects_newer = Err(
        "Error code: 400 - {'error': {'message': 'Unrecognized request argument "
        "supplied: reasoning_effort', 'type': 'invalid_request_error'}}"
    )
    unrelated = Err("Error code: 400 - your prompt was too long")

    assert _unsupported_param(newer_model_rejects_legacy) == "max_tokens"
    assert _unsupported_param(older_model_rejects_newer) == "reasoning_effort"
    # Anything else must propagate rather than being silently retried without a param.
    assert _unsupported_param(unrelated) is None


def test_structured_body_is_preferred_over_the_message():
    from app.core.providers.openai_provider import _unsupported_param

    class Err(Exception):
        body = {"error": {"code": "unsupported_parameter", "param": "temperature"}}

    assert _unsupported_param(Err("some message mentioning nothing")) == "temperature"
