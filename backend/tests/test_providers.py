"""Provider conformance + selection.

The conformance tests are the safety net for having two code paths: both providers must
translate their SDK's shapes into the *same* event contract, so a regression in either
shows up immediately rather than as "the assistant stopped doing things".

Fakes only — no network, no credentials, so CI stays free and green.
"""

import asyncio
import json
import types as pytypes

from app.config import MODEL_CATALOG, settings
from app.core.providers.base import BillingError, ProviderError, RateLimitError, TransientError
from app.core.providers.google import GoogleProvider
from app.core.providers.google import _classify as classify_google
from app.core.providers.openai_provider import OpenAIProvider
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


def _openai_chunk(content=None, tool_frags=None):
    delta = pytypes.SimpleNamespace(content=content, tool_calls=tool_frags)
    return pytypes.SimpleNamespace(choices=[pytypes.SimpleNamespace(delta=delta)], usage=None)


def _openai_frag(index, id_=None, name=None, args=None):
    fn = pytypes.SimpleNamespace(name=name, arguments=args)
    return pytypes.SimpleNamespace(index=index, id=id_, function=fn)


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


def _stub_openai(monkeypatch, chunks):
    async def fake_create(**kwargs):
        async def gen():
            for c in chunks:
                yield c

        return gen()

    provider = OpenAIProvider()
    client = pytypes.SimpleNamespace(
        chat=pytypes.SimpleNamespace(completions=pytypes.SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(provider, "_get", lambda: client)
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
    o = _stub_openai(monkeypatch, [_openai_chunk("He"), _openai_chunk("llo")])
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
        [_openai_chunk(tool_frags=[_openai_frag(0, "c1", "create_task", '{"title": "X"}')])],
    )
    for provider in (g, o):
        _, calls = asyncio.run(_drain(provider, tools=TOOLS))
        assert calls and len(calls) == 1
        assert calls[0]["name"] == "create_task"
        assert json.loads(calls[0]["arguments"]) == {"title": "X"}
        assert calls[0]["id"]  # every call is addressable


def test_streamed_tool_arguments_are_reassembled(monkeypatch):
    """OpenAI splits arguments across chunks; they must arrive as one JSON string."""
    o = _stub_openai(
        monkeypatch,
        [
            _openai_chunk(tool_frags=[_openai_frag(0, "c1", "create_task", '{"tit')]),
            _openai_chunk(tool_frags=[_openai_frag(0, None, None, 'le": "X"}')]),
        ],
    )
    _, calls = asyncio.run(_drain(o, tools=TOOLS))
    assert json.loads(calls[0]["arguments"]) == {"title": "X"}


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


def test_openai_needs_no_native_echo(monkeypatch):
    o = _stub_openai(
        monkeypatch, [_openai_chunk(tool_frags=[_openai_frag(0, "c1", "create_task", "{}")])]
    )
    _, calls = asyncio.run(_drain(o, tools=TOOLS))
    assert calls[0]["raw"] is None


def test_openai_strips_provider_raw_before_sending():
    """`_provider_raw` is ours, not OpenAI's — it must never be sent upstream."""
    cleaned = OpenAIProvider._clean(
        [{"role": "assistant", "content": "x", "_provider_raw": object()}]
    )
    assert cleaned == [{"role": "assistant", "content": "x"}]


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
    before = user_settings.get_settings(user)["embedding"]
    user.llm_provider = "openai"
    db.commit()
    after = user_settings.get_settings(user)["embedding"]
    assert before == after
    assert after["pinned"] is True
    assert after["model"] == settings.embed_model
    assert after["dimensions"] == settings.embed_dim


def test_catalog_lists_configured_providers():
    assert set(MODEL_CATALOG) == {"google", "openai"}
    assert all(MODEL_CATALOG.values())
