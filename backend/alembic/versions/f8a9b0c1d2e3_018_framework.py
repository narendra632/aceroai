"""018 — the framework, stored as versioned data rather than written into the code

Phase 2 scores companies against a theory about India: ten things the country must build, the
bottlenecks standing in the way, and what a business in each sector is worth. Two tables hold
that, and the split between them is the whole design.

**`framework_versions` holds the THEORY.** Imperatives, bottlenecks, how many imperatives each
bottleneck blocks, the fair multiple per sector, the scoring weights. It changes rarely and
deliberately, and **every change is a new row**. A score and a proposal each carry the version
that produced them, so a review months later can always ask "under which rules?" — and
improving the framework never silently rewrites the history of decisions made under the old one.

**`ab_mappings` holds WHICH COMPANY sits where in that theory.** It changes often: every new
holding or watchlist name needs one. Keeping it out of the versioned blob means adding a
company does not create a new epoch of the framework, which would make every past decision
look like it was made under different rules.

⚠ **`crossings_status` exists because a gap in the notes is not a finding.**

How many imperatives a bottleneck blocks is the largest single component of the structural
score. Narendra's own framework spells that out for the eight bottlenecks in its "Master
Bottleneck Map" and leaves it unstated for the other twenty-odd — not because those block
less, but because those sections were written more briefly. Defaulting them to 1 would score a
documentation gap as though it were a fact about India, and Solar Industries would look
structurally weak because the ammunition section is short.

So a count carries its own provenance. `CONFIRMED` is stated in his framework. `PARTIAL` means
"at least this many, and nobody has established the rest" — it scores on what is known and the
interface says the figure is a floor. Approval promotes PARTIAL to CONFIRMED.

⚠ **`off_framework` and `review_after` close two holes found by walking the scenarios.**

`off_framework`: the framework asks what INDIA must build. SpaceX is a US company, so no
imperative applies to it — not because it is a poor holding but because the question does not
apply. Without this it would score zero and be blocked as though it had failed.

`review_after`: a mapping is a judgement about what a company does today. Kaynes is an
electronics manufacturer moving into chip packaging; a mapping approved two years ago would
quietly still be scoring the old business. A mapping has an expiry, not permanence.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "framework_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # Three families, versioned independently: the India structural framework, the
        # quality-and-reflexivity checklist, and the gates. A change to one must not reset
        # the comparability of decisions made under the others.
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", JSONB(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text()),
        # ⚠ NULL until a human approves. An unapproved version is a PROPOSAL — it is what a
        # newly-suggested bottleneck lands in, and nothing scores against it.
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_note", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "family in ('india_ab','buffett_soros','gates')", name="framework_versions_family"
        ),
        sa.CheckConstraint("version > 0", name="framework_versions_version"),
        sa.UniqueConstraint("family", "version", name="framework_versions_unique"),
    )

    op.create_table(
        "ab_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("instruments.id"), nullable=False),
        # Which imperatives this company's bottleneck serves, e.g. {A1,A2,A3,A5,A6,A9}.
        sa.Column("a_imperatives", ARRAY(sa.Text())),
        sa.Column("b_bottleneck", sa.Text()),
        sa.Column("crosses_a_count", sa.Integer(), nullable=False, server_default="0"),
        # CONFIRMED · PARTIAL · UNSUPPORTED — see the module docstring.
        sa.Column(
            "crossings_status", sa.Text(), nullable=False, server_default=sa.text("'PARTIAL'")
        ),
        sa.Column(
            "is_crisis_accelerated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("inflection_quarter", sa.Text()),
        sa.Column("investability", sa.Text()),
        sa.Column("rationale", sa.Text()),
        sa.Column("proposed_by", sa.Text(), nullable=False),
        # ⚠ A row with approved_at IS NULL scores ZERO. This is the guard against a model
        # narrating an unrelated small-cap into national importance: it may propose the
        # claim, and the claim is worth nothing until a person agrees with it.
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_note", sa.Text()),
        # When this judgement should be looked at again. A company's business changes.
        sa.Column("review_after", sa.Date()),
        # Outside the framework by construction: a non-Indian company, or one the user has
        # said is simply off-thesis. Scored differently rather than scored badly.
        sa.Column("off_framework", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "framework_version_id",
            sa.Uuid(),
            sa.ForeignKey("framework_versions.id"),
            nullable=False,
        ),
        sa.Column("superseded_by_id", sa.Uuid(), sa.ForeignKey("ab_mappings.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "crossings_status in ('CONFIRMED','PARTIAL','UNSUPPORTED')",
            name="ab_mappings_crossings_status",
        ),
        sa.CheckConstraint(
            "investability is null or investability in ('GREEN','AMBER','RED')",
            name="ab_mappings_investability",
        ),
        sa.CheckConstraint("proposed_by in ('USER','AGENT')", name="ab_mappings_proposed_by"),
        sa.CheckConstraint("crosses_a_count >= 0", name="ab_mappings_count"),
        # An off-framework mapping names no bottleneck; an on-framework one must.
        sa.CheckConstraint(
            "off_framework = (b_bottleneck IS NULL)", name="ab_mappings_off_framework"
        ),
    )
    op.create_index(
        "ab_mappings_live",
        "ab_mappings",
        ["instrument_id"],
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ab_mappings_live", table_name="ab_mappings")
    op.drop_table("ab_mappings")
    op.drop_table("framework_versions")
