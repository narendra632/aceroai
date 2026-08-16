"""Facade over the model providers.

Callers (the handler's tool loop, memory) use these four functions and never know which
provider served a request. Each provider lives in `app/core/providers/` and speaks its
own **native** SDK, so nothing is degraded by a compatibility shim.

Robustness lives here, once, for every provider: transient failures (timeout,
connection, overload) are retried with a short backoff. For streaming, a retry only
happens *before* the first token is yielded, so retries never duplicate output.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from app.config import settings
from app.core.providers import get_provider
from app.core.providers.base import TransientError

log = logging.getLogger(__name__)


def _resolve(provider: str | None) -> str:
    return provider or settings.llm_provider


def _backoff(attempt: int) -> float:
    return 0.5 * (2**attempt)


async def _with_retry[T](run: Callable[[], Awaitable[T]]) -> T:
    """Run a non-streaming coroutine factory, retrying transient provider errors."""
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return await run()
        except TransientError as exc:
            if attempt == settings.llm_max_retries:
                raise
            log.warning("llm transient error (attempt %d): %s; retrying", attempt + 1, exc)
            await asyncio.sleep(_backoff(attempt))
    raise AssertionError("unreachable")  # pragma: no cover


async def stream_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    usage: dict | None = None,
    effort: str | None = None,
    provider: str | None = None,
) -> AsyncIterator[tuple[str, object]]:
    """Stream one model turn as `(kind, payload)` events:

    - `("delta", str)` — a chunk of visible assistant text
    - `("tool_calls", list)` — tools to run, yielded once at the end of the turn

    A plain chat turn yields only `"delta"` events. Passing `tools=None` forces a text
    answer (used to close out a capped tool loop).
    """
    impl = get_provider(_resolve(provider))
    attempts = settings.llm_max_retries + 1
    for attempt in range(attempts):
        produced = False
        try:
            async for kind, payload in impl.stream_with_tools(
                messages, tools=tools, model=model, effort=effort, usage=usage
            ):
                produced = True
                yield kind, payload
            return
        except TransientError as exc:
            # Never retry once output was produced (it would duplicate).
            if produced or attempt == attempts - 1:
                raise
            log.warning("stream transient error (attempt %d): %s; retrying", attempt + 1, exc)
            await asyncio.sleep(_backoff(attempt))


async def complete(
    messages: list[dict],
    model: str | None = None,
    effort: str | None = None,
    provider: str | None = None,
) -> str:
    """Non-streaming completion — used for structured background work (fact extraction)."""
    impl = get_provider(_resolve(provider))
    return await _with_retry(lambda: impl.complete(messages, model=model, effort=effort))


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts (order preserved).

    Deliberately ignores the user's chat-provider choice: every stored `profile_facts`
    vector came from `settings.embed_model`, and vectors from a different model are not
    comparable (same length, different meaning), so recall would silently return
    nonsense. Changing the embedding model is a deliberate re-embed migration.
    """
    impl = get_provider(settings.embed_provider)
    return await _with_retry(
        lambda: impl.embed(texts, model=settings.embed_model, dim=settings.embed_dim)
    )
