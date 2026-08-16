"""Model providers, each behind the shared contract in `base.py`.

Every provider uses its own **native** SDK, so no provider's capabilities are degraded
by a lowest-common-denominator compatibility layer. Add a provider by implementing
`base.Provider` and registering it here — nothing above `core/llm.py` changes.
"""

from functools import cache

from app.core.providers.base import Provider


@cache
def get_provider(name: str) -> Provider:
    """Return the (cached) provider instance. Imports are local so a missing optional
    SDK or credential never breaks importing the app."""
    if name == "google":
        from app.core.providers.google import GoogleProvider

        return GoogleProvider()
    if name == "openai":
        from app.core.providers.openai_provider import OpenAIProvider

        return OpenAIProvider()
    raise ValueError(f"unknown provider '{name}'")
