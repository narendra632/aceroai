"""027 — the face value the exchange states for every listed company

A company's share count is its paid-up capital divided by its face value, and both come from
its own filing. That is the right source — until the filing says the face value is zero.

⚠ **Kaynes Technology filed a face value of 0.** Its paid-up capital came through intact
(₹67.03 crore) and its face value as `0.000000`, so the share count could not be computed, so
it had no market value, so the price half of its score — the margin of safety — was
permanently blank. Nothing about the company was unreadable except that one figure, and
nothing on the screen said which figure it was.

The exchange's own equity list states the face value of every listed company, in a column the
universe sync was already downloading and throwing away. It is now kept, and used only where a
filing's face value is missing or impossible — a filed figure still wins wherever it is sane,
because it is the company's own statement about the period being scored.

Nullable, and filled by the next weekly universe sync rather than by this migration: the sync
already rewrites every row, and a migration that reached out to the network would be the only
one in this project that could fail for a reason outside the database.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("listed_companies", sa.Column("face_value", sa.Numeric(12, 4), nullable=True))
    # A face value is a positive amount of rupees. Zero is exactly the value this column exists
    # to stand in for, so it is refused here rather than copied in from a bad row.
    op.create_check_constraint(
        "ck_listed_companies_face_value_positive",
        "listed_companies",
        "face_value IS NULL OR face_value > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_listed_companies_face_value_positive", "listed_companies", type_="check"
    )
    op.drop_column("listed_companies", "face_value")
