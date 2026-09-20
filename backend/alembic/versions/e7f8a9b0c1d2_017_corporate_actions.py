"""017 — corporate actions, stored rather than only announced

A 1:1 bonus halves the quoted price overnight. Unhandled, the page reports a 50% loss on a
holding that lost nothing — the one failure mode of this module that produces a large,
alarming, entirely fictional number, and the one most likely to be acted on.

Until now the exchange feed was read and a notification sent, and nothing was written down.
That leaves three gaps this table closes:

* **Nothing remembers.** The same announcement is re-read every evening and suppressed only
  by a notification's tag. Delete the notification and it is announced again; miss it and
  there is no record it was ever seen.
* **Nothing can be applied.** The quantity change has to be typed by hand, from a feed
  string, into a form — at exactly the moment the page is showing a frightening number.
* **Nothing can be flagged.** While an action is outstanding the holding's profit and loss is
  not reliable, and the page has no way to know that.

`status` is why this table is NOT append-only, unlike the three beside it. A transaction is
an event and never changes; an action is a **thing the system is tracking**, and it moves
from PENDING to APPLIED, IGNORED or NEEDS_REVIEW as it is dealt with. What it *did* to the
book is still append-only — that lives in `transactions`, and `applied_txn_id` points at it.

`dedupe_key` rather than a unique constraint over `(instrument_id, action_type, ex_date)`:
NULLs are distinct in Postgres, so an undated announcement would insert afresh every evening
under that key, which is exactly the case the column exists to stop.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        # Nullable: NSE announces some actions before fixing the ex-date. An undated action is
        # worth recording and flagging, and is simply never applied automatically.
        sa.Column("ex_date", sa.Date()),
        # The multiplier as an exact fraction — 2/1 for a 1:1 bonus, 10/1 for a ₹10→₹1 split.
        # ⚠ Integers, not a Numeric ratio: 1/3 has no exact decimal, and a third of a holding
        # rounded at storage time is a rounding error written permanently into the quantity.
        sa.Column("ratio_num", sa.Integer()),
        sa.Column("ratio_den", sa.Integer()),
        sa.Column("amount_per_share", sa.Numeric(20, 6)),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        # The feed's own words, kept verbatim. This is what a person reads when the ratio
        # could not be parsed, and it is the provenance for what was applied.
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("applied_txn_id", sa.Uuid(), sa.ForeignKey("transactions.id")),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "action_type in ('SPLIT','BONUS','DIVIDEND','RIGHTS','MERGER','BUYBACK','DEMERGER')",
            name="corporate_actions_type",
        ),
        sa.CheckConstraint(
            "status in ('PENDING','APPLIED','IGNORED','NEEDS_REVIEW')",
            name="corporate_actions_status",
        ),
        # A ratio is either wholly present or wholly absent, and its parts are positive.
        # A half-parsed ratio is the shape that silently multiplies a holding by zero.
        sa.CheckConstraint(
            "(ratio_num IS NULL) = (ratio_den IS NULL) "
            "AND (ratio_num IS NULL OR (ratio_num > 0 AND ratio_den > 0))",
            name="corporate_actions_ratio",
        ),
        # APPLIED means a transaction exists. Nothing else may carry one.
        sa.CheckConstraint(
            "(status = 'APPLIED') = (applied_txn_id IS NOT NULL)",
            name="corporate_actions_applied_has_txn",
        ),
    )
    op.create_index(
        "corporate_actions_dedupe",
        "corporate_actions",
        ["instrument_id", "dedupe_key"],
        unique=True,
    )
    op.create_index("corporate_actions_open", "corporate_actions", ["instrument_id", "status"])


def downgrade() -> None:
    op.drop_index("corporate_actions_open", table_name="corporate_actions")
    op.drop_index("corporate_actions_dedupe", table_name="corporate_actions")
    op.drop_table("corporate_actions")
