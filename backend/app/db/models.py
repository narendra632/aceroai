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
    pushed_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))


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
