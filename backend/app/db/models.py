import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db.session import Base

now = sa.func.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.Text, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text)
    timezone: Mapped[str] = mapped_column(sa.Text, default="Asia/Kolkata")
    # Model preferences (migration 003). NULL = use the server's configured default,
    # so an untouched account behaves exactly as before.
    llm_provider: Mapped[str | None] = mapped_column(sa.Text)
    model_chat: Mapped[str | None] = mapped_column(sa.Text)
    model_deep: Mapped[str | None] = mapped_column(sa.Text)
    # Monthly spend ceiling in USD (migration 009). NULL = no limit, so an account that
    # never sets one behaves exactly as it did before the cap existed.
    monthly_budget_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 2))
    # Notification policy (migration 011). Local hours; NULL on either = quiet hours off.
    # A notification raised inside the window is still WRITTEN — only the push to the
    # device is suppressed, so nothing is lost, it just waits until morning.
    quiet_hours_start: Mapped[int | None] = mapped_column(sa.SmallInteger)
    quiet_hours_end: Mapped[int | None] = mapped_column(sa.SmallInteger)
    daily_push_cap: Mapped[int | None] = mapped_column(sa.SmallInteger)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    # 'telegram' is retained DELIBERATELY though the channel was retired in migration 011.
    # Sessions with this value are real conversations Narendra had; rewriting them to 'web'
    # would make the record misstate where they happened, and dropping them would destroy
    # history to tidy a constraint. Do not "clean this up".
    __table_args__ = (
        sa.CheckConstraint("channel in ('web','telegram')", name="chat_sessions_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(sa.Text)
    title: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    last_active_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
    # Soft delete (migration 004) so a deletion can be undone. Readers MUST filter on
    # this — the filter lives in services/sessions.py, never in a route.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        sa.CheckConstraint("role in ('user','assistant','system','tool')", name="messages_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(sa.Text)
    content: Mapped[str] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.Text)
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('todo','in_progress','done','dropped')", name="tasks_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text, default="todo")
    priority: Mapped[int] = mapped_column(sa.SmallInteger, default=2)  # 1 hi / 2 mid / 3 lo
    due_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    snoozed_until: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now, onupdate=now
    )
    # Soft delete (migration 004) so a deletion can be undone. Readers MUST filter on
    # this — the filter lives in services/tasks.py, never in a route or a tool.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # NOTE: urgency is derived from due_at + priority at read time. Never store it.


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    entry_date: Mapped[dt.date] = mapped_column(sa.Date)
    content: Mapped[str] = mapped_column(sa.Text)
    mood: Mapped[int | None] = mapped_column(sa.SmallInteger)  # optional 1-5
    tags: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), default=list)
    channel: Mapped[str] = mapped_column(sa.Text, default="web")
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    # Soft delete (migration 004) so a deletion can be undone. Readers MUST filter on
    # this — the filter lives in services/journal.py, never in a route or a tool.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ProfileFact(Base):
    __tablename__ = "profile_facts"
    __table_args__ = (
        sa.CheckConstraint(
            "category in ('preference','health','work','finance','relationship','other')",
            name="profile_facts_category",
        ),
        sa.CheckConstraint("source in ('stated','inferred')", name="profile_facts_source"),
        sa.CheckConstraint(
            "status in ('active','superseded','rejected')", name="profile_facts_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    fact: Mapped[str] = mapped_column(sa.Text)
    category: Mapped[str] = mapped_column(sa.Text)
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.8)
    source: Mapped[str] = mapped_column(sa.Text)
    source_ref: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    status: Mapped[str] = mapped_column(sa.Text, default="active")
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("profile_facts.id"))
    valid_from: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    # Semantic memory: fact embedding for pgvector similarity search (migration 002).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embed_dim))
    # A fact the user can edit needs to say when it last changed (migration 005).
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now, onupdate=now
    )

    # Soft delete (migration 005) so forgetting a fact can be undone. Readers MUST filter
    # this — the filter lives in services/memory.py, never in a route, a tool, or recall.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))

    # Migration 010. Set when a fact was stored despite sitting close to an existing one.
    #
    # This exists because the alternative was *deletion*. Cosine distance measures subject
    # matter, not identity: measured, "AI-901 certification" and "AI-103 certification" are
    # 0.098 apart — closer than the 0.12 dedup threshold — so the second one used to be
    # dropped. Storing it with a pointer at its suspected twin keeps the ambiguity visible
    # and correctable. `superseded_by` says "this was replaced"; this says "these two might
    # be the same and nobody has decided".
    possible_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("profile_facts.id")
    )

    @property
    def effective_confidence(self) -> float:
        """What this fact is actually worth believing.

        `confidence` stores the *model's* estimate and is never overwritten — so
        confirming a fact and later un-confirming it restores the original number
        instead of losing it. A fact the user has stated is certain by definition, which
        makes this a derived value, computed rather than stored (golden rule 2).
        """
        return 1.0 if self.source == "stated" else self.confidence


