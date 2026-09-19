import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str
    password: str


class MessageIn(BaseModel):
    message: str
    session_id: uuid.UUID | None = None
    deep: bool = False  # explicit "think harder": route this turn to deeper reasoning


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    channel: str
    last_active_at: dt.datetime


class SessionPatch(BaseModel):
    title: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: dt.datetime


# --- tasks ---


class TaskIn(BaseModel):
    title: str
    notes: str | None = None
    priority: int = Field(default=2, ge=1, le=3)  # 1 high · 2 mid · 3 low
    due_at: dt.datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: str | None = None
    due_at: dt.datetime | None = None
    snoozed_until: dt.datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    notes: str | None
    status: str
    priority: int
    due_at: dt.datetime | None
    snoozed_until: dt.datetime | None
    completed_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


# --- journal ---


class JournalIn(BaseModel):
    content: str
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    entry_date: dt.date | None = None


class JournalUpdate(BaseModel):
    content: str | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class JournalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_date: dt.date
    content: str
    mood: int | None
    tags: list[str]
    channel: str
    created_at: dt.datetime


# --- settings ---


class SettingsUpdate(BaseModel):
    provider: str | None = None
    model_chat: str | None = None
    model_deep: str | None = None
    monthly_budget_usd: Decimal | None = None
    # None already means "not sent" above, so turning a limit OFF needs its own flag.
    clear_budget: bool = False


class BudgetStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: None = no limit set. Everything else is still reported, so the interface can show
    #: what a month costs before asking the user to pick a ceiling.
    limit_usd: Decimal | None
    spent_usd: Decimal
    remaining_usd: Decimal | None
    used_ratio: float
    #: "off" | "ok" | "warning" | "exceeded"
    state: str
    resets_on: dt.date
    warn_ratio: float


class EmbeddingInfo(BaseModel):
    provider: str
    model: str
    dimensions: int
    pinned: bool
    note: str


class SettingsOut(BaseModel):
    provider: str
    model_chat: str
    model_deep: str
    available_providers: list[str]
    model_catalog: dict[str, list[str]]
    # "provider/model" entries where picking it for `deep` buys nothing, because the model
    # has no reasoning control. A toggle that silently does nothing is worse than one that
    # is not offered, so the interface says so.
    no_reasoning_control: list[str]
    defaults: dict[str, str]
    embedding: EmbeddingInfo
    budget: BudgetStatus


# --- memory / knowledge graph ---


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    fact: str
    category: str
    # Reads ProfileFact.effective_confidence, not the stored column: a confirmed fact is
    # certain by definition, while the column keeps the model's original estimate so
    # un-confirming can restore it.
    confidence: float = Field(validation_alias="effective_confidence")
    source: str  # "inferred" (the assistant concluded it) | "stated" (the user confirmed it)
    status: str  # "active" | "superseded" | "rejected"
    superseded_by: uuid.UUID | None
    # Set when this fact was stored despite closely resembling another. It is a QUESTION,
    # not a verdict: the alternative was deleting it, and distance cannot tell a
    # restatement from a genuinely different fact (AI-901 vs AI-103 measure 0.098 apart).
    possible_duplicate_of: uuid.UUID | None = None
    valid_from: dt.datetime
    created_at: dt.datetime
    updated_at: dt.datetime


class FactDetailOut(FactOut):
    """Everything the detail panel needs, resolved server-side.

    `source_session_id` turns `source_ref` (a message id) into something the UI can link to,
    and `previous` makes a superseded fact's history reachable rather than merely stored.
    """

    source_session_id: uuid.UUID | None = None
    previous: FactOut | None = None
    #: The fact this one is suspected of duplicating, resolved so the panel can show both
    #: side by side — a flag pointing at an id the user cannot read is not reviewable.
    resembles: FactOut | None = None


class FactPatch(BaseModel):
    # Changing `fact` supersedes the row (and needs a fresh embedding); changing only the
    # metadata updates it in place. See services/memory.update_fact.
    fact: str | None = None
    category: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GraphNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fact: str
    category: str
    confidence: float
    source: str
    valid_from: dt.datetime


class GraphEdge(BaseModel):
    source: uuid.UUID
    target: uuid.UUID
    distance: float  # cosine distance: 0 = identical meaning, 1 = unrelated


