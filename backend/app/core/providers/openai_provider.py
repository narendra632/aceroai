"""OpenAI provider — the native `openai` SDK against OpenAI proper.

This is where the streaming + tool-call accumulation that used to live in `core/llm.py`
now lives, unchanged in behavior: it was written against this SDK, so it is already
native here. Authenticated with `OPENAI_API_KEY` from the environment (never the UI).
"""

import logging
import re
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
    set_usage,
)


def _read_usage(usage: dict | None, u) -> None:
    """Translate OpenAI's usage into the shared shape.

    The packaging differs from Gemini's in a way that matters: `completion_tokens` INCLUDES
    reasoning tokens (`completion_tokens_details.reasoning_tokens` is a subfield of it),
    whereas Gemini reports thinking separately. Copying the raw field across would make the
    two providers silently incomparable — the same work would look more expensive on one of
    them purely because of how the numbers are grouped. Subtracting keeps `tokens_out`
    meaning VISIBLE output everywhere.
    """
    if u is None:
        return
    details = getattr(u, "completion_tokens_details", None)
    thinking = getattr(details, "reasoning_tokens", None) or 0
    completion = getattr(u, "completion_tokens", None)
    prompt_details = getattr(u, "prompt_tokens_details", None)
    set_usage(
        usage,
        tokens_in=getattr(u, "prompt_tokens", None),
        tokens_out=None if completion is None else max(0, completion - thinking),
        tokens_thinking=thinking or None,
        tokens_cached=getattr(prompt_details, "cached_tokens", None),
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


# OpenAI rejects an unusable parameter with two DIFFERENT messages depending on which
# way the mismatch runs, and only the first is machine-readable:
#
#   newer model, legacy param : code=unsupported_parameter, param="max_tokens"
#                               "Unsupported parameter: 'max_tokens' is not supported..."
#   older model, newer param  : code=None, param=None
#                               "Unrecognized request argument supplied: reasoning_effort"
#
# Matching only the first meant every non-reasoning model (gpt-4.1, gpt-4o) failed
# outright the moment an effort was sent, which is every turn. Observed live.
_REJECTED_PARAM = re.compile(
    r"Unsupported parameter: '([^']+)'|Unrecognized request argument supplied: (\S+)"
)


def _unsupported_param(exc: Exception) -> str | None:
    """The parameter name a 400 is complaining about, whichever way it is phrased.

    The structured `body` is preferred, but the SDK populates it for only one of the two
    shapes, so the message is parsed as a fallback.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if err.get("code") == "unsupported_parameter" and err.get("param"):
            return str(err["param"])
    match = _REJECTED_PARAM.search(str(exc))
    if not match:
        return None
    # Whichever alternative matched; the other group is None.
    return (match.group(1) or match.group(2)).strip("'\".,")


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

    async def _create(self, **kwargs):
        """Create a completion, adapting to what the chosen model actually accepts.

        OpenAI's model families disagree about parameters: newer ones (gpt-5.x) require
        `max_completion_tokens` and reject `max_tokens`, while older ones reject
        `reasoning_effort`. Rather than hard-code a model->capability table that rots
        every release, we send the modern form and let the API tell us: on an
        `unsupported_parameter` 400 we rename or drop that parameter and retry. This
        happens before any output is streamed, so nothing is ever duplicated.
        """
        kwargs.setdefault("max_completion_tokens", MAX_OUTPUT_TOKENS)
        for _ in range(3):  # at most a few parameters can be objected to
            try:
                return await self._get().chat.completions.create(**kwargs)
            except openai.BadRequestError as exc:
                param = _unsupported_param(exc)
                if param is None or param not in kwargs:
                    raise
                value = kwargs.pop(param)
                # A host that predates the rename still wants the legacy name.
                if param == "max_completion_tokens":
                    kwargs["max_tokens"] = value
                log.info("openai: model rejected '%s'; retrying without it", param)
        return await self._get().chat.completions.create(**kwargs)

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
            stream = await self._create(
                model=model or settings.model_chat,
                messages=self._clean(messages),
                stream=True,
                stream_options={"include_usage": True},
                **({"tools": tools} if tools else {}),
                **self._effort(effort),
            )
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    _read_usage(usage, chunk.usage)
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
        self,
        messages: list[dict],
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> str:
        try:
            resp = await self._create(
                model=model or settings.model_chat,
                messages=self._clean(messages),
                **self._effort(effort),
            )
            _read_usage(usage, getattr(resp, "usage", None))
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc

    async def embed(
        self, texts: list[str], model: str, dim: int, usage: dict | None = None
    ) -> list[list[float]]:
        try:
            resp = await self._get().embeddings.create(model=model, input=texts, dimensions=dim)
            u = getattr(resp, "usage", None)
            # Embeddings are input-only; there is no output to bill.
            set_usage(usage, tokens_in=getattr(u, "prompt_tokens", None))
            return [d.embedding for d in resp.data]
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
