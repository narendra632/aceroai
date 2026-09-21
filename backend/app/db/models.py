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
    """Something the portfolio has an opinion about — held, or watched and waiting.

    ⚠ **`is_tracked` is a spending decision, not a label.** A tracked instrument is priced
    every day, has its filings pulled and is scored; an untracked one costs nothing. That is
    why a company merely *named* by a source is a `Candidate` against the exchange's listed
    list rather than an instrument — pricing every name anyone ever mentioned would spend the
    API allowance and the disk budget on companies nobody has decided to care about.

    Promotion is the moment the meter starts, and it is deliberate: from the research queue,
    or by asking for it directly. An earlier version of this docstring claimed there was
    "deliberately no add-to-watchlist action", which was wrong on its own terms — the seed
    script has always maintained a watchlist by hand, and without one the system can only
    ever say hold, trim or sell.
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

    Six kinds, and each answers a question the others cannot:

    * `REAL` — what the user actually holds. Their word, never written by a machine.
    * `MIRROR` — seeded with the real holdings, then the system's approved decisions on top.
      *What would my portfolio look like if I had followed Acero from here.*
    * `AI_CLEAN` — from nothing, only those decisions. *What has Acero itself produced.*
    * `PROPOSED_ALL` — every buy ever suggested, equally weighted, never sold. If the real
      book cannot beat this, the system has ideas but no timing.
    * `SHADOW_*` — what did NOT happen: vetoed, unfunded, or refused by the rules.

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


class SourceItem(Base):
    """One document the system has read, and the words it took its figures from (019).

    ⚠ **APPEND-ONLY, and the excerpt is why this table exists.** The rule the module rests on
    is that a model never produces a number: every figure is looked up from a record and
    checked back against that record's own words, character by character. That check needs the
    words. Storing the parsed figure alone leaves the validator comparing a number with
    itself, which validates nothing.

    The document itself is NOT stored. Filings run to 200 KB and the module has a hard disk
    budget; the file is parsed in memory and discarded, and the ~15 tagged lines the figures
    came from fit the 2 KB cap with room to spare.

    A company revising its results arrives as a NEW row whose figures supersede the old ones.
    """

    __tablename__ = "source_items"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(sa.Text)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("instruments.id"))
    #: Which registered source produced this. ⚠ Nullable, because the filings ingested before
    #: the source register existed have none — and inventing one would be a lie about
    #: provenance in the one table whose entire purpose is provenance.
    source_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("sources.id"))
    source: Mapped[str] = mapped_column(sa.Text)
    external_id: Mapped[str] = mapped_column(sa.Text)
    url: Mapped[str | None] = mapped_column(sa.Text)
    title: Mapped[str | None] = mapped_column(sa.Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    fetched_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(sa.Text)
    #: ⚠ Capped at 2 KB by a database CHECK, not by the code that writes it. A cap the
    #: application promises to honour is a cap a later writer forgets.
    excerpt: Mapped[str] = mapped_column(sa.Text)
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Fundamental(Base):
    """One figure a company reported, for one period. **APPEND-ONLY** (019).

    Keyed on `(instrument, period, metric, source_item)` rather than a uuid so that re-parsing
    the same filing writes the identical rows and the insert does nothing — the sync job is
    safe to run as often as it likes.

    ⚠ `consolidated` travels with every figure. Consolidated covers subsidiaries and
    standalone does not; comparing one year's consolidated revenue with another's standalone
    is a silent apples-to-oranges error, and GE Vernova files only standalone because it has
    no subsidiaries at all.
    """

    __tablename__ = "fundamentals"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("instruments.id"), primary_key=True
    )
    #: `FY26` or `FY26Q1` — what the figure DESCRIBES, never when it was filed.
    fiscal_period: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    metric_key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("source_items.id"), primary_key=True
    )
    value: Mapped[Decimal] = mapped_column(sa.Numeric(24, 6))
    unit: Mapped[str] = mapped_column(sa.Text)
    period_end: Mapped[dt.date] = mapped_column(sa.Date)
    consolidated: Mapped[bool] = mapped_column(sa.Boolean)
    taxonomy: Mapped[str] = mapped_column(sa.Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("source_items.id"))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class AgentRun(Base):
    """One run of a thinking job. **APPEND-ONLY** (020).

    ⚠ Written even when the run proposed nothing, which on most days is the correct outcome.
    A system that only logs the days it acted can never be measured against the days it should
    have acted and did not — the record becomes a highlight reel rather than evidence.
    """

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(sa.Text)
    occurrence_key: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    status: Mapped[str] = mapped_column(sa.Text)
    inputs_seen: Mapped[int] = mapped_column(sa.Integer, default=0)
    inputs_material: Mapped[int] = mapped_column(sa.Integer, default=0)
    proposals_emitted: Mapped[int] = mapped_column(sa.Integer, default=0)
    sources_unavailable: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text))
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6), default=Decimal(0))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Proposal(Base):
    """A suggested action, frozen with everything that produced it. **APPEND-ONLY** (020).

    ⚠ `status` is written ONCE and is only ever `PENDING` or `BLOCKED` — what the system
    itself decided as it wrote the row. What the HUMAN decided lives in `decisions`, and the
    effective state is derived from the two. An editable status on an append-only table is a
    contradiction: it would drift out of step with the decision record and nothing could say
    which of the two was right.

    ⚠ `price_snapshot`, `input_refs` and `gate_results` are FROZEN. What the system saw is a
    different fact from what the market later did, and a review that recomputes the inputs is
    reconstructing a decision rather than examining one.
    """

    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("agent_runs.id"))
    portfolio_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("portfolios.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    action: Mapped[str] = mapped_column(sa.Text)
    target_amount_inr: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    target_qty: Mapped[Decimal | None] = mapped_column(sa.Numeric(28, 8))
    horizon_days: Mapped[int] = mapped_column(sa.Integer)
    thesis: Mapped[str] = mapped_column(sa.Text)
    confidence: Mapped[Decimal] = mapped_column(sa.Numeric(4, 3))
    framework_version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("framework_versions.id"))
    #: ⚠ Three scores, never blended. The most valuable finding these frameworks produce is
    #: "essential, excellent, and still a bad purchase today" — which an average destroys.
    ab_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    quality_earned: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    quality_available: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    reflexivity_flags_yes: Mapped[int] = mapped_column(sa.Integer, default=0)
    quadrant: Mapped[str | None] = mapped_column(sa.Text)
    price_snapshot: Mapped[dict] = mapped_column(JSONB)
    input_refs: Mapped[dict] = mapped_column(JSONB)
    gate_results: Mapped[dict] = mapped_column(JSONB)
    urgency: Mapped[str] = mapped_column(sa.Text, default="BATCH")
    model: Mapped[str | None] = mapped_column(sa.Text)
    prompt_hash: Mapped[str | None] = mapped_column(sa.Text)
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6), default=Decimal(0))
    status: Mapped[str] = mapped_column(sa.Text, default="PENDING")
    blocked_by: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Decision(Base):
    """What the human did about a proposal. **APPEND-ONLY** (020).

    ⚠ `reason_text` is NOT NULL on purpose. The reason in the user's own words is the data
    that eventually reveals what kinds of proposal keep being turned down — which is the only
    route by which the system learns anything about its own suggestions.
    """

    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("proposals.id"))
    decided_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(sa.Text)
    modified_amount_inr: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2))
    reason_text: Mapped[str] = mapped_column(sa.Text)
    decided_via: Mapped[str] = mapped_column(sa.Text)
    resulting_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("transactions.id")
    )
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class InvalidationTrigger(Base):
    """What would prove the thesis wrong, stated before the outcome is known (020).

    ⚠ A number, a comparison and a deadline — never prose. "If the story changes" cannot be
    checked, so a position carrying it has no way of ever being wrong, which is the same as
    carrying no invalidation condition at all.

    Mutable in `status` alone: a trigger arms, then fires, expires or is cleared.
    """

    __tablename__ = "invalidation_triggers"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("proposals.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    metric_key: Mapped[str] = mapped_column(sa.Text)
    comparator: Mapped[str] = mapped_column(sa.Text)
    threshold: Mapped[Decimal] = mapped_column(sa.Numeric(24, 6))
    unit: Mapped[str] = mapped_column(sa.Text)
    window_until: Mapped[dt.date] = mapped_column(sa.Date)
    description: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text, default="ARMED")
    fired_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    fired_evidence: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Claim(Base):
    """One falsifiable assertion a thesis made. **APPEND-ONLY** (020).

    ⚠ This is where measuring the system becomes possible at all. Thirty-odd decisions a year
    can say nothing statistical about returns for years — but each thesis makes several
    specific, checkable assertions, so a year produces a few hundred testable predictions
    instead of thirty outcomes. That is the difference between knowing in months and knowing
    in decades.
    """

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("proposals.id"))
    claim_text: Mapped[str] = mapped_column(sa.Text)
    metric_key: Mapped[str | None] = mapped_column(sa.Text)
    comparator: Mapped[str | None] = mapped_column(sa.Text)
    threshold: Mapped[Decimal | None] = mapped_column(sa.Numeric(24, 6))
    due_by: Mapped[dt.date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.Text, default="OPEN")
    resolved_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolved_evidence: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class ShadowEntry(Base):
    """A decision that did NOT happen, tracked with identical arithmetic (020).

    Three books, and the third is the valuable one: what the user vetoed, what the budget
    could not fund, and what the rules blocked. Only the last can answer whether the safety
    rails are protecting or merely obstructing.

    ⚠ Read in aggregate, on a schedule — never dipped into after a name that got away. A
    rejected idea that went up is far more memorable than a rejected idea that went down, and
    a shadow book read casually trains worse judgement rather than better.
    """

    __tablename__ = "shadow_entries"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("portfolios.id"))
    proposal_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("proposals.id"))
    reason: Mapped[str] = mapped_column(sa.Text)
    entry_price: Mapped[Decimal] = mapped_column(sa.Numeric(20, 6))
    entry_date: Mapped[dt.date] = mapped_column(sa.Date)
    quantity: Mapped[Decimal] = mapped_column(sa.Numeric(28, 8))
    exit_price: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 6))
    exit_date: Mapped[dt.date | None] = mapped_column(sa.Date)
    exit_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class FrameworkScore(Base):
    """What a company scored, on a day, under the rules in force then. **APPEND-ONLY** (022).

    ⚠ A score is a judgement made at a moment with the data available then. Recomputing it
    later with today's figures silently rewrites history — a company that scored 4 in March and
    8 in September would read as 8 for both, and the improvement, which is the most interesting
    thing about it, would be invisible.

    ⚠ The three scores sit side by side and are never summed. A company can be structurally
    essential, genuinely excellent, and still a bad purchase today; that is the finding an
    average destroys, and it is the main reason these frameworks are held together.

    One row per company per day, written only when something CHANGED. Eleven identical rows
    every evening would turn a history worth reading into a log.
    """

    __tablename__ = "framework_scores"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("instruments.id"))
    scored_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    #: The day the score DESCRIBES, distinct from when it was taken. A catch-up run on Monday
    #: scoring Friday's facts is recording a fact about Friday.
    as_of: Mapped[dt.date] = mapped_column(sa.Date)
    framework_version_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("framework_versions.id"))
    ab_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    ab_components: Mapped[dict | None] = mapped_column(JSONB)
    quality_earned: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    quality_available: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 2))
    quality_components: Mapped[dict | None] = mapped_column(JSONB)
    flags_yes: Mapped[int] = mapped_column(sa.Integer, default=0)
    flags: Mapped[dict | None] = mapped_column(JSONB)
    quadrant: Mapped[str | None] = mapped_column(sa.Text)
    price: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 6))
    years_read: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Source(Base):
    """A place the system reads from (023).

    ⚠ `trust_tier` is load-bearing rather than descriptive. Tier 1 is a filing or a regulator,
    tier 2 the press, tier 3 commentary — and a proposal resting *only* on tier 3 fails its
    sourcing gate. A stock named on a channel joins the research queue; it does not join the
    portfolio, however persuasive the argument was.

    ⚠ Approved like a framework mapping, and for the same reason: adding a source changes what
    the system reads and therefore what it can be talked into. That is a decision, not a
    setting.

    Soft-deleted rather than removed. A source that could only be deleted would orphan every
    mention that ever cited it, and quietly rewrite the attribution history along with it.
    """

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(sa.Text)
    name: Mapped[str] = mapped_column(sa.Text)
    #: A channel id, a feed URL, a filer id — whatever its own system calls it.
    handle: Mapped[str] = mapped_column(sa.Text)
    trust_tier: Mapped[int] = mapped_column(sa.Integer)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(sa.Text)
    last_polled_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Mention(Base):
    """Every instrument every source has ever named. **APPEND-ONLY** (023).

    ⚠ **Every** one — acted on or not, held or not, dismissed or not. That clause is the whole
    reason this table exists.

    Judge a channel only on the ideas you acted on and you are measuring your own filter rather
    than the channel: the ideas you skipped are missing from the denominator, so a source that
    named forty companies of which you looked at three and one worked reads as 33% instead of
    2.5%. That is not a subtle bias — it is the difference between a source looking excellent
    and looking useless. And it cannot be reconstructed afterwards, which is why the row is
    written at the moment the thing is said.

    `became_proposal_id` is usually NULL, and the rows carrying nothing there are the point.

    ⚠ Append-only in the **utterance** — instrument, stance and words — and not in what came
    of it. `became_proposal_id` is set later, by a database trigger narrowed the same way 021
    had to narrow `claims`: what was said cannot be unsaid, but what it led to is a fact
    discovered afterwards about an utterance that has not moved. DELETE is refused outright.
    """

    __tablename__ = "mentions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("source_items.id"))
    #: ⚠ Exactly ONE of these two, insisted on by a database CHECK (024). A mention is about a
    #: company; sometimes that company is one the portfolio follows and sometimes it is merely
    #: listed on the exchange. 023 wrote `instrument_id NOT NULL`, which quietly assumed every
    #: company anyone names is one you already own — the same assumption that made discovery
    #: impossible in the first place.
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("instruments.id"))
    listed_company_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("listed_companies.id")
    )
    stance: Mapped[str] = mapped_column(sa.Text)
    claim_excerpt: Mapped[str | None] = mapped_column(sa.Text)
    became_proposal_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("proposals.id"))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class ListedCompany(Base):
    """One company on the exchange's own equity list (024).

    ⚠ **The vocabulary the reader recognises names with**, and the reason discovery does not
    need a model to produce names. A model that can generate company names can generate ones
    that do not exist, and a fictional company written into `mentions` is indistinguishable
    from a real one once there — in the very table the source-attribution measure counts. With
    the exchange's list as the vocabulary, recognising a company never heard of is exactly as
    deterministic as recognising one already held.

    ⚠ This is a fact about the exchange, not about the portfolio. Being listed says nothing
    about being worth owning, and nothing here scores or filters.

    A delisting is recorded, never deleted: the company was still named by sources while it
    was listed, and removing it would make those mentions unresolvable.
    """

    __tablename__ = "listed_companies"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(sa.Text)
    exchange: Mapped[str] = mapped_column(sa.Text, default="NSE")
    name: Mapped[str] = mapped_column(sa.Text)
    series: Mapped[str | None] = mapped_column(sa.Text)
    isin: Mapped[str | None] = mapped_column(sa.Text)
    listed_on: Mapped[dt.date | None] = mapped_column(sa.Date)
    delisted_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    refreshed_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))


class Candidate(Base):
    """A company something named, not held and not watched, waiting to be looked at (024).

    The research queue. Without it the system can only ever say hold, trim or sell — a
    research analyst that can only comment on what you already own is a bookkeeper with
    opinions.

    ⚠ **A candidate is deliberately not priced.** Pricing every name ever mentioned would
    spend the API allowance and the disk budget on companies nobody has decided to care
    about. It has an identity so it can be referenced and counted; promoting it is what starts
    the meter, and `instrument_id` stays NULL until then.

    ⚠ `best_trust_tier` is the best tier that has **ever** named it, not the latest and not
    the worst. A company named once by a filing and ten times by commentary is a filing-grade
    lead, and tier is what the sourcing gate reads.

    ⚠ `dismissed_reason` is required by a database CHECK, not by politeness. It is the only
    record of what kinds of idea keep being refused, and a queue that could be cleared
    silently would discard that every time it was tidied.
    """

    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    listed_company_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("listed_companies.id"))
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("instruments.id"))
    status: Mapped[str] = mapped_column(sa.Text, default="QUEUED")
    first_mention_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("mentions.id"))
    first_seen_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    mention_count: Mapped[int] = mapped_column(sa.Integer, default=1)
    best_trust_tier: Mapped[int] = mapped_column(sa.Integer, default=3)
    #: Proposed by the system, approved by a person — exactly like an `AbMapping`.
    proposed_bottleneck: Mapped[str | None] = mapped_column(sa.Text)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    dismissed_reason: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Review(Base):
    """What was true at the end of a week, a month or a quarter (025).

    The artefact actually worth reading. The daily notifications are operational; this is
    where the thinking accumulates.

    ⚠ **APPEND-ONLY, for the reason `framework_scores` is.** A review states what was true at
    a moment, with the data available then. Regenerating March's review in June with June's
    figures would show a position that recovered as never having fallen, and a prediction that
    failed as never having been made. The most interesting thing a review can hold is the part
    that turned out to be wrong — and a review that can be rewritten cannot hold it.

    ⚠ **`content` is facts, and no model writes it.** Everywhere else in this module a model
    is forbidden from producing a number; a review is almost entirely numbers, so it is
    assembled by code from records that already exist. A prose summary would be the one place
    a figure could be restated wrongly with nothing to check it against.
    """

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    period_start: Mapped[dt.date] = mapped_column(sa.Date)
    period_end: Mapped[dt.date] = mapped_column(sa.Date)
    generated_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    content: Mapped[dict] = mapped_column(JSONB)
    #: One line, for the notification and the list — composed from the same facts.
    headline: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class Benchmark(Base):
    """What you could have bought instead (026).

    ⚠ **An index FUND, not an index.** A total-return index is the right idea — the headline
    price index understates the real alternative by roughly the dividend yield — but an index
    cannot be bought. A fund's NAV is a total-return series by construction and is what was
    actually available instead; it differs by the expense ratio and tracking error, both of
    which are costs a real alternative would have charged. `proxy_for` says so in the
    interface, because a benchmark that is a proxy has to announce it.
    """

    __tablename__ = "benchmarks"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(sa.Text)
    name: Mapped[str] = mapped_column(sa.Text)
    proxy_for: Mapped[str] = mapped_column(sa.Text)
    source: Mapped[str] = mapped_column(sa.Text)
    external_id: Mapped[str] = mapped_column(sa.Text)
    #: IN or US — so a blended comparison can weight by the book's actual split.
    region: Mapped[str] = mapped_column(sa.Text)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)


class BenchmarkValue(Base):
    """One day of a benchmark. **APPEND-ONLY** (026).

    ⚠ A benchmark whose past could be restated is a benchmark that can be moved under a result.
    """

    __tablename__ = "benchmark_values"

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("benchmarks.id"), primary_key=True
    )
    on_day: Mapped[dt.date] = mapped_column(sa.Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(sa.Numeric(20, 6))
    created_at: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), server_default=now)