class GraphOut(BaseModel):
    """Deliberately carries no embeddings — the 768-dimensional vectors never leave the
    server. The client receives only what it needs to draw."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # True when more facts exist than the graph will draw. Silently showing a subset of
    # someone's memory as if it were all of it is the kind of quiet lie that erodes trust
    # in the whole view.
    truncated: bool = False
    total: int = 0
    # The rendering ceiling, sent so the interface can name the actual number rather than
    # hard-coding a copy of it that drifts.
    render_limit: int = 0
    # True once the memory approaches or passes that ceiling. Surfaced in the UI on
    # purpose: the moment to switch the layout to a Barnes-Hut quadtree should announce
    # itself where it will be seen, not sit in a document nobody re-reads.
    needs_faster_layout: bool = False


class MemoryStatsOut(BaseModel):
    total: int
    by_category: dict[str, int]
    by_source: dict[str, int]
    by_status: dict[str, int]
    per_day: list[dict]


# --- insights (read-only) ---


class InsightsSummary(BaseModel):
    calls: int
    cost_usd: Decimal
    tokens_in: int
    tokens_out: int
    tokens_thinking: int
    failed: int
    error_rate: float
    # Percentiles, never a mean — one slow turn would hide what a typical turn feels like.
    p50_ms: int | None
    p95_ms: int | None
    p50_ttft_ms: int | None
    # Calls whose model had no known price, so a total can say how complete it is.
    unpriced: int


class SeriesPoint(BaseModel):
    day: str
    kind: str
    calls: int
    cost_usd: Decimal


class ModelUsage(BaseModel):
    provider: str | None
    model: str | None
    calls: int
    cost_usd: Decimal
    tokens_in: int
    tokens_out: int
    # True for the embedding model, which is not selectable.
    pinned: bool = False


class ProviderComparison(BaseModel):
    provider: str | None
    calls: int
    cost_usd: Decimal
    cost_per_call: Decimal
    p50_ms: int | None
    p50_ttft_ms: int | None
    error_rate: float


class ErrorCount(BaseModel):
    error_type: str
    count: int


class TurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    provider: str | None
    model: str | None
    effort: str | None
    session_id: uuid.UUID | None
    started_at: dt.datetime
    duration_ms: int | None
    ttft_ms: int | None
    rounds: int | None
    tokens_in: int | None
    tokens_out: int | None
    tokens_thinking: int | None
    tokens_cached: int | None
    cost_usd: Decimal | None
    pricing_version: str | None
    ok: bool
    error_type: str | None


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    seq: int
    duration_ms: int | None
    meta: dict | None


class RecalledFactOut(BaseModel):
    """A fact that was injected into one turn's prompt, resolved from the id on its span."""

    id: uuid.UUID
    fact: str
    category: str


class TurnDetail(BaseModel):
    turn: TurnOut
    spans: list[SpanOut]
    #: What memory contributed to this turn. Empty when nothing was recalled — which after
    #: hybrid recall is a real state, not a gap in the data.
    recalled: list[RecalledFactOut] = []


class InsightsOverview(BaseModel):
    """Everything the page needs in ONE request.

    Six round-trips on a page load would each pay the same cold-connection cost to a VM in
    Oregon. The queries are cheap; the latency is not.
    """

    summary: InsightsSummary
    series: list[SeriesPoint]
    by_model: list[ModelUsage]
    by_provider: list[ProviderComparison]
    errors: list[ErrorCount]
    # When recording began, so the page never implies it covers a period it does not.
    data_start: dt.datetime | None
    # Cost is an estimate; this names the price list behind it.
    pricing_version: str


