"""Thin async wrapper over the openai SDK, pointed at any OpenAI-compatible
endpoint via settings (Gemini by default). Provider swap = change .env only.

`stream_chat` / `complete` / `embed` are module-level so tests can monkeypatch
them with fakes — no network, no cost in CI.

Robustness: transient provider errors (timeout, connection, rate-limit) are
retried with a short backoff. For streaming, a retry only happens *before* the
first token is yielded, so retries never duplicate already-streamed output.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.config import settings

log = logging.getLogger(__name__)

# gemini-3.x flash is a thinking model: it spends tokens on reasoning before any
# visible text, so give the reply generous headroom (see verify_llm history).
DEFAULT_MAX_TOKENS = 8192

# Errors worth retrying: transient network/quota/overload (e.g. Gemini 503
# "high demand"), not bad requests.
_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    # Built lazily so importing this module never requires a key — CI, tests,
    # and a not-yet-configured checkout can still import the app. The SDK raises
    # if constructed with an empty api_key.
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    return _client


def _reasoning_kwargs(reasoning_effort: str | None) -> dict:
    # Include the knob only when set, so providers/models that don't support it
    # are unaffected (keeps the provider swap clean).
    return {"reasoning_effort": reasoning_effort} if reasoning_effort else {}


def _backoff(attempt: int) -> float:
    return 0.5 * (2**attempt)


async def _with_retry[T](run: Callable[[], Awaitable[T]]) -> T:
    """Run a non-streaming coroutine factory, retrying transient errors."""
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return await run()
        except _RETRYABLE as exc:
            if attempt == settings.llm_max_retries:
                raise
            log.warning("llm transient error (attempt %d): %s; retrying", attempt + 1, exc)
            await asyncio.sleep(_backoff(attempt))
    raise AssertionError("unreachable")  # pragma: no cover


async def stream_chat(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    usage: dict | None = None,
    reasoning_effort: str | None = None,
) -> AsyncIterator[str]:
    """Yield assistant text deltas. If `usage` dict is passed, it is populated
    with token counts when the provider reports them (Gemini may omit them)."""
    attempts = settings.llm_max_retries + 1
    for attempt in range(attempts):
        produced = False
        try:
            stream = await _get_client().chat.completions.create(
                model=model or settings.model_chat,
                messages=messages,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **_reasoning_kwargs(reasoning_effort),
            )
            async for chunk in stream:
                if usage is not None and getattr(chunk, "usage", None):
                    usage["tokens_in"] = chunk.usage.prompt_tokens
                    usage["tokens_out"] = chunk.usage.completion_tokens
                for choice in chunk.choices:
                    delta = choice.delta.content if choice.delta else None
                    if delta:
                        produced = True
                        yield delta
            return
        except _RETRYABLE as exc:
            # Never retry once tokens were streamed (would duplicate output).
            if produced or attempt == attempts - 1:
                raise
            log.warning("stream_chat transient error (attempt %d): %s; retrying", attempt + 1, exc)
            await asyncio.sleep(_backoff(attempt))


async def complete(
    messages: list[dict],
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    reasoning_effort: str | None = None,
) -> str:
    """Non-streaming completion — returns the full text. Used for structured
    background work (fact extraction) where streaming adds nothing."""

    async def _run() -> str:
        resp = await _get_client().chat.completions.create(
            model=model or settings.model_chat,
            messages=messages,
            max_tokens=max_tokens,
            **_reasoning_kwargs(reasoning_effort),
        )
        return resp.choices[0].message.content or ""

    return await _with_retry(_run)


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts (order preserved) via the provider's /embeddings endpoint."""

    async def _run() -> list[list[float]]:
        resp = await _get_client().embeddings.create(
            model=settings.embed_model,
            input=texts,
            dimensions=settings.embed_dim,
        )
        return [d.embedding for d in resp.data]

    return await _with_retry(_run)
