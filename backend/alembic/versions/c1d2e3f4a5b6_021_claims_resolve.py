"""021 — a claim can be settled without the claim itself becoming editable

`claims` was made wholly append-only in 020, and that was one step too far. Resolving a claim
writes its outcome onto the row — and the trigger correctly refused, which is the guard
working on its author for the third time in this module.

⚠ **The distinction the first version missed.** What must never change is the **prediction**:
the assertion, the metric it is about, the threshold it must clear, and the date by which. A
prediction revisable after the outcome is known is worth nothing for judging yourself, and
hindsight is not something people resist by intending to.

The **resolution** is not a revision of that. It is a new fact, discovered later, about a
prediction that has not moved — exactly the shape of an invalidation condition firing, which
020 already got right by making `invalidation_triggers` mutable in its status alone.

So the guard is narrowed rather than dropped. An UPDATE that touches any part of the claim
still raises; an UPDATE that only records what happened is allowed. That is a stronger
guarantee than either "append-only" or "mutable" alone would give, because it says exactly
which columns carry the promise.

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: The columns that carry the prediction. Touching any of them after the fact is the failure
#: the whole append-only design exists to prevent.
_FROZEN = (
    "id",
    "proposal_id",
    "claim_text",
    "metric_key",
    "comparator",
    "threshold",
    "due_by",
    "created_at",
)

_CONDITION = " OR ".join(
    f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column in _FROZEN
)

_GUARD = """
CREATE OR REPLACE FUNCTION claims_prediction_is_frozen() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'a claim is a prediction: its text, metric, threshold and deadline cannot change '
        'once written. Record the outcome instead.'
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS claims_append_only ON claims;")
    op.execute(_GUARD)
    # DELETE is still refused outright: a prediction that can be removed after the fact is a
    # prediction that never has to be counted.
    op.execute(
        "CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )
    op.execute(
        f"CREATE TRIGGER claims_prediction_frozen BEFORE UPDATE ON claims "
        f"FOR EACH ROW WHEN ({_CONDITION}) "
        f"EXECUTE FUNCTION claims_prediction_is_frozen();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS claims_prediction_frozen ON claims;")
    op.execute("DROP TRIGGER IF EXISTS claims_no_delete ON claims;")
    op.execute("DROP FUNCTION IF EXISTS claims_prediction_is_frozen();")
    op.execute(
        "CREATE TRIGGER claims_append_only BEFORE UPDATE OR DELETE ON claims "
        "FOR EACH ROW EXECUTE FUNCTION investments_append_only();"
    )