class LearnConstants(BaseModel):
    """The tuning values the Learn section is allowed to quote.

    Typed field by field on purpose. A settings key that is removed becomes a **type
    error at import**, not a missing key discovered by a reader seeing `{recall_k}` on
    the page. And an explicit model is what makes the allow-list in `api/learn.py`
    readable at a glance — which matters, because that allow-list is the only thing
    standing between this endpoint and the database URL, the JWT secret, and both
    provider keys.
    """

    # recall — how a message finds the facts that answer it
    recall_k: int
    recall_pool: int
    rrf_k: int
    vector_only_max: int
    lexical_only_max: int
    lexical_terms_max: int
    lexical_max_df: float
    lexical_rare_df: float
    vector_only_max_distance: float
    consensus_max_distance: float
    memory_recall_timeout_s: float

    # memory — how a fact is judged on the way in
    memory_dedup_distance: float
    embed_dim: int

    # the prompt — what the model is shown each turn
    history_limit: int
    context_tasks_limit: int
    tools_max_iters: int
    tool_count: int
    max_input_chars: int

    # the knowledge map
    graph_limit: int
    graph_warn_at: int
    graph_neighbours: int
    graph_max_distance: float

    # observability — how long the record is kept
    span_retention_days: int
    turn_retention_days: int

    # scheduled work and notifications
    #
    # NOTE: numbers ONLY, here and everywhere in this model. `test_api_learn.py` asserts
    # every field is int or float, and that assertion is a security boundary rather than a
    # style rule: it makes leaking a secret-shaped string through this endpoint
    # structurally impossible. Cron expressions therefore do not belong here — the Learn
    # page reads those from /api/jobs, which is scoped to the authenticated user.
    job_count: int
    job_tick_seconds: int
    job_catch_up_hours: int
    notification_retention_days: int
    quiet_hours_start: int
    quiet_hours_end: int
    push_ttl_default_s: int
    push_payload_max_bytes: int


# --- notifications and scheduled jobs (migration 011) ---


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    url: str | None
    tag: str | None
    created_at: dt.datetime
    read_at: dt.datetime | None
    # NULL means it never reached a device. That is information the user can act on —
    # quiet hours, the daily cap, no subscription, or a send that failed — so it is
    # surfaced rather than hidden. Since migration 013 it is when it was LAST delivered.
    pushed_at: dt.datetime | None
    # How many times this record was delivered. Greater than 1 for a reminder that repeats
    # until acted on, so the panel can say "reminded 4 times" rather than showing four rows.
    push_count: int

    model_config = ConfigDict(from_attributes=True)


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


class PushSubscribeIn(BaseModel):
    """Exactly what `PushSubscription.toJSON()` gives the browser, and nothing else.

    No credential of ours travels in either direction here: `p256dh` and `auth` are the
    BROWSER's keys, generated by it for this origin, and our VAPID private key never
    leaves the server.
    """

    endpoint: str
    p256dh: str
    auth: str


class PushStatusOut(BaseModel):
    #: Whether this server can send at all — false when no VAPID keys are configured.
    configured: bool
    #: The VAPID public key, which is public by design and required by the browser to
    #: subscribe. The private half is never serialised anywhere.
    public_key: str
    devices: int
    quiet_hours_start: int | None
    quiet_hours_end: int | None
    #: The user's ceiling on deliveries per day. **0, and the default, means no ceiling.**
    #: Retained as an escape hatch for a looping job rather than as a product feature —
    #: expected volume is governed by per-tag repetition suppression instead.
    daily_push_cap: int | None
    #: How many notifications reached a device today. A readout, not a limit — and counted
    #: from what was DELIVERED, so clearing the panel does not reset it.
    pushed_today: int


class ClearedOut(BaseModel):
    """The ids a bulk removal actually removed.

    Returned rather than a count, because the undo restores exactly this set. "Restore
    everything read" would be the obvious inverse and is wrong: anything marked read between
    the clear and the undo would be resurrected along with it.
    """

    ids: list[uuid.UUID]


class CapacityOut(BaseModel):
    used_bytes: int
    total_bytes: int
    percent: float


class VitalsOut(BaseModel):
    """What the machine is doing right now.

    **Every measurement is optional, and that is the point.** `/proc` does not exist on
    Windows, so on the development machine memory and load are genuinely absent. Making the
    absence expressible in the type is what stops it being encoded as a zero — and "0%
    memory pressure" is the most reassuring possible way to say "I have no idea".
    """

    disk: CapacityOut | None
    memory: CapacityOut | None
    load_1m: float | None
    database_bytes: int | None
    #: When the scheduler last completed a pass. **None means "not yet in this process"** —
    #: true after a restart, and true for at most one tick interval. Read together with
    #: `uptime_seconds`, which is what separates "just booted" from "the ticker has stopped".
    last_tick: dt.datetime | None
    uptime_seconds: float
    #: So the client can judge staleness without hard-coding the server's schedule.
    tick_interval_seconds: int
    #: The threshold `disk_watch` notifies at, so the interface and the job cannot disagree
    #: about what "getting full" means.
    disk_warn_percent: int


