"""Thin async wrapper over the openai SDK, pointed at any OpenAI-compatible
endpoint via settings (Gemini by default). Provider swap = change .env only.

`stream_chat` is a module-level async generator so tests can monkeypatch
`app.core.llm.stream_chat` with a fake — no network, no cost in CI.
"""

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings

# gemini-3.x flash is a thinking model: it spends tokens on reasoning before any
# visible text, so give the reply generous headroom (see verify_llm history).
DEFAULT_MAX_TOKENS = 8192

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    # Built lazily so importing this module never requires a key — CI, tests,
    # and a not-yet-configured checkout can still import the app. The SDK raises
    # if constructed with an empty api_key.
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


async def stream_chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    usage: dict | None = None,
) -> AsyncIterator[str]:
    """Yield assistant text deltas. If `usage` dict is passed, it is populated
    with token counts when the provider reports them (Gemini may omit them)."""
    stream = await _get_client().chat.completions.create(
        model=model or settings.model_chat,
        messages=messages,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if usage is not None and getattr(chunk, "usage", None):
            usage["tokens_in"] = chunk.usage.prompt_tokens
            usage["tokens_out"] = chunk.usage.completion_tokens
        for choice in chunk.choices:
            delta = choice.delta.content if choice.delta else None
            if delta:
                yield delta
