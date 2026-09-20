"""020 — proposals, and everything that makes one checkable afterwards

Six tables. Together they are the point of the whole module: the place where a judgement is
written down **before** anyone knows how it turned out, and can therefore be graded later
without the grading being a story.

`proposals` is what was suggested. `decisions` is what the human did about it. `claims` and
`invalidation_triggers` are the falsifiable parts — the specific things that must come true,
and the specific things that would prove the thesis wrong. `shadow_entries` tracks what did
NOT happen. `agent_runs` records every run, **including the ones that proposed nothing**.

⚠ **`price_snapshot`, `gate_results` and `input_refs` are frozen onto the proposal**, not
looked up later. What the system SAW is a different fact from what the market DID, and a
review that recomputes the inputs is reconstructing a decision rather than examining one. The
same discipline `core/pricing.py` uses to freeze model costs at write time.

⚠ **Nothing here can be edited.** Five of the six are append-only at the database. A
proposal whose thesis could be revised after the outcome is known is worth nothing for
judging yourself, and hindsight is not a thing people resist by intending to.

**Why `agent_runs` records no-ops.** A system that only logs the days it acted can never be
measured against the days it should have. "Proposed nothing" is a decision, and on most days
it is the correct one — so it has to leave a trace or the record is a highlight reel.

⚠ **`claims` is where measurement actually becomes possible.** At thirty-odd decisions a year
nothing statistical can be said about returns for years. But each thesis makes several
specific, checkable assertions, so a year produces a few hundred testable predictions rather
than thirty outcomes — which is the difference between knowing in months and knowing in
decades.

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUARD_FN = "investments_append_only"
_APPEND_ONLY = ("agent_runs", "proposals", "decisions", "claims")


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_name", sa.Text(), nullable=False),
        # Idempotency, same as the job registry: one row per occurrence, so a catch-up run
        # after a restart cannot double-write proposals.
        sa.Column("occurrence_key", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("inputs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inputs_material", sa.Integer(), nullable=False, server_default="0"),
        # ⚠ Zero is a real and frequent value. A run that proposed nothing is recorded so the
        # system can be measured against the days it should have acted and did not.
        sa.Column("proposals_emitted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_unavailable", ARRAY(sa.Text())),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status in ('OK','PARTIAL','FAILED','SKIPPED')", name="agent_runs_status"
        ),
        sa.UniqueConstraint("agent_name", "occurrence_key", name="agent_runs_occurrence"),
    )

    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # One batch per evening, so a night's suggestions are read together rather than as
        # unrelated alerts.
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id")),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_amount_inr", sa.Numeric(14, 2)),
        sa.Column("target_qty", sa.Numeric(28, 8)),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        # 0.000–1.000. Calibration — "when it says 80%, is it right 80% of the time" — is the
        # most honest thing measurable about a forecaster, and it needs this recorded.
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "framework_version_id",
            sa.Uuid(),
            sa.ForeignKey("framework_versions.id"),
            nullable=False,
        ),
        # The three scores, frozen. Never blended into one: the most valuable thing these
        # frameworks produce is "essential, excellent, and still a bad purchase today", and
        # that is precisely the finding an average destroys.
        sa.Column("ab_score", sa.Numeric(4, 2)),
        sa.Column("quality_earned", sa.Numeric(4, 2)),
        sa.Column("quality_available", sa.Numeric(4, 2)),
        sa.Column("reflexivity_flags_yes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quadrant", sa.Text()),
        # ⚠ FROZEN. What the system saw, not what the market later did.
        sa.Column("price_snapshot", JSONB(), nullable=False),
        sa.Column("input_refs", JSONB(), nullable=False),
        sa.Column("gate_results", JSONB(), nullable=False),
        sa.Column("urgency", sa.Text(), nullable=False, server_default="BATCH"),
        sa.Column("model", sa.Text()),
        sa.Column("prompt_hash", sa.Text()),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        # ⚠ Written ONCE, and only ever `PENDING` or `BLOCKED` — what the system itself
        # decided at the moment it wrote the row. What the HUMAN decided lives in `decisions`,
        # and the effective state is derived from the two.
        #
        # An editable status on an append-only table was the first shape of this and it is a
        # contradiction: the column would drift out of step with the decision record and
        # nothing could say which was right. Deriving it means they cannot disagree.
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("blocked_by", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "action in ('INITIATE','ADD','HOLD','TRIM','EXIT','ACCUMULATE_POOL')",
            name="proposals_action",
        ),
        sa.CheckConstraint("status in ('PENDING','BLOCKED')", name="proposals_status"),
        sa.CheckConstraint("urgency in ('BATCH','IMMEDIATE')", name="proposals_urgency"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="proposals_confidence"),
        sa.CheckConstraint("horizon_days > 0", name="proposals_horizon"),
        # A blocked proposal names what blocked it; nothing else carries a blocker.
        sa.CheckConstraint(
            "(status = 'BLOCKED') = (blocked_by IS NOT NULL)", name="proposals_blocked_by"
        ),
    )
    op.create_index("proposals_open", "proposals", ["portfolio_id", "status", "created_at"])
    op.create_index("proposals_by_instrument", "proposals", ["instrument_id", "created_at"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("modified_amount_inr", sa.Numeric(14, 2)),
        # ⚠ NOT NULL and deliberately so. The reason in the user's own words is the data that
        # eventually reveals what kinds of proposal keep getting turned down — which is the
        # only way the system learns anything about its own suggestions.
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("decided_via", sa.Text(), nullable=False),
        sa.Column("resulting_transaction_id", sa.Uuid(), sa.ForeignKey("transactions.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("outcome in ('APPROVE','REJECT','MODIFY')", name="decisions_outcome"),
        sa.CheckConstraint("decided_via in ('PUSH','WEB','CHAT')", name="decisions_via"),
        sa.CheckConstraint("length(btrim(reason_text)) > 0", name="decisions_reason_present"),
        sa.UniqueConstraint("proposal_id", name="decisions_one_per_proposal"),
    )

    op.create_table(
        "invalidation_triggers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        # ⚠ A number, a comparison and a deadline. Prose is refused: "if the story changes" is
        # unfalsifiable, so a position carrying it has no way of ever being wrong, which is
        # the same as having no invalidation condition at all.
        sa.Column("metric_key", sa.Text(), nullable=False),
        sa.Column("comparator", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(24, 6), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("window_until", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ARMED"),
        sa.Column("fired_at", sa.DateTime(timezone=True)),
        sa.Column("fired_evidence", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "comparator in ('LT','LTE','GT','GTE','EQ','CROSSES_BELOW','CROSSES_ABOVE')",
            name="triggers_comparator",
        ),
        sa.CheckConstraint(
            "status in ('ARMED','FIRED','EXPIRED','CLEARED','SUPERSEDED')",
            name="triggers_status",
        ),
    )
    op.create_index(
        "triggers_armed",
        "invalidation_triggers",
        ["instrument_id", "status"],
        postgresql_where=sa.text("status = 'ARMED'"),
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("metric_key", sa.Text()),
        sa.Column("comparator", sa.Text()),
        sa.Column("threshold", sa.Numeric(24, 6)),
        sa.Column("due_by", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_evidence", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status in ('OPEN','TRUE','FALSE','UNVERIFIABLE')", name="claims_status"
        ),
    )
    op.create_index("claims_due", "claims", ["status", "due_by"])

    op.create_table(
        "shadow_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("proposals.id"), nullable=False),
        # ⚠ Which book: what you vetoed, what the budget could not fund, what the rules
        # blocked. The third is the most valuable, because it is the only way to find out
        # whether the safety rails are protecting or merely obstructing.
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 6)),
        sa.Column("exit_date", sa.Date()),
        sa.Column("exit_reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "reason in ('VETOED','BUDGET_EXHAUSTED','GATE_BLOCKED')", name="shadow_reason"
        ),
        sa.UniqueConstraint("proposal_id", "portfolio_id", name="shadow_one_per_proposal"),
    )

    for table in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_GUARD_FN}();"
        )


def downgrade() -> None:
    for table in _APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.drop_table("shadow_entries")
    op.drop_index("claims_due", table_name="claims")
    op.drop_table("claims")
    op.drop_index("triggers_armed", table_name="invalidation_triggers")
    op.drop_table("invalidation_triggers")
    op.drop_table("decisions")
    op.drop_index("proposals_by_instrument", table_name="proposals")
    op.drop_index("proposals_open", table_name="proposals")
    op.drop_table("proposals")
    op.drop_table("agent_runs")
