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


class CorporateActionOut(BaseModel):
    """A split or bonus the exchange announced, and what it would do to the book.

    `quantity_before`/`quantity_after` are computed server-side on purpose: they are the
    arithmetic that changes a holding's size, and a browser computing them would be doing
    that arithmetic in binary floating point.
    """

    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    name: str
    action_type: str
    ex_date: dt.date | None
    purpose: str
    #: PENDING · NEEDS_REVIEW · APPLIED · IGNORED
    status: str
    source: str
    announced_at: dt.datetime
    applied_at: dt.datetime | None
    #: Why a ratio could not be read, or what was done with the action.
    note: str | None
    #: None when the announcement's ratio was never understood — the case a person must read.
    ratio_text: str | None
    quantity_change: Decimal | None
    quantity_before: Decimal | None
    quantity_after: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class ForeignHoldingOut(BaseModel):
    """One security's Schedule FA figures for one calendar year."""

    symbol: str
    name: str
    currency: str
    acquired_on: dt.date
    initial_inr: Decimal
    peak_inr: Decimal | None
    peak_on: dt.date | None
    closing_inr: Decimal | None
    closing_on: dt.date | None
    closing_quantity: Decimal
    gross_income_inr: Decimal
    gross_proceeds_inr: Decimal
    #: ⚠ Coverage against the days it was HELD, not against the length of the period.
    #: Comparing with the period read as missing data for a share bought mid-year, when the
    #: truth was simply that it was not owned yet.
    days_valued: int
    days_held: int
    days_in_period: int
    is_complete: bool

    model_config = ConfigDict(from_attributes=True)


class ScheduleFaOut(BaseModel):
    year: int
    period_start: dt.date
    period_end: dt.date
    holdings: list[ForeignHoldingOut]
    years_available: list[int]

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
    #: ⚠ An announced split or bonus not yet in the ledger. While this is present the price
    #: and the quantity on this row are counting different things, so the profit and loss
    #: beside them is not reliable and the interface must say so rather than show it plainly.
    open_action: CorporateActionOut | None = None

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


class FrameworkComponentOut(BaseModel):
    """One part of the structural score, with the sentence explaining what it measured."""

    name: str
    points: Decimal
    available: Decimal
    detail: str

    model_config = ConfigDict(from_attributes=True)


class AbScoreOut(BaseModel):
    """How much durable demand the framework says a company has.

    ⚠ `total` is `None` when the framework does not APPLY — a US company, or one the user has
    called off-thesis. That is a different answer from zero, which means "measured against
    this framework and found wanting", and an interface that renders them the same way is
    telling the reader something false.
    """

    total: Decimal | None
    available: Decimal
    components: list[FrameworkComponentOut]
    unavailable_because: str | None
    #: ⚠ The crossing count is a floor, not an established figure — the score may be
    #: understated and must not be presented as a ceiling.
    breadth_is_floor: bool

    model_config = ConfigDict(from_attributes=True)


class BottleneckOut(BaseModel):
    """One bottleneck from the framework, for the picker and for explaining a mapping."""

    id: str
    name: str
    summary: str
    crosses: list[str]
    crossings_status: str
    crisis: str
    inflection_text: str
    investability: str

    model_config = ConfigDict(from_attributes=True)


class ScorePartOut(BaseModel):
    """One component of the quality score. ⚠ `points` is null where the inputs were absent —
    which is a different answer from zero and must be rendered differently."""

    name: str
    points: Decimal | None
    available: Decimal
    detail: str

    model_config = ConfigDict(from_attributes=True)


class QualityOut(BaseModel):
    """How good the business is and how sensibly it is priced, from filings alone.

    ⚠ `earned` and `available` must be shown TOGETHER. Six on its own means nothing: six out
    of ten is mediocre and six out of six is excellent, and the difference is entirely how
    many of the filings have been read.
    """

    earned: Decimal
    available: Decimal
    ratio: Decimal | None
    parts: list[ScorePartOut]
    unknown: list[str]
    is_complete: bool

    model_config = ConfigDict(from_attributes=True)


