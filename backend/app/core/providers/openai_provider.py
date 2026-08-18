"""OpenAI provider — the native `openai` SDK, on the **Responses** API.

Why Responses and not Chat Completions
--------------------------------------
OpenAI split capability by endpoint. On `/v1/chat/completions` the gpt-5.4 and gpt-5.5
family refuses function tools and a reasoning effort in the same request:

    400 "Function tools with reasoning_effort are not supported for gpt-5.4-mini in
         /v1/chat/completions. To use function tools, use /v1/responses or set
         reasoning_effort to 'none'."

This app sends tools on **every** chat turn, so on Chat Completions every model newer
than gpt-5.2 failed on every message. Observed live, then reproduced against the API
before this module was rewritten.

The escape hatch that error offers — `reasoning_effort='none'` — would silence the
think-harder feature rather than fix it, and a control that quietly does nothing is worse
than one that is never offered. So we moved endpoint, which is what OpenAI is telling us
to do anyway.

Responses is also the better home for what this app does, independent of the bug: it
returns the model's **reasoning items**, which we echo on the next tool round (see
`_provider_raw`). A three-round tool turn therefore keeps one train of thought instead of
re-deriving it each round. Chat Completions discards reasoning between rounds.

Two request-level choices, both deliberate:
  * `store=False` — OpenAI never retains this conversation. It is a personal journal.
  * `include=["reasoning.encrypted_content"]` — the consequence of not storing is that the
    reasoning must travel with us, so we ask for it back encrypted and hand it straight
    back. We cannot read it; the model can.

Authenticated with `OPENAI_API_KEY` from the environment (never from the UI).
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

log = logging.getLogger(__name__)

# Visible output, matching the Google provider so a reply is not shorter on one of them.
MAX_OUTPUT_TOKENS = 8192

# Extra budget for hidden reasoning, added only when an effort is actually requested.
#
# The two providers count this differently and the difference bites. Gemini's thinking
# budget is a SEPARATE allowance from `max_output_tokens`; OpenAI's `max_output_tokens`
# covers reasoning AND visible output in one number. Passing 8192 to both would let a
# high-effort turn here spend the whole allowance thinking and return an empty reply.
REASONING_HEADROOM = 24576

_BILLING_HINTS = ("billing", "credit", "quota", "payment", "insufficient", "exceeded your")


def _first(obj, *names):
    """The first of `names` this object actually carries, so one reader serves both APIs."""
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _read_usage(usage: dict | None, u) -> None:
    """Translate OpenAI's usage into the shared shape.

    Reads either spelling — Responses reports `input_tokens`/`output_tokens`, Chat
    Completions reported `prompt_tokens`/`completion_tokens` — because the semantics are
    identical and only the naming differs.

    The packaging differs from Gemini's in a way that matters: the output count INCLUDES
    reasoning tokens (reasoning is a subfield of it), whereas Gemini reports thinking
    separately. Copying the raw field across would make the two providers silently
    incomparable — the same work would look more expensive on one of them purely because
    of how the numbers are grouped. Subtracting keeps `tokens_out` meaning VISIBLE output
    everywhere.
    """
    if u is None:
        return
    tokens_in = _first(u, "input_tokens", "prompt_tokens")
    total_out = _first(u, "output_tokens", "completion_tokens")
    out_details = _first(u, "output_tokens_details", "completion_tokens_details")
    in_details = _first(u, "input_tokens_details", "prompt_tokens_details")
    thinking = getattr(out_details, "reasoning_tokens", None) or 0
    set_usage(
        usage,
        tokens_in=tokens_in,
        tokens_out=None if total_out is None else max(0, total_out - thinking),
        tokens_thinking=thinking or None,
        tokens_cached=getattr(in_details, "cached_tokens", None),
    )


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


# OpenAI rejects an unusable parameter with several DIFFERENT messages, and only the first
# is machine-readable:
#
#   newer model, legacy param : code=unsupported_parameter, param="max_tokens"
#                               "Unsupported parameter: 'max_tokens' is not supported..."
#   older model, newer param  : code=None, param=None
#                               "Unrecognized request argument supplied: reasoning_effort"
#   nested field              : "Unsupported parameter: 'reasoning.effort' is not
#                               supported with this model."   (gpt-4.1 on Responses)
#
# Matching only the first meant every non-reasoning model failed outright the moment an
# effort was sent, which is every turn. Observed live.
_REJECTED_PARAM = re.compile(
    r"Unsupported parameter: '([^']+)'|Unrecognized request argument supplied: (\S+)"
)


def _unsupported_param(exc: Exception) -> str | None:
    """The parameter name a 400 is complaining about, whichever way it is phrased.

    The structured `body` is preferred, but the SDK populates it for only some of the
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


def _root_param(param: str | None, kwargs: dict) -> str | None:
    """The top-level argument to drop for a complaint that may name a nested field.

    Responses reports `reasoning.effort`; the argument we actually sent is `reasoning`.
    Returns None when the complaint names something we did not send, which means the 400
    is a real error and must surface rather than be retried away.
    """
    if param is None:
        return None
    if param in kwargs:
        return param
    root = param.split(".", 1)[0]
    return root if root in kwargs else None


def _to_tools(tools: list[dict] | None) -> list[dict]:
    """Chat-shaped tool schemas -> the flat shape Responses wants.

    Chat nests the definition under a "function" key; Responses puts the same fields at the
    top level. The rest of the app keeps the chat shape because Gemini's adapter reads it
    too, so the translation lives here rather than rippling outward.
    """
    out = []
    for tool in tools or []:
        fn = tool.get("function")
        out.append({"type": "function", **fn} if isinstance(fn, dict) else tool)
    return out