class GeneratedReview(Base):
    __tablename__ = "generated_reviews"
    __table_args__ = (
        sa.CheckConstraint("kind in ('morning','daily','weekly')", name="generated_reviews_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    period_start: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    period_end: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    content: Mapped[str] = mapped_column(sa.Text)
    delivered_to: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), default=list)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    # Soft delete (migration 012). Deleting a briefing does NOT cause it to be written again:
    # `job_runs` records what has run, and this table is only its output. Were it the other
    # way round, deleting a briefing would make Acero pay to compose a replacement.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))


class Turn(Base):
    """One model call — including the ones the user never sees (migration 007).

    A single user message can trigger four provider calls: an embedding for recall, the
    reply itself, the fact extractor, and an embedding for any new facts. Only the reply
    produces a `messages` row, so `kind` is what makes the other three attributable rather
    than invisible spend.

    Records shape, counts and durations. Never prompt or response text — `messages` already
    holds the content, and duplicating it here would double both the disk footprint and the
    blast radius of a leak.
    """

    __tablename__ = "turns"
    __table_args__ = (
        sa.CheckConstraint("kind in ('chat','memory_extract','embed','job')", name="turns_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    channel: Mapped[str | None] = mapped_column(sa.Text)
    kind: Mapped[str] = mapped_column(sa.Text)
    provider: Mapped[str | None] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.Text)
    effort: Mapped[str | None] = mapped_column(sa.Text)
    started_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    duration_ms: Mapped[int | None]
    ttft_ms: Mapped[int | None]
    rounds: Mapped[int | None] = mapped_column(sa.SmallInteger)
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    tokens_thinking: Mapped[int | None]
    tokens_cached: Mapped[int | None]
    # NULL = no price known for this model. Never 0 — a zero is a lie that silently
    # understates the total, while a gap is visible and gets fixed.
    cost_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6))
    # Which price list produced cost_usd, so any figure on screen can be explained.
    pricing_version: Mapped[str | None] = mapped_column(sa.Text)
    ok: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    error_type: Mapped[str | None] = mapped_column(sa.Text)


class Span(Base):
    """One stage within a turn — what draws the per-turn waterfall (migration 007)."""

    __tablename__ = "spans"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    turn_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("turns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(sa.Text)
    seq: Mapped[int] = mapped_column(sa.SmallInteger)
    duration_ms: Mapped[int | None]
    # Counts and identifiers only, never message text.
    meta: Mapped[dict | None] = mapped_column(JSONB)


class DailyUsage(Base):
    """One day of spend, rolled up and kept forever (migration 008).

    `turns` and `spans` are written on every model call and would grow without bound on a
    host with 10 GB of disk. They are pruned; this table is what survives, so "what did I
    spend in March" stays answerable long after the individual calls behind it are gone.

    A day is bucketed in `settings.app_timezone`, not UTC, because that is the day the
    Insights page draws. Rolling up in UTC and displaying in Asia/Kolkata would shift every
    bucket by five and a half hours — the totals would be right and every daily figure
    wrong.

    `provider` and `model` are NOT NULL, with unknowns coalesced to a literal. Postgres
    treats NULLs as distinct in a unique constraint, so a nullable key column would let the
    same day be inserted repeatedly instead of updated.
    """

    __tablename__ = "daily_usage"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "day", "kind", "provider", "model", name="daily_usage_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    day: Mapped[dt.date] = mapped_column(sa.Date)
    kind: Mapped[str] = mapped_column(sa.Text)
    provider: Mapped[str] = mapped_column(sa.Text)
    model: Mapped[str] = mapped_column(sa.Text)
    calls: Mapped[int]
    failed: Mapped[int]
    # Calls whose model had no known price, so a total can say how complete it is rather
    # than quietly understating itself — the same reason `turns.cost_usd` is nullable.
    unpriced: Mapped[int]
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(12, 6))
    tokens_in: Mapped[int]
    tokens_out: Mapped[int]
    tokens_thinking: Mapped[int]


