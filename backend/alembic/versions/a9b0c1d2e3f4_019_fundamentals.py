"""019 — filed numbers, and the text they were filed as

Two tables, and the relationship between them is the whole anti-fabrication design.

**`source_items` is the provenance store.** One row per document the system has read — here,
one XBRL results filing. It keeps the URL, when it was published and fetched, a content hash,
and an **excerpt capped at 2 KB**: the literal tagged lines the figures were taken from.

**`fundamentals` is the extracted figures**, every one pointing back at the source item it
came from.

⚠ **Why the text is stored at all.** The rule the module rests on is that a language model
never produces a number — every figure in a thesis is looked up from a record and checked back
against that record's own words, character by character. That check needs the words. Storing
the parsed figure alone would leave the validator comparing a number against itself, which
validates nothing. The published benchmark for models answering questions about real filings
with document retrieval is a failure rate around four in five, so this is not a theoretical
concern.

**Why the document is NOT stored.** The module has a hard 250 MB budget on a disk already
three-quarters full, and filings run to 200 KB each. The file is parsed in memory and
discarded; ~15 fact lines at ~120 bytes each is what the record actually needs, and it fits
the 2 KB cap with room to spare.

**Both tables are append-only.** A filing is a thing that happened and a reported figure is a
fact about a moment. Companies do revise results — a revision arrives as a NEW source item
whose figures supersede the old ones, which is what `supersedes_id` is for. Editing the old
row in place would destroy the ability to ask what the system believed, and when.

`fundamentals`' primary key is `(instrument, period, metric, source_item)` rather than a uuid,
deliberately: re-parsing the same filing writes the identical rows and the insert does
nothing, so the sync job is safe to run as often as it likes.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUARD_FN = "investments_append_only"


def upgrade() -> None:
    op.create_table(
        "source_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # RESULTS_XBRL today. RSS_EXCHANGE, NEWS, YOUTUBE and USER_DROP follow when the
        # reading layer lands; the column exists now so those need no migration of shape.
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # Dedupe across feeds that carry the same document under different ids.
        sa.Column("content_hash", sa.Text(), nullable=False),
        # ⚠ HARD CAP 2 KB, enforced by a CHECK rather than by the code that writes it. A cap
        # the application promises to honour is a cap that a later writer forgets.
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("extraction", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(excerpt) <= 2048", name="source_items_excerpt_cap"),
        sa.CheckConstraint(
            "kind in ('RESULTS_XBRL','RSS_EXCHANGE','NEWS','YOUTUBE','USER_DROP','MACRO')",
            name="source_items_kind",
        ),
        sa.UniqueConstraint("source", "external_id", name="source_items_unique"),
    )
    op.create_index("source_items_by_instrument", "source_items", ["instrument_id", "kind"])

    op.create_table(
        "fundamentals",
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), primary_key=True),
        # 'FY26' or 'FY26Q1' — the period the figure DESCRIBES, never the date it was filed.
        sa.Column("fiscal_period", sa.Text(), primary_key=True),
        sa.Column("metric_key", sa.Text(), primary_key=True),
        sa.Column(
            "source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id"),
            primary_key=True,
        ),
        sa.Column("value", sa.Numeric(24, 6), nullable=False),
        # inr · pct · days · ratio · count — so a reader never has to infer scale.
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        # ⚠ Consolidated covers subsidiaries and standalone does not. Comparing one year's
        # consolidated figure with another's standalone is a silent apples-to-oranges error,
        # so which basis produced a figure travels with it.
        sa.Column("consolidated", sa.Boolean(), nullable=False),
        sa.Column("taxonomy", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("source_items.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "unit in ('inr','pct','days','ratio','count')", name="fundamentals_unit"
        ),
    )
    op.create_index(
        "fundamentals_series", "fundamentals", ["instrument_id", "metric_key", "period_end"]
    )

    # Both are append-only, guarded by the trigger function migration 014 installed.
    for table in ("source_items", "fundamentals"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_GUARD_FN}();"
        )


def downgrade() -> None:
    for table in ("fundamentals", "source_items"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
    op.drop_index("fundamentals_series", table_name="fundamentals")
    op.drop_table("fundamentals")
    op.drop_index("source_items_by_instrument", table_name="source_items")
    op.drop_table("source_items")