class JobOut(BaseModel):
    name: str
    description: str
    #: The raw cron expression — the truth.
    schedule: str
    #: The same thing as an English phrase — what a person reads. Rendered server-side so
    #: there is one implementation rather than a second one in TypeScript that can drift.
    when: str
    uses_ai: bool
    default_on: bool
    enabled: bool
    last_run_at: dt.datetime | None
    last_status: str | None


class JobPrefIn(BaseModel):
    enabled: bool


class ReviewOut(BaseModel):
    """A briefing Acero wrote. Distinct from a journal entry, which the user wrote."""

    id: uuid.UUID
    kind: str
    content: str
    period_start: dt.datetime
    period_end: dt.datetime
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


# --- investments -------------------------------------------------------------------------
#
# ⚠ Every monetary field here is `Decimal`, and every route that returns one MUST declare its
# response model. Pydantic serialises a Decimal to an exact quoted JSON string; FastAPI's
# `jsonable_encoder` — the path taken when a route returns a bare dict — turns it into a
# float, and `Decimal("0.86242900")` comes out as `0.862429`. The value survives, the scale
# does not, and once it is a JS number the client can no longer format or combine it
# faithfully. There is no stylistic latitude in this.


class MarkOut(BaseModel):
    """A price, with everything needed to decide whether to believe it."""

    price: Decimal
    currency: str
    observed_at: dt.datetime
    source: str
    age_text: str
    is_stale: bool

    model_config = ConfigDict(from_attributes=True)


class SuspiciousMoveOut(BaseModel):
    """A move too large and too fast to be a price move."""

    on: dt.date
    previous: Decimal
    current: Decimal
    change: Decimal
    gap_days: int
    direction: str

    model_config = ConfigDict(from_attributes=True)


