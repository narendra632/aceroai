import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

now = sa.func.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.Text, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text)
    telegram_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True)
    timezone: Mapped[str] = mapped_column(sa.Text, default="Asia/Kolkata")
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
    # Phase 2 migration adds: embedding vector(N) + HNSW index


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