class JobRun(Base):
    """One attempted execution of a scheduled job (migration 011).

    This table — not the scheduler — is the source of truth about whether a job has run.
    APScheduler holds exactly one job (a five-minute tick) and forgets everything on
    restart; a deploy at 20:58 would otherwise kill the 21:00 summary and report nothing.

    `occurrence_key` is the scheduled instant the run satisfies, as an ISO string in local
    time. Together with `job_name` it is unique, which is what makes exactly-once a
    *database* guarantee rather than something the runner has to be careful about.

    `status` distinguishes six outcomes, and the distinction is the point. `silent` means
    the job ran and correctly had nothing to say — `task_nudge` does this twelve times a
    day — which must be readable at a glance as success, not mistaken for a failure or for
    a run that never happened.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        sa.UniqueConstraint("job_name", "occurrence_key", name="job_runs_occurrence"),
        sa.CheckConstraint(
            "status in ('ok','silent','failed','skipped_budget','skipped_disabled','missed')",
            name="job_runs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(sa.Text)
    occurrence_key: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    duration_ms: Mapped[int | None]
    error_type: Mapped[str | None] = mapped_column(sa.Text)
    # Counts and identifiers only, never message text — the same rule as `spans.meta`.
    detail: Mapped[dict | None] = mapped_column(JSONB)


class Notification(Base):
    """Something the system decided to tell the user (migration 011).

    A notification is a ROW; push is one way of drawing attention to it. The row is written
    *before* any delivery is attempted, so what Acero had to say survives a refused
    permission, a closed laptop, a dead subscription, and a notification swiped off a
    lockscreen while walking.

    That ordering is the whole design. A system whose only memory of "two tasks are overdue"
    is an OS toast you dismissed is not a system that reduces what you have to remember.

    `pushed_at` NULL means it never reached a device — which is information, not a failure:
    quiet hours, the daily cap, no subscription, or a send that did not succeed.

    ⚠ Since migration 013 `pushed_at` is when it was **last** delivered, not when it was
    delivered. A record can be delivered repeatedly: the overdue nudge reminds the user every
    two hours against one record per day rather than writing a record per reminder.
    `push_count` is how many times that happened, and it — not the number of rows — is what
    "how often have I been interrupted today" means.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    title: Mapped[str] = mapped_column(sa.Text)
    body: Mapped[str] = mapped_column(sa.Text)
    # An in-app route, so selecting the notification lands on what it is about.
    url: Mapped[str | None] = mapped_column(sa.Text)
    # Groups notifications that replace one another on the device rather than stacking.
    tag: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    read_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # When it was LAST delivered (migration 013), not when it was delivered.
    pushed_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Deliveries, not records (migration 013). Starts at zero and is incremented by the code
    # that actually delivers — a row is written BEFORE delivery is attempted, so a default of
    # 1 would claim an interruption that may never happen.
    push_count: Mapped[int] = mapped_column(sa.Integer, server_default="0", default=0)
    # ⚠ Soft delete (migration 012), with an exception found nowhere else in this file.
    #
    # Readers that LIST rows filter `deleted_at IS NULL`, as everywhere. But two readers ask
    # what has already HAPPENED, and they must not:
    #
    #   `already_said()` — filter it and dismissing a nudge makes the next run re-push it,
    #                      because the evidence that it was said is what the filter hides.
    #   `pushed_today()` — a count of deliveries is a count of deliveries, not of surviving
    #                      receipts.
    #
    # Making this file consistent with itself would break both. See services/notifications.py.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))


