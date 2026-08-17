"""The Insights API: aggregates in SQL, read-only, honest about what it doesn't know."""

import datetime as dt
import uuid
from decimal import Decimal

from app.db.models import Span, Turn


def _turn(db, user, **kw):
    row = Turn(
        user_id=user.id,
        kind=kw.pop("kind", "chat"),
        provider=kw.pop("provider", "google"),
        model=kw.pop("model", "gemini-3.5-flash"),
        started_at=kw.pop("started_at", dt.datetime.now(dt.UTC)),
        duration_ms=kw.pop("duration_ms", 1000),
        ttft_ms=kw.pop("ttft_ms", 500),
        tokens_in=kw.pop("tokens_in", 100),
        tokens_out=kw.pop("tokens_out", 20),
        cost_usd=kw.pop("cost_usd", Decimal("0.001")),
        ok=kw.pop("ok", True),
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _overview(client, **params):
    return client.get("/api/insights/overview", params=params or None).json()


# --- the guarantee ------------------------------------------------------------------


def test_insights_is_read_only(auth_client, db, user):
    """Nothing on this page may mutate anything — that is what makes it safe to open,
    reload and leave open. Checked by counting rows before and after every route."""
    _turn(db, user)
    before = (db.query(Turn).count(), db.query(Span).count())

    turn_id = auth_client.get("/api/insights/turns").json()[0]["id"]
    _overview(auth_client)
    auth_client.get(f"/api/insights/turns/{turn_id}")
    _overview(auth_client, all_time=True)

    assert (db.query(Turn).count(), db.query(Span).count()) == before


def test_insights_requires_auth(client):
    assert client.get("/api/insights/overview").status_code == 401
    assert client.get("/api/insights/turns").status_code == 401


def test_another_users_turn_is_not_readable(auth_client, db, other_user):
    theirs = _turn(db, other_user)
    assert auth_client.get(f"/api/insights/turns/{theirs.id}").status_code == 404


# --- the numbers --------------------------------------------------------------------


def test_summary_totals_and_error_rate(auth_client, db, user):
    _turn(db, user, cost_usd=Decimal("0.002"), tokens_in=100, tokens_out=10)
    _turn(db, user, cost_usd=Decimal("0.003"), tokens_in=200, tokens_out=20)
    # Rejected before reaching the model, so it consumed nothing.
    _turn(
        db,
        user,
        cost_usd=None,
        tokens_in=None,
        tokens_out=None,
        ok=False,
        error_type="RateLimitError",
    )

    s = _overview(auth_client)["summary"]

    assert s["calls"] == 3
    assert Decimal(s["cost_usd"]) == Decimal("0.005")
    assert s["tokens_in"] == 300
    assert s["failed"] == 1
    assert abs(s["error_rate"] - 1 / 3) < 0.001


def test_latency_is_reported_as_percentiles_not_a_mean(auth_client, db, user):
    """One 30-second turn must not hide what a typical turn feels like."""
    for ms in (100, 110, 120, 130, 30000):  # four fast, one pathological
        _turn(db, user, duration_ms=ms)

    s = _overview(auth_client)["summary"]

    mean = (100 + 110 + 120 + 130 + 30000) / 5  # 6092ms — describes nothing that happened
    assert s["p50_ms"] == 120
    assert s["p50_ms"] < mean / 10
    assert s["p95_ms"] > s["p50_ms"]


def test_background_work_is_excluded_from_felt_latency(auth_client, db, user):
    """Nobody waits on an embedding, so letting it into the percentile would report a
    speed no human ever experiences."""
    _turn(db, user, kind="chat", duration_ms=2000)
    for _ in range(20):
        _turn(db, user, kind="embed", duration_ms=5, cost_usd=Decimal("0.000001"))

    assert _overview(auth_client)["summary"]["p50_ms"] == 2000


def test_unpriced_calls_are_counted_so_a_total_can_admit_its_gaps(auth_client, db, user):
    _turn(db, user, cost_usd=Decimal("0.001"))
    _turn(db, user, model="model-shipped-tomorrow", cost_usd=None)

    assert _overview(auth_client)["summary"]["unpriced"] == 1


def test_spend_is_split_by_what_the_call_was_for(auth_client, db, user):
    """The headline finding of this whole section: a message is not one model call."""
    _turn(db, user, kind="chat", cost_usd=Decimal("0.010"))
    _turn(db, user, kind="embed", cost_usd=Decimal("0.001"))
    _turn(db, user, kind="memory_extract", cost_usd=Decimal("0.004"))

    by_kind = {p["kind"]: Decimal(p["cost_usd"]) for p in _overview(auth_client)["series"]}

    assert by_kind == {
        "chat": Decimal("0.010"),
        "embed": Decimal("0.001"),
        "memory_extract": Decimal("0.004"),
    }
    # A third of spend here is background work that used to be invisible entirely.
    assert by_kind["embed"] + by_kind["memory_extract"] > 0


def test_by_model_is_ordered_most_expensive_first(auth_client, db, user):
    _turn(db, user, model="cheap-model", cost_usd=Decimal("0.001"))
    _turn(db, user, model="dear-model", cost_usd=Decimal("0.050"))

    rows = _overview(auth_client)["by_model"]
    assert [r["model"] for r in rows][:2] == ["dear-model", "cheap-model"]


def test_provider_comparison_ignores_pinned_embeddings(auth_client, db, user):
    """Embeddings always run on Google regardless of the chat-provider setting, so
    counting them would blame Google for work the choice never touched."""
    _turn(db, user, kind="chat", provider="google", cost_usd=Decimal("0.010"), duration_ms=2000)
    _turn(db, user, kind="chat", provider="openai", cost_usd=Decimal("0.030"), duration_ms=1000)
    for _ in range(10):
        _turn(db, user, kind="embed", provider="google", cost_usd=Decimal("0.000001"))

    rows = {r["provider"]: r for r in _overview(auth_client)["by_provider"]}

    assert rows["google"]["calls"] == 1  # the ten embeddings are not counted
    assert Decimal(rows["openai"]["cost_per_call"]) > Decimal(rows["google"]["cost_per_call"])
    assert rows["openai"]["p50_ms"] < rows["google"]["p50_ms"]


def test_errors_are_grouped_by_kind(auth_client, db, user):
    _turn(db, user, ok=False, error_type="RateLimitError")
    _turn(db, user, ok=False, error_type="RateLimitError")
    _turn(db, user, ok=False, error_type="BillingError")

    errs = {e["error_type"]: e["count"] for e in _overview(auth_client)["errors"]}
    # Telling these apart is the difference between waiting and fixing a billing account.
    assert errs == {"RateLimitError": 2, "BillingError": 1}


def test_the_page_states_when_recording_began(auth_client, db, user):
    """A chart implying it has always been watching is misleading."""
    assert _overview(auth_client)["data_start"] is None

    _turn(db, user)
    body = _overview(auth_client)
    assert body["data_start"] is not None
    assert body["pricing_version"]


def test_a_time_window_excludes_older_turns(auth_client, db, user):
    old = dt.datetime.now(dt.UTC) - dt.timedelta(days=60)
    _turn(db, user, started_at=old, cost_usd=Decimal("9.000"))
    _turn(db, user, cost_usd=Decimal("0.001"))

    assert Decimal(_overview(auth_client, days=30)["summary"]["cost_usd"]) == Decimal("0.001")
    assert Decimal(_overview(auth_client, all_time=True)["summary"]["cost_usd"]) == Decimal("9.001")


# --- the waterfall ------------------------------------------------------------------


def test_turn_detail_returns_stages_in_order(auth_client, db, user):
    turn = _turn(db, user)
    stages = [("persist_user", 30), ("memory_recall", 1600), ("llm_round1", 1400)]
    for seq, (name, ms) in enumerate(stages):
        db.add(Span(turn_id=turn.id, name=name, seq=seq, duration_ms=ms, meta={"facts": 12}))
    db.commit()

    body = auth_client.get(f"/api/insights/turns/{turn.id}").json()

    assert [s["name"] for s in body["spans"]] == [n for n, _ in stages]
    assert body["spans"][1]["duration_ms"] == 1600
    assert body["spans"][0]["meta"] == {"facts": 12}
    assert body["turn"]["id"] == str(turn.id)


def test_a_missing_turn_is_a_404_not_an_empty_waterfall(auth_client):
    assert auth_client.get(f"/api/insights/turns/{uuid.uuid4()}").status_code == 404


def test_first_word_can_never_appear_after_the_reply_finished(auth_client, db, user):
    """Failed turns abort in milliseconds and record no first-token time. Left in, they
    drag the duration median down while leaving the time-to-first-token median alone —
    producing "typical reply 2393ms, first word after 2538ms", which is impossible.
    Observed on real data before this was fixed."""
    for _ in range(3):
        _turn(db, user, kind="chat", duration_ms=3000, ttft_ms=2500, ok=True)
    for _ in range(3):
        _turn(db, user, kind="chat", duration_ms=30, ttft_ms=None, ok=False, error_type="Boom")

    s = _overview(auth_client)["summary"]

    assert s["p50_ttft_ms"] <= s["p50_ms"], "first word cannot precede the reply it starts"
    assert s["p50_ms"] == 3000  # the fast failures do not masquerade as fast replies
