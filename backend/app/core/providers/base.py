"""The provider contract.

Everything above this line — the handler's tool loop, memory, composer, channels —
talks only to this interface, so adding or switching a provider never touches them.
Each implementation uses its provider's **native** SDK (not a compatibility shim), so
no provider's capabilities are degraded; the implementation's job is to translate that
SDK's shapes into the small, shared event contract below.

The stream contract, unchanged from what `handle_message` already consumes:
    ("delta", str)        - a chunk of visible assistant text
    ("tool_calls", list)  - the tools the model wants run, yielded once at turn end,
                            each {"id", "name", "arguments" (JSON str), "raw" (optional
                            provider-native payload to echo back on the next turn)}
"""

from collections.abc import AsyncIterator
from typing import Protocol

# Reasoning intent, mapped by each provider onto its own native control (a thinking
# budget, an effort string, ...) rather than pretending one knob fits every provider.
EFFORT_LOW = "low"
EFFORT_HIGH = "high"


class ProviderError(Exception):
    """Base for provider failures, carrying a cause the UI can be honest about."""


class TransientError(ProviderError):
    """Timeout / connection / overload — worth retrying."""


class RateLimitError(ProviderError):
    """A genuine per-minute/per-day rate limit — retry later."""


class BillingError(ProviderError):
    """Billing or quota problem (no credit, disabled billing, exhausted quota).

    Separate from RateLimitError on purpose: providers return the same HTTP status for
    both, and reporting a billing failure as a "rate limit" sends you chasing a limit
    that isn't there. That mistake cost real debugging time on this project.
    """


class Provider(Protocol):
    """What every provider must implement."""

    name: str

    def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> AsyncIterator[tuple[str, object]]:
        """Stream one model turn as ("delta", text) / ("tool_calls", calls) events."""
        ...

    async def complete(
        self, messages: list[dict], model: str | None = None, effort: str | None = None
    ) -> str:
        """Non-streaming completion, for structured background work."""
        ...

    async def embed(self, texts: list[str], model: str, dim: int) -> list[list[float]]:
        """Embed texts (order preserved) at exactly `dim` dimensions."""
        ...
