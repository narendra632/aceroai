"""OpenAI provider — the native `openai` SDK against OpenAI proper.

This is where the streaming + tool-call accumulation that used to live in `core/llm.py`
now lives, unchanged in behavior: it was written against this SDK, so it is already
native here. Authenticated with `OPENAI_API_KEY` from the environment (never the UI).
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI

from app.config import settings
from app.core.providers.base import (
    EFFORT_HIGH,
    EFFORT_LOW,
    BillingError,
    ProviderError,
    RateLimitError,
    TransientError,
)

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192
_BILLING_HINTS = ("billing", "credit", "quota", "payment", "insufficient", "exceeded your")


def _classify(exc: Exception) -> ProviderError:
    text = str(exc).lower()
    if isinstance(exc, openai.RateLimitError):
        # OpenAI also returns 429 for an exhausted quota / unpaid balance.
        if any(h in text for h in _BILLING_HINTS):
            return BillingError(str(exc))
        return RateLimitError(str(exc))
    if isinstance(
        exc, openai.APITimeoutError | openai.APIConnectionError | openai.InternalServerError
    ):
        return TransientError(str(exc))
    if any(h in text for h in ("billing", "insufficient_quota", "payment")):
        return BillingError(str(exc))
    return ProviderError(str(exc))


def _accumulate(acc: dict[int, dict], fragment) -> None:
    """Merge a streamed tool-call fragment: id/name arrive once, arguments in pieces."""
    slot = acc.setdefault(fragment.index, {"id": None, "name": None, "arguments": ""})
    if fragment.id:
        slot["id"] = fragment.id
    if fragment.function:
        if fragment.function.name:
            slot["name"] = fragment.function.name
        if fragment.function.arguments:
            slot["arguments"] += fragment.function.arguments


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _get(self) -> AsyncOpenAI:
        # Lazy so importing never requires a key (CI has none).
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
            if settings.openai_base_url:
                kwargs["base_url"] = settings.openai_base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    @staticmethod
    def _effort(effort: str | None) -> dict:
        # Only send the knob when we mean it, so models without it are unaffected.
        if effort in (EFFORT_LOW, EFFORT_HIGH):
            return {"reasoning_effort": effort}
        return {}

    @staticmethod
    def _clean(messages: list[dict]) -> list[dict]:
        # Drop our provider-native echo field; OpenAI reconstructs from tool_calls.
        return [{k: v for k, v in m.items() if k != "_provider_raw"} for m in messages]

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        acc: dict[int, dict] = {}
        try:
            stream = await self._get().chat.completions.create(
                model=model or settings.model_chat,
                messages=self._clean(messages),
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
                **({"tools": tools} if tools else {}),
                **self._effort(effort),
            )
            async for chunk in stream:
                if usage is not None and getattr(chunk, "usage", None):
                    usage["tokens_in"] = chunk.usage.prompt_tokens
                    usage["tokens_out"] = chunk.usage.completion_tokens
                for choice in chunk.choices:
                    delta = choice.delta
                    if not delta:
                        continue
                    if delta.content:
                        yield "delta", delta.content
                    for frag in getattr(delta, "tool_calls", None) or []:
                        _accumulate(acc, frag)
        except Exception as exc:  # noqa: BLE001 - one place to classify provider errors
            raise _classify(exc) from exc

        calls = [
            {
                "id": acc[i]["id"] or f"call_{i}",
                "name": acc[i]["name"],
                "arguments": acc[i]["arguments"] or "{}",
                "raw": None,  # OpenAI needs no native echo
            }
            for i in sorted(acc)
            if acc[i]["name"]
        ]
        if calls:
            yield "tool_calls", calls

    async def complete(
        self, messages: list[dict], model: str | None = None, effort: str | None = None
    ) -> str:
        try:
            resp = await self._get().chat.completions.create(
                model=model or settings.model_chat,
                messages=self._clean(messages),
                max_tokens=MAX_OUTPUT_TOKENS,
                **self._effort(effort),
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc

    async def embed(self, texts: list[str], model: str, dim: int) -> list[list[float]]:
        try:
            resp = await self._get().embeddings.create(model=model, input=texts, dimensions=dim)
            return [d.embedding for d in resp.data]
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