class FlagOut(BaseModel):
    """One checklist answer. ⚠ Every flag is a RED flag: YES is bad."""

    number: int
    question: str
    #: YES · NO · UNKNOWN. Unknown is the truth when nothing was read; a checklist that
    #: answers NO by default reports a clean bill of health it never checked.
    verdict: str
    evidence: str
    #: Measured rather than judged, so no model verdict may later overrule it.
    computed: bool

    model_config = ConfigDict(from_attributes=True)


class GateOut(BaseModel):
    """One rule and what it decided.

    ⚠ `not_applicable` is distinct from `passed`: "not asked" and "asked and satisfied" are
    different facts, and an interface that shows them alike overstates how much was checked.
    """

    gate: str
    passed: bool
    not_applicable: bool
    detail: str


class TriggerOut(BaseModel):
    """What would prove the thesis wrong — a number, a comparison and a deadline."""

    id: uuid.UUID
    metric_key: str
    comparator: str
    threshold: Decimal
    unit: str
    window_until: dt.date
    description: str
    status: str
    fired_at: dt.datetime | None

    model_config = ConfigDict(from_attributes=True)


class ClaimOut(BaseModel):
    """One falsifiable assertion the thesis made."""

    id: uuid.UUID
    claim_text: str
    metric_key: str | None
    due_by: dt.date
    status: str

    model_config = ConfigDict(from_attributes=True)


class ProposalOut(BaseModel):
    """A suggestion, with everything it rests on.

    ⚠ `price_snapshot`, `gate_results` and the three scores are FROZEN at the moment it was
    made. What the system saw is a different fact from what the market later did.
    """

    id: uuid.UUID
    symbol: str
    name: str
    action: str
    #: PENDING · APPROVED · REJECTED · MODIFIED · EXPIRED · BLOCKED — derived, never stored.
    status: str
    blocked_by: str | None
    target_amount_inr: Decimal | None
    target_qty: Decimal | None
    horizon_days: int
    thesis: str
    confidence: Decimal
    ab_score: Decimal | None
    quality_earned: Decimal | None
    quality_available: Decimal | None
    reflexivity_flags_yes: int
    quadrant: str | None
    price_snapshot: dict
    gates: list[GateOut]
    triggers: list[TriggerOut]
    claims: list[ClaimOut]
    created_at: dt.datetime
    decided_at: dt.datetime | None = None
    decision_reason: str | None = None


class DecideIn(BaseModel):
    """⚠ `reason` is required. It is the data that eventually reveals what kinds of suggestion
    keep being turned down, which is the only way the system learns about its own judgement."""

    outcome: str
    reason: str
    modified_amount_inr: Decimal | None = None


class BookLineOut(BaseModel):
    """One book or benchmark, valued at the same prices as all the others."""

    kind: str
    name: str
    purpose: str
    invested_inr: Decimal
    #: ⚠ None when even one holding lacks a price. A total assembled from partial coverage
    #: steps whenever coverage changes, and that is indistinguishable from a real movement.
    value_inr: Decimal | None
    gain_inr: Decimal | None
    gain_pct: Decimal | None
    positions: int
    is_complete: bool

    model_config = ConfigDict(from_attributes=True)


class BooksOut(BaseModel):
    """Every book side by side, plus what you bought that was never suggested."""

    lines: list[BookLineOut]
    as_of: dt.datetime | None
    #: ⚠ False until the real book and a paper book are both fully priced. Comparing a
    #: complete total with a partial one is worse than not comparing at all.
    readable: bool
    #: Holdings the system never suggested — the direct read on your own judgement, and the
    #: one category a single merged ledger would silently discard.
    unaided: list[str]

    model_config = ConfigDict(from_attributes=True)