class PushSubscription(Base):
    """A browser that has agreed to receive notifications (migration 011).

    What the browser's push service hands us: an endpoint URL plus two keys used to encrypt
    the payload. The content is encrypted end to end, so the push service relays it and
    cannot read it.

    `endpoint` is unique because re-subscribing the same browser must UPDATE this row.
    Subscriptions also die — a push service returns 404/410 when a browser is uninstalled or
    its storage is cleared — and a dead endpoint must be DELETED rather than retried, or
    every job pays for it forever.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    endpoint: Mapped[str] = mapped_column(sa.Text, unique=True)
    p256dh: Mapped[str] = mapped_column(sa.Text)
    auth: Mapped[str] = mapped_column(sa.Text)
    # Only so the user can tell two devices apart in Settings.
    user_agent: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
    last_ok_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text)


class UserJobPref(Base):
    """Whether one user wants one job to run (migration 011).

    Deliberately SPARSE: no row means "use the job's declared default". That is not a
    space optimisation — it is what makes adding a future job a code change with no
    migration, no backfill, and no per-user default row behind it, which was an explicit
    requirement of this change rather than a happy accident.
    """

    __tablename__ = "user_job_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    job_name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean)
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now, onupdate=now
    )


# --- the investment ledger (migration 014) -------------------------------------------
#
# ⚠ `Transaction`, `PriceObservation` and `FxObservation` are APPEND-ONLY, enforced by a
# database trigger. This is the ONE place in this project where convention 6 — soft delete
# with an undo toast — is deliberately not followed, and the reason is what the record is
# for. Everywhere else a deletion is a user changing their mind about something they wrote.
# Here the record exists to be judged against months later: what did I own in March, and
# what did I believe when I bought it? A row that can be edited afterwards leaves that
# question with no stable answer, and every review built on it becomes a story rather than a
# measurement.
#
# So a sale is an EVENT and a mistake is a COUNTER-EVENT carrying `supersedes_id`, exactly
# as a paper ledger works. The interface still offers undo; it inserts the reversing row.


class Instrument(Base):
    """Something that can be held. Created by recording a holding, never separately.

    There is deliberately no "add to watchlist" action: a tracked set maintained apart from
    holdings is a tracked set that will disagree with them, and the disagreement surfaces as
    a filing nobody was watching.
    """

    __tablename__ = "instruments"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(sa.Text)
    exchange: Mapped[str] = mapped_column(sa.Text)
    isin: Mapped[str | None] = mapped_column(sa.Text)
    amfi_scheme_code: Mapped[str | None] = mapped_column(sa.Text)
    #: Angel One's numeric instrument ID — the same number as `FinInstrmId` in NSE's bhavcopy,
    #: which is where it is read from. Migration 016.
    angel_token: Mapped[str | None] = mapped_column(sa.Text)
    #: CoinGecko's slug ("bitcoin"). A ticker is not unique across coins; this is.
    coingecko_id: Mapped[str | None] = mapped_column(sa.Text)
    name: Mapped[str] = mapped_column(sa.Text)
    asset_class: Mapped[str] = mapped_column(sa.Text)
    currency: Mapped[str] = mapped_column(sa.Text)
    sector: Mapped[str | None] = mapped_column(sa.Text)
    is_tracked: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    #: Renames happen. HDFC Mid-Cap Opportunities Fund became HDFC Mid Cap Fund under SEBI's
    #: naming standardisation, same ISIN — without both names an AMFI lookup looks broken.
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Portfolio(Base):
    """A book of holdings.

    `REAL` is what the user actually holds. `MIRROR` is what the system's own approved
    decisions produce, and stays empty until proposals exist.

    ⚠ They are **not nested**. The user holds things the system never suggested, and the
    system suggests things the user does not act on. The difference between the two books is
    the measurement this whole module exists to produce, and a single combined book would
    destroy it.
    """

    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(sa.Text)
    kind: Mapped[str] = mapped_column(sa.Text)
    base_currency: Mapped[str] = mapped_column(sa.Text, default="INR")
    mode: Mapped[str] = mapped_column(sa.Text, default="BALANCED")
    monthly_budget_inr: Mapped[Decimal] = mapped_column(sa.Numeric(14, 2), default=Decimal(30000))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class ChargeSchedule(Base):
    """The transaction-cost rates in force from a date.

    Frozen onto each transaction when it is recorded, exactly as `core/pricing.py` freezes
    model prices — because rates change, and recomputing March's charges at October's rates
    would silently rewrite March's return.
    """

    __tablename__ = "charge_schedules"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.Text)
    venue: Mapped[str] = mapped_column(sa.Text)
    effective_from: Mapped[dt.date] = mapped_column(sa.Date)
    spec: Mapped[dict] = mapped_column(JSONB)
    source_note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Transaction(Base):
    """One thing that happened to the book. **APPEND-ONLY — see the note above.**"""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("portfolios.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    txn_type: Mapped[str] = mapped_column(sa.Text)
    trade_date: Mapped[dt.date] = mapped_column(sa.Date)
    quantity: Mapped[Decimal] = mapped_column(sa.Numeric(28, 8))
    price: Mapped[Decimal] = mapped_column(sa.Numeric(20, 6))
    currency: Mapped[str] = mapped_column(sa.Text)
    #: Stored per transaction, never looked up later — the rate at the moment money moved is
    #: a fact about that moment, and currency decomposition depends on it. 1.0 for INR.
    fx_rate_inr: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8), default=Decimal(1))
    charges_inr: Mapped[Decimal] = mapped_column(sa.Numeric(18, 2), default=Decimal(0))
    charge_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("charge_schedules.id")
    )
    #: ⚠ NOT a cost. Crypto TDS and LRS TCS are withheld against a future liability and are
    #: creditable or refundable — booking them as expense would understate returns AND
    #: double-count against the flat 30% VDA rate. Kept visible, kept out of `charges_inr`.
    prepaid_tax_inr: Mapped[Decimal] = mapped_column(sa.Numeric(18, 2), default=Decimal(0))
    entry_source: Mapped[str] = mapped_column(sa.Text)
    entry_ref: Mapped[str | None] = mapped_column(sa.Text)
    note: Mapped[str | None] = mapped_column(sa.Text)
    #: The correction mechanism. A row pointing at another retires it; readers resolve to
    #: rows nothing supersedes.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("transactions.id"))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class PriceObservation(Base):
    """What something was worth, according to someone, at a moment. **APPEND-ONLY.**

    `source` is the column that makes a typed price and a fetched price the same kind of
    fact. It is what lets the whole valuation and staleness machinery be built and proven
    before any market-data feed exists.
    """

    __tablename__ = "price_observations"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("instruments.id"), primary_key=True
    )
    observed_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    price: Mapped[Decimal] = mapped_column(sa.Numeric(20, 6))
    currency: Mapped[str] = mapped_column(sa.Text)
    quality: Mapped[str] = mapped_column(sa.Text, default="OK")
    quarantine_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class FxObservation(Base):
    """An exchange rate at a moment. **APPEND-ONLY.**"""

    __tablename__ = "fx_observations"

    pair: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    observed_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class CorporateAction(Base):
    """A split, bonus or similar, announced by the exchange (migration 017).

    ⚠ **Not append-only, unlike the three tables above it, and the difference is the point.**
    A transaction is an event and never changes. An action is a thing being *tracked*: it
    arrives PENDING, and becomes APPLIED, IGNORED or NEEDS_REVIEW as it is dealt with. What
    it did to the book is still an event — that is a row in `transactions`, and
    `applied_txn_id` points at it.

    While one is PENDING or NEEDS_REVIEW the holding's profit and loss is not reliable, and
    the page says so. That is the whole reason the row exists rather than a notification: a
    notification can be dismissed, and the number it was warning about stays on the screen.
    """

    __tablename__ = "corporate_actions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    action_type: Mapped[str] = mapped_column(sa.Text)
    #: NSE announces some actions before fixing the ex-date. Undated ones are recorded and
    #: flagged, and never applied on a schedule.
    ex_date: Mapped[dt.date | None] = mapped_column(sa.Date)
    #: The multiplier as an exact fraction: 2/1 for a 1:1 bonus, 10/1 for a ₹10→₹1 split.
    #: Integers rather than a decimal because 1/3 has no exact decimal form.
    ratio_num: Mapped[int | None] = mapped_column(sa.Integer)
    ratio_den: Mapped[int | None] = mapped_column(sa.Integer)
    amount_per_share: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 6))
    announced_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    source: Mapped[str] = mapped_column(sa.Text)
    #: The feed's own words, verbatim — what a person reads when the ratio could not be
    #: parsed, and the provenance for whatever was applied.
    purpose: Mapped[str] = mapped_column(sa.Text)
    dedupe_key: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text, default="PENDING")
    applied_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    applied_txn_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("transactions.id"))
    note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class FrameworkVersion(Base):
    """The theory, frozen at a version (migration 018).

    Holds the ten imperatives, the bottlenecks and what each one blocks, the fair multiple per
    sector, and the scoring weights — all in `spec`.

    ⚠ Every score and every proposal carries the version that produced it. That is what makes
    it possible to improve the framework without corrupting the record: a review can always
    ask "under which rules was this decided?", and changing a weight never silently rewrites
    the history of decisions made under the old one.

    `approved_at IS NULL` means the version is a **proposal**. A newly suggested bottleneck
    lands in one, and nothing scores against it until a person agrees.
    """

    __tablename__ = "framework_versions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    #: india_ab · buffett_soros · gates — versioned independently, so a change to one does
    #: not reset the comparability of decisions made under the others.
    family: Mapped[str] = mapped_column(sa.Text)
    version: Mapped[int] = mapped_column(sa.Integer)
    spec: Mapped[dict] = mapped_column(JSONB)
    effective_from: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    approved_note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class AbMapping(Base):
    """Where one company sits in the framework (migration 018).

    ⚠ **A row with `approved_at IS NULL` scores ZERO.** This is the guard the whole structural
    score rests on: a model may *propose* that a company solves a national bottleneck, and the
    claim is worth nothing until a person agrees with it. Without it, a system that reads
    enough news will eventually narrate an unrelated small-cap into strategic importance, and
    the score would have no way to tell that apart from the real thing.

    Kept out of `framework_versions.spec` deliberately. Companies are added often; the theory
    changes rarely. Folding them together would make adding a watchlist name look like a new
    epoch of the framework, and every past decision would appear to have been made under
    different rules.
    """

    __tablename__ = "ab_mappings"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    a_imperatives: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    b_bottleneck: Mapped[str | None] = mapped_column(sa.Text)
    crosses_a_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    #: ⚠ Where the count came from. `CONFIRMED` is stated in the framework; `PARTIAL` means
    #: "at least this many, and the rest was never established" — it scores on what is known
    #: and the interface calls the figure a floor. A gap in the notes is not a finding, and
    #: scoring one as though it were would mark a company weak for a documentation reason.
    crossings_status: Mapped[str] = mapped_column(sa.Text, default="PARTIAL")
    is_crisis_accelerated: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    inflection_quarter: Mapped[str | None] = mapped_column(sa.Text)
    investability: Mapped[str | None] = mapped_column(sa.Text)
    rationale: Mapped[str | None] = mapped_column(sa.Text)
    proposed_by: Mapped[str] = mapped_column(sa.Text)
    approved_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    approved_note: Mapped[str | None] = mapped_column(sa.Text)
    #: A mapping is a judgement about what a company does *today*. Businesses change, so the
    #: judgement expires and is re-proposed rather than standing for ever.
    review_after: Mapped[dt.date | None] = mapped_column(sa.Date)
    #: ⚠ Outside the framework by construction — a non-Indian company, or one the user has
    #: called off-thesis. The framework asks what INDIA must build, so no imperative applies
    #: to SpaceX. Scored differently rather than scored badly.
    off_framework: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    framework_version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("framework_versions.id"))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("ab_mappings.id"))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
