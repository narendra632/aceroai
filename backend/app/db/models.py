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
    telegram_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True)
    timezone: Mapped[str] = mapped_column(sa.Text, default="Asia/Kolkata")
    # Model preferences (migration 003). NULL = use the server's configured default,
    # so an untouched account behaves exactly as before.
    llm_provider: Mapped[str | None] = mapped_column(sa.Text)
    model_chat: Mapped[str | None] = mapped_column(sa.Text)
    model_deep: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
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