class MeasureOut(BaseModel):
    """One reading of how the system is doing, with the sample it rests on.

    ⚠ `value` is null while `n` is below the minimum, and that is the honest state for a long
    time. A figure over six outcomes reads exactly like one over six hundred, and nothing in
    an interface can tell the reader which they are seeing unless the figure is withheld.
    """

    name: str
    value: Decimal | None
    n: int
    detail: str

    model_config = ConfigDict(from_attributes=True)


class FiredTriggerOut(BaseModel):
    """A condition that came true, and what made it true."""

    id: uuid.UUID
    symbol: str
    description: str
    metric_key: str
    fired_at: dt.datetime | None
    evidence: dict


class ProposalsOut(BaseModel):
    open: list[ProposalOut]
    recent: list[ProposalOut]
    #: ⚠ Runs that suggested nothing are counted here. A system that only leaves a trace on
    #: the days it acted can never be measured against the days it should have.
    runs_recorded: int
    last_run_at: dt.datetime | None
    #: ⚠ Conditions that have fired and not yet been answered. These outrank everything else
    #: on the screen: a thesis the user holds money against has been contradicted.
    fired: list[FiredTriggerOut] = []
    measures: list[MeasureOut] = []


class MappingOut(BaseModel):
    """Where one company sits in the framework, and what that is worth."""

    id: uuid.UUID
    instrument_id: uuid.UUID
    symbol: str
    name: str
    sector: str | None
    #: ⚠ True when this sector has no fair multiple of its own and the default is standing in.
    #: The margin of safety computed from it is a guess wearing the clothes of a calculation.
    multiple: Decimal
    multiple_is_fallback: bool
    multiple_why: str
    b_bottleneck: str | None
    bottleneck_name: str | None
    a_imperatives: list[str]
    crosses_a_count: int
    crossings_status: str
    is_crisis_accelerated: bool
    inflection_quarter: str | None
    investability: str | None
    rationale: str | None
    proposed_by: str
    #: None means proposed and not yet agreed with — it scores nothing until it is.
    approved_at: dt.datetime | None
    review_after: dt.date | None
    off_framework: bool
    is_held: bool
    score: AbScoreOut
    quality: QualityOut | None = None
    flags: list[FlagOut] = []
    #: Q1 · Q2 · Q3 · Q4 · BORDERLINE · UNKNOWN. ⚠ Q2 and Q4 block a purchase outright, so
    #: BORDERLINE on a thin reading is a refusal to convict rather than a missing answer.
    quadrant: str | None = None
    #: How many full years of filings the quality score rests on.
    years_read: int = 0

    model_config = ConfigDict(from_attributes=True)


class AttentionOut(BaseModel):
    """One thing the framework needs a person for."""

    kind: str
    symbol: str
    detail: str

    model_config = ConfigDict(from_attributes=True)


class FrameworkOut(BaseModel):
    version: int
    approved_at: dt.datetime | None
    imperatives: list[dict]
    bottlenecks: list[BottleneckOut]
    mappings: list[MappingOut]
    attention: list[AttentionOut]

    model_config = ConfigDict(from_attributes=True)


class RemapIn(BaseModel):
    """Move a company to a different bottleneck, or out of the framework entirely."""

    b_bottleneck: str | None = None
    off_framework: bool = False
    rationale: str | None = None


class ApproveIn(BaseModel):
    note: str | None = None


class CrossingsIn(BaseModel):
    """Establish which imperatives a bottleneck blocks.

    ⚠ This writes a new framework version: a crossing set is a claim about the country, and
    changing one changes the rules every later score is measured against.
    """

    crosses: list[str]
    #: CONFIRMED once established; PARTIAL to widen a floor that is still not the full set.
    status: str = "CONFIRMED"
    note: str | None = None


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
    #: Outstanding splits and bonuses, plus recently applied ones so they can be checked.
    corporate_actions: list[CorporateActionOut] = []


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


