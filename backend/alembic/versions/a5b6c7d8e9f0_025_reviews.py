"""025 — what was true at the end of a week, a month, a quarter

The artefact that is actually worth reading. The daily notifications are operational; this is
where the thinking accumulates — and where the system is asked, on a schedule and in public,
whether any of it is working.

⚠ **APPEND-ONLY, and for the same reason `framework_scores` is.** A review is a statement of
what was true at a moment, made with the data available then. Regenerating March's review in
June with June's figures would show a position that recovered as never having fallen, and a
prediction that failed as never having been made. The most interesting thing a review can
contain is the bit that turned out to be wrong, and a review that can be rewritten cannot
contain it.

⚠ **`content` is facts, not prose, and no model writes it.** Every other place in this module
forbids a model producing a number; a review is almost entirely numbers, so it is assembled by
code from records that already exist and each figure stays traceable to the row it came from.
A paragraph summarising them would be the one place in the whole design where a figure could
be restated wrongly with nothing to check it against.

⚠ **One row per period per kind, enforced here.** A weekly review that could be written twice
is a weekly review whose two copies will eventually disagree, and neither would be wrong on
its face.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        # The whole review, as facts. ⚠ Assembled by code; see the module note.
        sa.Column("content", JSONB, nullable=False),
        # One line, for the notification and the list. Composed from the same facts.
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind in ('WEEKLY','MONTHLY','QUARTERLY')", name="reviews_kind"),
        sa.CheckConstraint("period_end >= period_start", name="reviews_period"),
        sa.UniqueConstraint("user_id", "kind", "period_end", name="reviews_one_per_period"),
    )
    op.create_index("reviews_by_date", "reviews", ["user_id", "period_end"])

    op.execute(
        "CREATE TRIGGER reviews_append_only BEFORE UPDATE OR DELETE ON reviews "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS reviews_append_only ON reviews;")
    op.drop_index("reviews_by_date", table_name="reviews")
    op.drop_table("reviews")