def _dump(item) -> dict:
    """A response item as a plain dict, ready to be echoed back verbatim."""
    model_dump = getattr(item, "model_dump", None)
    return model_dump(exclude_none=True) if model_dump else dict(vars(item))


def _to_input(messages: list[dict]) -> list[dict]:
    """Our chat-shaped messages -> Responses input items.

    The interesting case is an assistant turn that requested tools. If it carries
    `_provider_raw` — the model's own output items from the previous round, reasoning
    included — those go back **verbatim**, which is the whole reason for moving here. The
    reconstruction below it is the fallback for a turn rebuilt from the database rather
    than produced in this process.
    """
    items: list[dict] = []
    for message in messages:
        role = message.get("role")

        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id") or "",
                    "output": str(message.get("content") or ""),
                }
            )
            continue

        if role == "assistant":
            raw = message.get("_provider_raw")
            if raw:
                items.extend(raw)
                continue
            if message.get("tool_calls"):
                if message.get("content"):
                    items.append({"role": "assistant", "content": str(message["content"])})
                for call in message["tool_calls"]:
                    fn = call.get("function") or {}
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call.get("id") or "",
                            "name": fn.get("name") or "",
                            "arguments": fn.get("arguments") or "{}",
                        }
                    )
                continue

        if message.get("content"):
            items.append({"role": role or "user", "content": str(message["content"])})
    return items


def _check_terminal(response, produced_anything: bool) -> None:
    """Fail loudly when a run ends without producing anything.

    A response can finish `incomplete` — most often because reasoning consumed the whole
    output allowance — and the SDK does not raise for it. Left alone that surfaces as an
    empty assistant bubble recorded as a SUCCESS, the worst of both worlds: the user sees
    nothing and the Insights page reports everything is fine. If some output did arrive we
    keep it and only note the truncation.
    """
    status = getattr(response, "status", None)
    if status not in ("incomplete", "failed"):
        return
    details = getattr(response, "incomplete_details", None) or getattr(response, "error", None)
    reason = getattr(details, "reason", None) or getattr(details, "message", None) or status
    if produced_anything:
        log.warning("openai: response ended %s (%s); keeping partial output", status, reason)
        return
    raise ProviderError(f"model returned nothing: {status} ({reason})")


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
            return {"reasoning": {"effort": effort}}
        return {}

    @staticmethod
    def _budget(effort: str | None) -> int:
        return MAX_OUTPUT_TOKENS + (
            REASONING_HEADROOM if effort in (EFFORT_LOW, EFFORT_HIGH) else 0
        )

    async def _create(self, **kwargs):
        """Create a response, adapting to what the chosen model actually accepts.

        OpenAI's model families disagree about parameters, and the disagreements change
        every release. Rather than hard-code a model->capability table that rots, we send
        the modern form and let the API tell us: on a 400 naming a parameter we sent, we
        drop or rename it and retry. This happens before any output is streamed, so
        nothing is ever duplicated.
        """
        kwargs.setdefault("max_output_tokens", MAX_OUTPUT_TOKENS)
        # Never retained by OpenAI; see the module docstring.
        kwargs.setdefault("store", False)
        for _ in range(3):  # at most a few parameters can be objected to
            try:
                return await self._get().responses.create(**kwargs)
            except openai.BadRequestError as exc:
                param = _root_param(_unsupported_param(exc), kwargs)
                if param is None:
                    raise
                value = kwargs.pop(param)
                # A host that predates the rename still wants the legacy name.
                if param == "max_output_tokens":
                    kwargs["max_tokens"] = value
                log.info("openai: model rejected '%s'; retrying without it", param)
        return await self._get().responses.create(**kwargs)

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        calls: list[dict] = []
        items: list[dict] = []
        produced = False
        try:
            stream = await self._create(
                model=model or settings.model_chat,
                input=_to_input(messages),
                stream=True,
                include=["reasoning.encrypted_content"],
                max_output_tokens=self._budget(effort),
                **({"tools": _to_tools(tools)} if tools else {}),
                **self._effort(effort),
            )
            async for event in stream:
                kind = getattr(event, "type", "")

                if kind == "response.output_text.delta":
                    produced = True
                    yield "delta", event.delta

                elif kind == "response.output_item.done":
                    # Every item the model produced, in order: reasoning, tool calls and
                    # the visible message. Kept whole so the next round can echo it.
                    item = _dump(event.item)
                    items.append(item)
                    if item.get("type") == "function_call":
                        produced = True
                        calls.append(
                            {
                                "id": item.get("call_id") or f"call_{len(calls)}",
                                "name": item.get("name"),
                                "arguments": item.get("arguments") or "{}",
                            }
                        )

                elif kind in ("response.completed", "response.incomplete", "response.failed"):
                    _read_usage(usage, getattr(event.response, "usage", None))
                    _check_terminal(event.response, produced)

                elif kind == "error":
                    raise ProviderError(getattr(event, "message", None) or "stream error")

        except Exception as exc:  # noqa: BLE001 - one place to classify provider errors
            raise _classify(exc) from exc

        named = [c for c in calls if c["name"]]
        if named:
            for call in named:
                # The model's own items for this turn, echoed verbatim next round so the
                # reasoning behind a call survives into the round that uses its result.
                call["raw"] = items
            yield "tool_calls", named

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
                input=_to_input(messages),
                max_output_tokens=self._budget(effort),
                **self._effort(effort),
            )
            _read_usage(usage, getattr(resp, "usage", None))
            text = getattr(resp, "output_text", None) or ""
            _check_terminal(resp, bool(text))
            return text
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