class HoldingOut(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    name: str
    asset_class: str
    currency: str
    quantity: Decimal
    average_cost: Decimal | None
    cost_basis: Decimal
    cost_basis_inr: Decimal
    realised_inr: Decimal
    charges_inr: Decimal
    prepaid_tax_inr: Decimal
    #: ⚠ None means "not known", never zero. A holding whose worth is unknown must say so.
    market_value_inr: Decimal | None
    unrealised_inr: Decimal | None
    unrealised_pct: Decimal | None
    mark: MarkOut | None
    days_to_long_term: int | None
    losses_ring_fenced: bool
    suspicious_move: SuspiciousMoveOut | None
    lots: int

    model_config = ConfigDict(from_attributes=True)


class TotalsOut(BaseModel):
    """A portfolio total that is honest about what it could not include."""

    #: ⚠ What every holding cost — the figure a person means by "invested". Exact whether or
    #: not anything has a price. Use THIS for the headline, never `invested_inr`.
    cost_basis_inr: Decimal
    #: Cost of the priced, non-ring-fenced holdings only, so it stays comparable with
    #: `market_value_inr`. Zero on a book with no prices.
    invested_inr: Decimal
    market_value_inr: Decimal
    unrealised_inr: Decimal
    unrealised_pct: Decimal | None
    realised_inr: Decimal
    #: ⚠ The whole book, crypto included — what the page headline shows. The three fields
    #: above exclude ring-fenced holdings so they stay comparable with each other.
    market_value_all_inr: Decimal
    unrealised_all_inr: Decimal
    unrealised_all_pct: Decimal | None
    #: ⚠ Crypto, apart from everything else. Under s.115BBH its losses offset nothing, so a
    #: single netted figure would show a position the tax code does not permit.
    ring_fenced_inr: Decimal
    #: Named, never counted — the interface must list these beside the total they are absent
    #: from, at the same prominence.
    unpriced: list[str]
    stale: list[str]
    is_complete: bool


class ReturnOut(BaseModel):
    """One measure of return, or a plain statement of why it is missing."""

    kind: str
    label: str
    measures: str
    value: Decimal | None
    unavailable_because: str | None
    covers_from: dt.date | None
    covers_to: dt.date | None
    #: One short line under the figure — the same fact in rupees.
    headline: str | None = None
    #: The longer plain-language note, shown behind an "i" rather than on the card.
    explanation: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AssetTotalOut(BaseModel):
    """One asset class, subtotalled on the server.

    ⚠ A subtotal is a displayed monetary figure. Summing it in the browser would do money
    arithmetic in binary floating point right after the server took care to be exact.
    """

    asset_class: str
    holdings: int
    invested_inr: Decimal
    market_value_inr: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class SummaryOut(BaseModel):
    portfolio_id: uuid.UUID
    name: str
    kind: str
    as_of: dt.datetime
    holdings: list[HoldingOut]
    totals: TotalsOut
    by_asset_class: list[AssetTotalOut]
    #: What the holdings that cannot be valued originally cost.
    unpriced_cost_inr: Decimal
    returns: list[ReturnOut]


class LotOut(BaseModel):
    trade_date: dt.date
    quantity: Decimal
    unit_cost: Decimal
    fx_rate_inr: Decimal
    cost_inr: Decimal
    days_held: int
    long_term_on: dt.date | None
    is_long_term: bool
    days_remaining: int | None

    model_config = ConfigDict(from_attributes=True)


class IfSoldNowOut(BaseModel):
    at_price: Decimal
    quantity: Decimal
    realised_inr: Decimal
    long_term_inr: Decimal
    short_term_inr: Decimal
    weighted_average_realised_inr: Decimal
    #: True on a full disposal, where both bases relieve the entire cost basis and therefore
    #: agree. They diverge on a partial sale.
    bases_agree: bool

    model_config = ConfigDict(from_attributes=True)


class CurrencySplitOut(BaseModel):
    """A foreign holding's return taken apart — all three, never just the total."""

    local: Decimal
    fx: Decimal
    total_inr: Decimal

    model_config = ConfigDict(from_attributes=True)


class TransactionOut(BaseModel):
    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    txn_type: str
    trade_date: dt.date
    quantity: Decimal
    price: Decimal
    currency: str
    fx_rate_inr: Decimal | None
    charges_inr: Decimal
    prepaid_tax_inr: Decimal
    net_inr: Decimal
    entry_source: str
    note: str | None
    created_at: dt.datetime
    #: ⚠ Superseded rows stay visible. Hiding them would destroy the property the append-only
    #: design exists for: seeing what you believed at the time.
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None


class ObservationOut(BaseModel):
    observed_at: dt.datetime
    price: Decimal
    currency: str
    source: str
    quality: str

    model_config = ConfigDict(from_attributes=True)


class HoldingDetailOut(BaseModel):
    holding: HoldingOut
    lots: list[LotOut]
    if_sold_now: IfSoldNowOut | None
    currency_split: CurrencySplitOut | None
    transactions: list[TransactionOut]
    observations: list[ObservationOut]
    moves: list[SuspiciousMoveOut]


class CurvePointOut(BaseModel):
    day: dt.date
    invested_inr: Decimal
    #: ⚠ None on any day where even one open holding lacks a price. Nothing is interpolated,
    #: and a total is never assembled from partial coverage.
    value_inr: Decimal | None
    priced: int
    open_holdings: int

    model_config = ConfigDict(from_attributes=True)


class PriceRefreshOut(BaseModel):
    """What a live refresh did. The page reloads its figures when `written` is non-zero."""

    #: New observations recorded. Zero is the common, healthy answer: nothing was stale.
    written: int
    #: Sources that could not be reached. Their holdings keep their last price, shown stale.
    failed: list[str]


class CurveOut(BaseModel):
    points: list[CurvePointOut]
    covered_from: dt.date | None
    covered_to: dt.date | None
    #: ⚠ How many days actually carry a value, against how many are plotted. The first and
    #: last covered day are not enough on their own: coverage can have a hole in the middle
    #: — buy something and leave it unpriced for a week — and "covered from X to Y" would
    #: then claim a continuity the data does not have.
    covered_days: int
    total_days: int
    moves: list[SuspiciousMoveOut]


class DraftIn(BaseModel):
    symbol: str
    txn_type: str
    quantity: Decimal
    price: Decimal
    trade_date: dt.date
    exchange: str | None = None
    name: str | None = None
    asset_class: str | None = None
    currency: str | None = None
    fx_rate_inr: Decimal | None = None


class DraftOut(BaseModel):
    """What was understood, costed and validated — before anything is written."""

    symbol: str
    name: str
    exchange: str
    asset_class: str
    txn_type: str
    trade_date: dt.date
    quantity: Decimal
    price: Decimal
    currency: str
    fx_rate_inr: Decimal
    charges_inr: Decimal
    prepaid_tax_inr: Decimal
    gross_inr: Decimal
    net_inr: Decimal
    warnings: list[str]
    creates_instrument: bool


class ReverseIn(BaseModel):
    note: str | None = None
