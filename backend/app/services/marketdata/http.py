"""What every price adapter shares: a client, retries, a cooldown, and one error type.

⚠ **Money is parsed as `Decimal`, never float.** `response.json()` turns `731.0` into a binary
float before any code here sees it, and `Decimal(731.1)` is 731.1000000000000227… — so every
adapter parses JSON through `json_decimal`, which hands the parser's text straight to
`Decimal`. The number never exists as a float at all.

⚠ **Nothing here may echo a request.** Angel One's login carries the MPIN and a TOTP in its
body and the API key in a header; CoinGecko and Twelve Data keys travel in headers. So
`ProviderError` carries a provider name and a short reason, never a URL, header or body, and
callers log only that.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from decimal import Decimal

import httpx

log = logging.getLogger(__name__)

#: Connect fast, read patiently. A host that will not accept a connection in 10 seconds is
#: down — Angel's API host refused connections outright for over an hour while this was
#: being built — whereas a bhavcopy download on a slow link is legitimately slower.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

ATTEMPTS = 3
#: Seconds before the second and third attempt. Module-level so tests can zero it.
BACKOFF = (1.0, 3.0)

#: After a provider fails, interactive refreshes leave it alone for this long. Without it,
#: every open of the page would wait out three timed-out attempts against a host that was
#: already known to be down a minute ago. Scheduled jobs ignore it and always try.
COOLDOWN_SECONDS = 600.0

_down_until: dict[str, float] = {}


class ProviderError(Exception):
    """A source could not supply what was asked. Safe to log: carries no request detail."""

    def __init__(self, provider: str, reason: str):
        super().__init__(f"{provider}: {reason}")
        self.provider = provider
        self.reason = reason


def client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True)


def json_decimal(response: httpx.Response):
    """Parse a JSON body with every non-integer number as an exact `Decimal`."""
    return json.loads(response.text, parse_float=Decimal)


def with_retries[T](provider: str, fn: Callable[[], T]) -> T:
    """Run `fn`, retrying transport failures and 5xx/429 with backoff.

    A 4xx other than 429 is not retried: a wrong key or a malformed request will be exactly as
    wrong a second later, and retrying it only spends the provider's allowance.
    """
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            return fn()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status != 429 and status < 500:
                raise ProviderError(provider, f"HTTP {status}") from None
            last = ProviderError(provider, f"HTTP {status}")
        except httpx.TransportError as exc:
            last = ProviderError(provider, type(exc).__name__)
        if attempt < ATTEMPTS - 1:
            time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    raise last or ProviderError(provider, "no attempt made")


def cooling(provider: str) -> bool:
    """Whether an interactive refresh should skip this provider for now."""
    return time.monotonic() < _down_until.get(provider, 0.0)


def mark_down(provider: str) -> None:
    _down_until[provider] = time.monotonic() + COOLDOWN_SECONDS


def mark_up(provider: str) -> None:
    _down_until.pop(provider, None)
