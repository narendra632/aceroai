"""The Learn constants endpoint, and the boundary that keeps it safe.

This endpoint exists so the Learn section never hardcodes a number. That is a small,
pleasant feature with one sharp edge: it serves values straight out of `settings`, and
`settings` also holds the database URL, the JWT secret, both provider API keys and the
Telegram bot token.

So the interesting tests here are not "does it return 16". They are:

- it cannot be read without logging in
- nothing secret-shaped can ever appear in the payload, including a setting added later
- every value it serves matches the live configuration, so the page cannot drift

The third is the whole point of the endpoint. The second is the whole point of the
allow-list.
"""

import pytest

from app.api.schemas import LearnConstants
from app.config import settings
from app.core import tools
from app.core.composer import HISTORY_LIMIT
from app.services import memory as memory_svc

#: Settings whose *values* must never leave the server. Matched by name so a setting added
#: next year is covered without anyone remembering to update this list.
SECRET_SHAPES = ("key", "token", "secret", "password", "url", "dsn", "credential")


def _secret_values() -> dict[str, str]:
    out = {}
    for name in type(settings).model_fields:  # on the class, not the instance
        if any(shape in name.lower() for shape in SECRET_SHAPES):
            value = getattr(settings, name)
            if isinstance(value, str) and value:
                out[name] = value
    return out


def test_constants_requires_authentication(client):
    """It describes the system rather than the user, so it holds nothing private — but a
    public route is a decision to make deliberately, not one to arrive at by omission."""
    assert client.get("/api/learn/constants").status_code == 401


def test_constants_returns_the_live_configuration(auth_client):
    """The claim the whole feature rests on: what the page shows is what the system uses.

    Asserted against `settings` rather than against literals. A test with `== 16` in it
    would need editing every time a value is tuned, which is exactly the maintenance
    burden this endpoint exists to remove.
    """
    body = auth_client.get("/api/learn/constants").json()

    assert body["recall_k"] == settings.memory_recall_k
    assert body["recall_pool"] == settings.recall_pool
    assert body["rrf_k"] == settings.rrf_k
    assert body["vector_only_max"] == settings.vector_only_max
    assert body["lexical_only_max"] == settings.lexical_only_max
    assert body["memory_dedup_distance"] == settings.memory_dedup_distance
    assert body["consensus_max_distance"] == settings.consensus_max_distance
    assert body["tools_max_iters"] == settings.tools_max_iters
    assert body["span_retention_days"] == settings.span_retention_days
    assert body["turn_retention_days"] == settings.turn_retention_days


def test_constants_that_are_not_settings_come_from_where_they_are_defined(auth_client):
    """Some of these are engineering measurements, not per-environment configuration —
    the history window, the graph's node ceiling. They are read from the module that owns
    them for the same reason: so the page cannot disagree with the code."""
    body = auth_client.get("/api/learn/constants").json()

    assert body["history_limit"] == HISTORY_LIMIT
    assert body["graph_limit"] == memory_svc.GRAPH_LIMIT
    assert body["graph_warn_at"] == memory_svc.graph_warn_at()
    assert body["graph_neighbours"] == memory_svc.GRAPH_NEIGHBOURS
    assert body["graph_max_distance"] == memory_svc.GRAPH_MAX_DISTANCE
    assert body["tool_count"] == len(tools.TOOLS)


def test_the_payload_contains_no_secret(auth_client):
    """The allow-list is a security boundary, not a convenience.

    Replacing it with `settings.model_dump()` would put the database URL, the JWT secret
    and both provider keys into a browser. This fails if that ever happens — including by
    accident, via a setting nobody thought about.
    """
    body = auth_client.get("/api/learn/constants").json()
    haystack = str(body)

    for name, value in _secret_values().items():
        assert value not in haystack, f"the value of settings.{name} is exposed by /api/learn"


def test_no_field_is_even_named_like_a_secret():
    """A value can be secret without matching a known string — an empty key in dev, for
    instance, would slip past the check above. So the field *names* are constrained too."""
    for field in LearnConstants.model_fields:
        assert not any(shape in field.lower() for shape in SECRET_SHAPES), (
            f"LearnConstants.{field} is named like a secret; the Learn page quotes limits "
            "and thresholds only"
        )


def test_every_field_is_a_number():
    """Numbers are safe to publish and are all the page quotes. A string field would be the
    first step toward leaking a model name, an endpoint, or a key."""
    for field, info in LearnConstants.model_fields.items():
        assert info.annotation in (int, float), (
            f"LearnConstants.{field} is {info.annotation}; only int and float belong here"
        )


@pytest.mark.parametrize("field", sorted(LearnConstants.model_fields))
def test_every_declared_field_is_actually_served(auth_client, field):
    """A field declared and never populated would render as `null` on the page. Pydantic
    would catch a missing required field at response time, so this is really asserting the
    endpoint still answers at all for each one."""
    body = auth_client.get("/api/learn/constants").json()
    assert field in body and body[field] is not None
