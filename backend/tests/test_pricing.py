"""Cost estimation: frozen at write time, honest about what it doesn't know."""

import datetime as dt
from decimal import Decimal

from app.core import pricing


def test_cost_counts_thinking_at_the_output_rate():
    """Thinking tokens are generated text the user never sees — billed as output. Counting
    them as input, or not at all, understates the expensive half of every turn."""
    visible_only = pricing.estimate_cost(
        "google", "gemini-3.5-flash", tokens_in=1000, tokens_out=200
    )
    with_thinking = pricing.estimate_cost(
        "google", "gemini-3.5-flash", tokens_in=1000, tokens_out=200, tokens_thinking=300
    )

    rate = pricing.rate_for("google", "gemini-3.5-flash")
    assert with_thinking - visible_only == (Decimal(300) * rate.output / Decimal(1_000_000))


def test_cached_input_is_discounted_not_double_counted():
    """tokens_cached is a SUBSET of tokens_in that both providers bill cheaper. Adding it
    on top would charge for those tokens twice."""
    rate = pricing.rate_for("google", "gemini-3.5-flash")
    assert rate.cached_input < rate.input_

    plain = pricing.estimate_cost("google", "gemini-3.5-flash", tokens_in=1000)
    part_cached = pricing.estimate_cost(
        "google", "gemini-3.5-flash", tokens_in=1000, tokens_cached=400
    )
    assert part_cached < plain

    expected = (Decimal(600) * rate.input_ + Decimal(400) * rate.cached_input) / Decimal(1_000_000)
    assert part_cached == expected.quantize(Decimal("0.000001"))


def test_unknown_model_costs_nothing_known_not_zero():
    """Zero is a lie that silently understates a total; a gap is visible and gets fixed."""
    assert pricing.estimate_cost("google", "some-model-shipped-tomorrow", tokens_in=5000) is None
    assert pricing.estimate_cost(None, None, tokens_in=5000) is None


def test_a_later_price_does_not_change_an_earlier_turn(monkeypatch):
    """The whole reason cost is frozen at write time: opening the dashboard after a price
    change must not rewrite last month's spend."""
    key = "google/test-model"
    monkeypatch.setitem(
        pricing.PRICING,
        key,
        [
            pricing._r("2026-01-01", "1.00", "2.00"),
            pricing._r("2026-06-01", "5.00", "10.00"),  # a later, much higher rate
        ],
    )

    march = dt.datetime(2026, 3, 15, tzinfo=dt.UTC)
    july = dt.datetime(2026, 7, 15, tzinfo=dt.UTC)

    old = pricing.estimate_cost("google", "test-model", tokens_in=1_000_000, when=march)
    new = pricing.estimate_cost("google", "test-model", tokens_in=1_000_000, when=july)

    assert old == Decimal("1.000000")
    assert new == Decimal("5.000000")


def test_pricing_version_is_recorded_so_a_number_can_be_explained():
    assert pricing.PRICING_VERSION


def test_every_model_offered_in_settings_has_a_price():
    """A model a user can select but that we cannot price would produce silent NULL gaps
    in their spend chart."""
    from app.config import MODEL_CATALOG

    missing = [
        f"{provider}/{model}"
        for provider, models in MODEL_CATALOG.items()
        for model in models
        if pricing.rate_for(provider, model) is None
    ]
    assert not missing, f"selectable models with no price: {missing}"


def test_the_embedding_model_is_priced():
    """It runs on every single message — the easiest cost to forget and the one most
    likely to add up."""
    from app.config import settings

    assert pricing.rate_for(settings.embed_provider, settings.embed_model) is not None
