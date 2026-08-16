"""Per-request timing and context accounting.

Answers, with measured numbers rather than guesses: what exactly went into this
request, how big each part was, and where the wall-clock time went. One line per turn
at INFO, so you can watch it live (`docker compose logs -f api`, or the uvicorn console)
and compare it against a stopwatch.

Token counts: the provider's own usage numbers are authoritative and are reported when
it returns them. `approx_tokens` is only a *local estimate* for the per-block breakdown
(a provider never tells you how many tokens the persona alone cost), and is labelled as
approximate wherever it is shown.
"""

import logging
import time
from contextlib import contextmanager

log = logging.getLogger("aceroai.timing")

# Rough bytes-per-token for English prose. Real tokenizers differ per model; this is a
# sizing aid for the context breakdown, never billing.
_CHARS_PER_TOKEN = 4


def approx_tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN)) if text else 0


class Timeline:
    """Records how long each stage of one turn took, in order."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.stages: list[tuple[str, float]] = []
        self.notes: dict[str, object] = {}

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append((name, (time.perf_counter() - start) * 1000))

    def mark(self, name: str) -> None:
        """Record a moment measured from the start of the turn (e.g. first token)."""
        self.stages.append((name, (time.perf_counter() - self.t0) * 1000))

    def note(self, **kwargs: object) -> None:
        self.notes.update(kwargs)

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def emit(self) -> None:
        parts = " ".join(f"{name}={ms:.0f}ms" for name, ms in self.stages)
        extra = " ".join(f"{k}={v}" for k, v in self.notes.items())
        log.info("turn total=%.0fms %s %s", self.total_ms, parts, extra)


def describe_context(messages: list[dict]) -> dict:
    """Size each part of what we're about to send, so the cost is visible per block."""
    blocks: list[dict] = []
    for m in messages:
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        blocks.append(
            {"role": m.get("role"), "chars": len(content), "approx_tokens": approx_tokens(content)}
        )
    return {
        "messages": len(messages),
        "chars": sum(b["chars"] for b in blocks),
        "approx_tokens": sum(b["approx_tokens"] for b in blocks),
        "blocks": blocks,
    }