class SourceOut(BaseModel):
    """One place the system reads from.

    ⚠ `trust_tier` is not decoration. Tier 1 is a filing or a regulator, tier 2 the press,
    tier 3 commentary — and a proposal whose evidence is only tier 3 fails its sourcing gate.
    """

    id: uuid.UUID
    kind: str
    name: str
    handle: str
    trust_tier: int
    is_active: bool
    #: ⚠ Null means nothing is read from it. Adding a source changes what the system can be
    #: talked into, so it waits for a person the way a framework mapping does.
    approved_at: dt.datetime | None
    notes: str | None
    last_polled_at: dt.datetime | None

    model_config = ConfigDict(from_attributes=True)


class AttributionOut(BaseModel):
    """What one source named, and whether its directional calls worked out.

    ⚠ `named` counts **everything** the source said, including the companies never looked at.
    Scoring a source on the ideas that were acted on measures the reader's filter instead of
    the source, and turns a 2.5% hit rate into a 33% one.
    """

    source: str
    trust_tier: int
    named: int
    directional: int
    scored: int
    #: Calls whose horizon has not arrived, or whose prices do not reach it yet.
    pending: int
    became_proposals: int
    hit_rate: MeasureOut

    model_config = ConfigDict(from_attributes=True)


class HeardOut(BaseModel):
    """One thing a source said about one instrument."""

    symbol: str
    name: str
    #: BULL · BEAR · NEUTRAL · MENTION_ONLY. ⚠ Asked of commentary only: an exchange filing
    #: reports that something happened and takes no side, so it is always MENTION_ONLY.
    stance: str
    excerpt: str | None
    source: str
    trust_tier: int
    url: str | None
    published_at: dt.datetime | None
    is_held: bool

    model_config = ConfigDict(from_attributes=True)


class ReadingOut(BaseModel):
    """The reading layer: where information comes from, and what has been said lately."""

    sources: list[SourceOut]
    heard: list[HeardOut]
    attribution: list[AttributionOut]
    #: Sources registered but not yet approved — the decision waiting for the user.
    awaiting_approval: int


class ActiveIn(BaseModel):
    """Switch a source on or off. ⚠ Never a delete: see `SourceOut`."""

    is_active: bool


class QueueLineOut(BaseModel):
    """One company waiting to be looked at.

    ⚠ `mention_count` and `best_trust_tier` are what the queue is ordered by, not the date. A
    company three sources keep returning to is a different proposition from one named once in
    passing, and newest-first would bury it under today's noise.
    """

    id: uuid.UUID
    symbol: str
    name: str
    status: str
    mention_count: int
    #: 1 = a filing or regulator · 2 = press · 3 = commentary. The BEST tier that has ever
    #: named it, because that is what the sourcing gate will read.
    best_trust_tier: int
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    #: ⚠ How long it has sat here. A queue nobody clears is a queue that stopped being read,
    #: and the weekly review asks this question by name.
    age_days: int
    named_by: str | None
    stance: str | None
    excerpt: str | None
    proposed_bottleneck: str | None
    dismissed_reason: str | None
    #: ⚠ These two travel together and must be SHOWN together. "4" means nothing on its own:
    #: four out of four is excellent and four out of ten is mediocre, and the difference is
    #: entirely whether the company's filings had been read.
    quality_earned: Decimal | None = None
    quality_available: Decimal | None = None
    price: Decimal | None = None
    bottleneck_name: str | None = None
    #: Why the model placed it there, in its own words — so a wrong placement can be seen to
    #: be wrong rather than merely doubted.
    bottleneck_why: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ResearchQueueOut(BaseModel):
    """The research queue, and how big the vocabulary behind it is."""

    lines: list[QueueLineOut]
    #: How many companies the reader can recognise. Shown because a vocabulary that failed to
    #: load would make discovery silently stop, and a count of zero says so immediately.
    universe_size: int
    universe_refreshed_at: dt.datetime | None


