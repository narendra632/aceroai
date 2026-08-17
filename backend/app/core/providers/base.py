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

# The keys every provider reports usage under, named after OpenTelemetry's GenAI
# semantic conventions so exporting later is a formatting change, not a redesign.
USAGE_KEYS = ("tokens_in", "tokens_out", "tokens_thinking", "tokens_cached")


def set_usage(usage: dict | None, **counts: int | None) -> None:
    """Record ONE request's totals into `usage`, ignoring keys the provider didn't report.

    Deliberately assignment, not addition. Providers report *cumulative* totals for a
    request — Google repeats a running total on successive stream chunks, OpenAI sends one
    final tally — so within a request the last report is the answer. Summing chunk by chunk
    would wildly overcount.

    Adding *across* requests is a different problem and belongs one level up, in `core.llm`:
    a turn that calls tools makes several requests, and the turn's cost is their sum. Those
    two levels were previously conflated into one dict that each round overwrote, so a
    three-round turn reported only its last round.

    `tokens_out` means VISIBLE output on every provider. Thinking tokens are billed at the
    output rate but are controllable separately (via the effort setting), so they are kept
    apart — which is what makes "is deep reasoning worth it?" an answerable question.
    """
    if usage is None:
        return
    for key, value in counts.items():
        if value is not None:
            usage[key] = value


def add_usage(total: dict | None, request: dict) -> None:
    """Fold ONE request's totals into a running total across several requests.

    The companion to `set_usage`, and the distinction between them is the whole of defect
    B: assignment *within* a request (providers repeat cumulative totals), addition
    *across* requests (a tool-using turn makes several). One dict served both jobs, so each
    round overwrote the last and a turn billed 2,500/130 recorded 1,500/90.
    """
    if total is None:
        return
    for key, value in request.items():
        if value is not None:
            total[key] = total.get(key, 0) + value


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
    """What every provider must implement.

    Every method takes `usage`. It used to be on `stream_with_tools` alone, which meant the
    two *non-streaming* calls had nowhere to put a number — so the extractor and the
    embedder, which together run on every single message, were billed and never counted.
    The contract could not express their cost, so nothing did.
    """

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
        self,
        messages: list[dict],
        model: str | None = None,
        effort: str | None = None,
        usage: dict | None = None,
    ) -> str:
        """Non-streaming completion, for structured background work."""
        ...

    async def embed(
        self, texts: list[str], model: str, dim: int, usage: dict | None = None
    ) -> list[list[float]]:
        """Embed texts (order preserved) at exactly `dim` dimensions."""
        ...
