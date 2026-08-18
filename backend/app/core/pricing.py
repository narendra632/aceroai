"""What a model call costs — estimated, dated, and frozen at the moment it happened.

Three decisions worth knowing about:

**Cost is computed once, when the turn is recorded, and stored.** Prices change. If cost
were derived at read time from a current price list, opening the Insights page after a
price change would silently rewrite last month's spend. Every real billing system freezes
the rate at the moment of the transaction, for exactly this reason. `pricing_version` is
stored alongside so any figure on screen can be traced back to the rate that produced it.

**The catalog is code with effective dates, not a database table.** A table would be
editable without a deploy, which sounds like an advantage until it needs an admin UI, a
migration, and a seeding story — for data that changes a few times a year in a single-user
app. Code review is better change control for prices than a form.

**These are ESTIMATES.** Google's Agent Platform bills through Cloud Billing and OpenAI
through its own account; we never see either invoice. Everything derived from this module
must be labelled as an estimate. Showing a guess styled as a bill is the kind of small
dishonesty that destroys trust in a dashboard the first time it disagrees with reality.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

# Bump when any rate below changes. Stored on every turn so a number can be explained.
PRICING_VERSION = "2026-08"

_MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class Rate:
    """Dollars per million tokens, effective from a date."""

    valid_from: dt.date
    input_: Decimal
    output: Decimal
    # Cached input is billed at a discount by both providers. None = charge the full rate.
    cached_input: Decimal | None = None


def _r(valid_from: str, input_: str, output: str, cached: str | None = None) -> Rate:
    return Rate(
        valid_from=dt.date.fromisoformat(valid_from),
        input_=Decimal(input_),
        output=Decimal(output),
        cached_input=Decimal(cached) if cached is not None else None,
    )


# Keyed "provider/model". Several rates per model are allowed, newest last; the one in
# effect at the turn's timestamp is used.
#
# ⚠ Rates are transcribed from public price lists and go stale. A model missing here costs
# NULL, not zero — a visible gap that gets fixed, rather than a silent understatement.
PRICING: dict[str, list[Rate]] = {
    # --- Google (Gemini via Agent Platform) ---
    "google/gemini-3.5-flash": [_r("2026-01-01", "0.30", "2.50", "0.075")],
    "google/gemini-3.5-flash-lite": [_r("2026-01-01", "0.10", "0.40", "0.025")],
    "google/gemini-3.6-flash": [_r("2026-01-01", "0.30", "2.50", "0.075")],
    "google/gemini-3.7-flash": [_r("2026-01-01", "0.30", "2.50", "0.075")],
    "google/gemini-3.1-pro-preview": [_r("2026-01-01", "1.25", "10.00", "0.31")],
    "google/gemini-2.5-flash": [_r("2026-01-01", "0.30", "2.50", "0.075")],
    "google/gemini-2.5-pro": [_r("2026-01-01", "1.25", "10.00", "0.31")],
    # Embeddings: input only, no output to bill.
    "google/gemini-embedding-001": [_r("2026-01-01", "0.15", "0")],
    "google/gemini-3.1-flash-lite": [_r("2026-01-01", "0.10", "0.40", "0.025")],
    # --- OpenAI ---
    # ⚠ Frontier rates change often and these are transcribed, not fetched. They exist to
    # make relative cost visible; treat the absolute number as indicative.
    "openai/gpt-5.5": [_r("2026-01-01", "1.75", "14.00", "0.175")],
    "openai/gpt-5.4": [_r("2026-01-01", "1.50", "12.00", "0.150")],
    "openai/gpt-5.4-mini": [_r("2026-01-01", "0.30", "2.40", "0.030")],
    "openai/gpt-5.4-nano": [_r("2026-01-01", "0.10", "0.80", "0.010")],
    "openai/gpt-5.2": [_r("2026-01-01", "1.25", "10.00", "0.125")],
    "openai/gpt-5.1": [_r("2026-01-01", "1.25", "10.00", "0.125")],
    "openai/gpt-5": [_r("2026-01-01", "1.25", "10.00", "0.125")],
    "openai/gpt-4.1": [_r("2026-01-01", "2.00", "8.00", "0.50")],
}


def rate_for(
    provider: str | None, model: str | None, when: dt.datetime | None = None
) -> Rate | None:
    """The rate in effect for this model at `when`. None when the model has no known price."""
    if not provider or not model:
        return None
    rates = PRICING.get(f"{provider}/{model}")
    if not rates:
        return None
    on = (when or dt.datetime.now(dt.UTC)).date()
    eligible = [r for r in rates if r.valid_from <= on]
    # Before the earliest recorded rate, fall back to it rather than reporting nothing —
    # a slightly-wrong old price is more useful than a hole in the chart.
    return max(eligible, key=lambda r: r.valid_from) if eligible else rates[0]


def estimate_cost(
    provider: str | None,
    model: str | None,
    *,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    tokens_thinking: int | None = None,
    tokens_cached: int | None = None,
    when: dt.datetime | None = None,
) -> Decimal | None:
    """Estimated dollars for one call, or None if the model has no known price.

    Thinking tokens are billed at the OUTPUT rate — they are generated text the user simply
    never sees. Counting them as input, or not at all, understates the expensive half.

    `tokens_cached` is a *subset* of `tokens_in` that both providers bill at a discount, so
    it is subtracted from the full-price portion rather than added on top.
    """
    rate = rate_for(provider, model, when)
    if rate is None:
        return None

    cached = max(0, tokens_cached or 0)
    full_input = max(0, (tokens_in or 0) - cached)
    output = max(0, tokens_out or 0) + max(0, tokens_thinking or 0)

    cost = (Decimal(full_input) * rate.input_ + Decimal(output) * rate.output) / _MTOK
    if cached:
        cached_rate = rate.cached_input if rate.cached_input is not None else rate.input_
        cost += Decimal(cached) * cached_rate / _MTOK
    # Six decimal places matches the column; a single cheap turn is worth ~$0.000x, so
    # rounding to cents would record most of this app's activity as zero.
    return cost.quantize(Decimal("0.000001"))