class DismissIn(BaseModel):
    """⚠ A reason is required by the database, not merely requested. It is the only record of
    what kinds of idea keep being refused."""

    reason: str = Field(min_length=3, max_length=500)


class PromoteIn(BaseModel):
    """Start following a candidate. ⚠ This is the moment it starts costing prices and calls."""

    sector: str | None = None


class DropIn(BaseModel):
    """Something dropped into the inbox: a link, a video, or just a note.

    ⚠ Either is enough, and both together is fine — a link with a line of your own about why
    it matters reads better than the page alone.
    """

    url: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=8000)


class DropOut(BaseModel):
    """What came of it.

    ⚠ `stored` false with a `note` is a real outcome, not an error. A page that needs a
    browser, a PDF, or a listing naming thirty companies each produce nothing — and an inbox
    that swallowed them silently would train its user to drop things into a void.
    """

    stored: bool
    title: str
    url: str | None
    #: 1 = a filing or regulator · 2 = press or your own note. A drop from an exchange or a
    #: regulator is a filing; anything else is a report of one.
    trust_tier: int
    named: list[str]
    #: Companies this put into the research queue for the first time.
    discovered: list[str]
    #: Companies you already follow — filed against the holding rather than queued.
    already_followed: list[str]
    note: str | None

    model_config = ConfigDict(from_attributes=True)


class InvestmentReviewOut(BaseModel):
    """One look backwards, as the facts that were true then.

    ⚠ `content` is a structure of figures assembled by code, never prose written by a model.
    Everywhere else in this module a model is forbidden from producing a number, and a review
    is almost entirely numbers — a summary paragraph would be the one place a figure could be
    restated wrongly with nothing to check it against.
    """

    id: uuid.UUID
    kind: str
    period_start: dt.date
    period_end: dt.date
    generated_at: dt.datetime
    headline: str
    content: dict

    model_config = ConfigDict(from_attributes=True)


class InvestmentReviewsOut(BaseModel):
    reviews: list[InvestmentReviewOut]


class BenchmarkLineOut(BaseModel):
    """One alternative over one window."""

    key: str
    name: str
    #: ⚠ Shown, always. A benchmark that is a proxy has to announce it, or a comparison against
    #: it reads as a comparison against the index itself.
    proxy_for: str
    region: str
    #: ⚠ None when the window is not covered on both sides. A return computed from a
    #: carried-forward value at one end is a return against a date that never happened.
    change_pct: Decimal | None
    detail: str

    model_config = ConfigDict(from_attributes=True)


class BenchmarksOut(BaseModel):
    """The book against what you could have bought instead, over the same window."""

    start: dt.date
    end: dt.date
    portfolio_pct: Decimal | None
    lines: list[BenchmarkLineOut]
    #: The book's India/US split, which is how the blend is weighted.
    weights: dict[str, Decimal]
    blended_pct: Decimal | None
    readable: bool
    detail: str
    #: The share of the book no index stands in for — crypto and funds.
    non_equity_share: Decimal
    #: ⚠ Present when the two sides of the comparison are measuring materially different
    #: things. Rendered beside the figures rather than instead of them.
    caveat: str | None


class CriterionOut(BaseModel):
    """One condition for real money, and how far off it is."""

    key: str
    question: str
    #: ⚠ null means *not yet measurable*, which is different from failing. A criterion with no
    #: sample behind it has not been failed; it has not been tested — and an interface that
    #: rendered those the same way would turn "we do not know" into "we fell short".
    met: bool | None
    value: str
    target: str
    detail: str
    n: int
    #: ⚠ Shown beside every return statistic. A number without its error bar is the mechanism
    #: by which this system would mislead its owner.
    standard_error: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class VerdictOut(BaseModel):
    """Where the whole thing stands against the six criteria committed to in advance."""

    criteria: list[CriterionOut]
    met: int
    failed: int
    untested: int
    all_met: bool
    headline: str
    generated_at: dt.datetime | None
