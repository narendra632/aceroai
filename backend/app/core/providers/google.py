"""Google provider — the **native** `google-genai` SDK against Agent Platform (Vertex).

Why native rather than the OpenAI-compatible endpoint: Gemini attaches a
`thought_signature` to each function call that must be returned on the following turn.
The OpenAI schema has nowhere to carry it, so it is dropped and **multi-turn tool calls
fail** — which is exactly what our assistant does. The native SDK preserves it, and we
echo the model's own turn back verbatim (see `_provider_raw`).

Auth is **Application Default Credentials** — no API key. In production the GCE VM's
attached service account supplies ADC through the metadata server (no secret on disk);
locally, `gcloud auth application-default login`. Requests bill to **Cloud Billing**,
so Google Cloud credits apply.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.core.providers.base import (
    EFFORT_HIGH,
    BillingError,
    ProviderError,
    RateLimitError,
    TransientError,
)

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 8192
# Verified against the live endpoint: 0 (fast) and 4096 (deeper) are both accepted.
THINKING_BUDGET_LOW = 0
THINKING_BUDGET_HIGH = 4096

_BILLING_HINTS = ("billing", "credit", "quota", "payment", "exhausted", "disabled")


def _classify(exc: Exception) -> ProviderError:
    """Map an SDK error to a cause we can be honest about in the UI.

    Google returns 429 for *both* a genuine rate limit and billing/quota exhaustion, so
    the message text is what actually distinguishes them.
    """
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    text = str(exc).lower()
    if code == 429 or "resource_exhausted" in text:
        if any(h in text for h in _BILLING_HINTS):
            return BillingError(str(exc))
        return RateLimitError(str(exc))
    if code in (500, 502, 503, 504) or "unavailable" in text or "timeout" in text:
        return TransientError(str(exc))
    if any(h in text for h in ("billing", "credit balance", "payment")):
        return BillingError(str(exc))
    return ProviderError(str(exc))


class GoogleProvider:
    name = "google"

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def _get(self) -> genai.Client:
        # Built lazily so importing never requires credentials (CI has none).
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
        return self._client

    # --- translation: our message list -> Gemini contents -------------------------

    @staticmethod
    def _tools(tools: list[dict] | None) -> list[types.Tool] | None:
        """OpenAI-style tool definitions -> Gemini function declarations."""
        if not tools:
            return None
        decls = []
        for t in tools:
            fn = t.get("function", t)
            decls.append(
                types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters_json_schema=fn.get("parameters") or {"type": "object"},
                )
            )
        return [types.Tool(function_declarations=decls)]

    @staticmethod
    def _split(messages: list[dict]) -> tuple[str, list[types.Content]]:
        """Return (system_instruction, contents). Gemini takes system prompts in their
        own field, and uses role "model" where OpenAI says "assistant"."""
        system_parts: list[str] = []
        contents: list[types.Content] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                if m.get("content"):
                    system_parts.append(str(m["content"]))
            elif role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=str(m.get("content") or ""))])
                )
            elif role == "assistant":
                # An assistant turn that requested tools carries the provider-native
                # content (with thought_signature) — echo it back verbatim.
                raw = m.get("_provider_raw")
                if raw is not None:
                    contents.append(raw)
                elif m.get("content"):
                    contents.append(
                        types.Content(role="model", parts=[types.Part(text=str(m["content"]))])
                    )
            elif role == "tool":
                try:
                    payload = json.loads(m.get("content") or "{}")
                except json.JSONDecodeError:
                    payload = {"result": m.get("content")}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=m.get("name") or "tool", response=payload
                            )
                        ],
                    )
                )
        return "\n\n".join(system_parts), contents

    def _config(
        self, messages: list[dict], tools: list[dict] | None, effort: str | None
    ) -> tuple[types.GenerateContentConfig, list[types.Content]]:
        system, contents = self._split(messages)
        budget = THINKING_BUDGET_HIGH if effort == EFFORT_HIGH else THINKING_BUDGET_LOW
        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=self._tools(tools),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_budget=budget),
            # We run our own bounded, user-scoped tool loop. Let the SDK execute tools
            # by itself and it would bypass every guardrail we built.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        return cfg, contents

    # --- the contract --------------------------------------------------------------

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        cfg, contents = self._config(messages, tools, effort)
        parts: list[types.Part] = []  # the model's own turn, kept for the echo
        calls: list[dict[str, Any]] = []
        try:
            stream = await self._get().aio.models.generate_content_stream(
                model=model or settings.model_chat, contents=contents, config=cfg
            )
            async for chunk in stream:
                if usage is not None and getattr(chunk, "usage_metadata", None):
                    um = chunk.usage_metadata
                    usage["tokens_in"] = getattr(um, "prompt_token_count", None)
                    usage["tokens_out"] = getattr(um, "candidates_token_count", None)
                for cand in chunk.candidates or []:
                    content = getattr(cand, "content", None)
                    for part in (content.parts or []) if content else []:
                        if part.function_call:
                            parts.append(part)  # carries thought_signature
                            fc = part.function_call
                            calls.append(
                                {
                                    "id": fc.id or f"call_{len(calls)}",
                                    "name": fc.name,
                                    "arguments": json.dumps(dict(fc.args or {})),
                                }
                            )
                        elif part.text:
                            parts.append(part)
                            yield "delta", part.text
        except Exception as exc:  # noqa: BLE001 - one place to classify provider errors
            raise _classify(exc) from exc

        if calls:
            # Attach the native turn so the next request can echo it back intact —
            # this is what makes multi-turn tool calling work on Gemini.
            native = types.Content(role="model", parts=parts)
            for c in calls:
                c["raw"] = native
            yield "tool_calls", calls

    async def complete(
        self, messages: list[dict], model: str | None = None, effort: str | None = None
    ) -> str:
        cfg, contents = self._config(messages, None, effort)
        try:
            resp = await self._get().aio.models.generate_content(
                model=model or settings.model_chat, contents=contents, config=cfg
            )
            return resp.text or ""
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc

    async def embed(self, texts: list[str], model: str, dim: int) -> list[list[float]]:
        try:
            resp = await self._get().aio.models.embed_content(
                model=model,
                contents=texts,
                config=types.EmbedContentConfig(output_dimensionality=dim),
            )
            return [list(e.values) for e in resp.embeddings]
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc
