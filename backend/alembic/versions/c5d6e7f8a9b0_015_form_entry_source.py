"""015 — a transaction may say it was entered on a form

The ledger shipped with five ways a transaction could have arrived:

    CHAT, SCREENSHOT, PROPOSAL_APPROVAL, CORP_ACTION, IMPORT

The Investments page adds a sixth that none of those describes. Writing a form entry as
`CHAT` would be the cheap way out and is wrong: `entry_source` is provenance on an
append-only record, and the distinction it actually carries is **whether a language model
interpreted this, or whether a person typed the fields themselves**. Those two have different
failure modes and deserve different names — collapsing them would make the record lie about
how it came to exist, in the one table whose entire value is that it does not.

Purely additive: the constraint is widened, so every existing row still satisfies it and no
data is touched.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""

from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None

_OLD = "entry_source in ('CHAT','SCREENSHOT','PROPOSAL_APPROVAL','CORP_ACTION','IMPORT')"
_NEW = "entry_source in ('CHAT','FORM','SCREENSHOT','PROPOSAL_APPROVAL','CORP_ACTION','IMPORT')"


def upgrade() -> None:
    op.drop_constraint("transactions_entry_source", "transactions", type_="check")
    op.create_check_constraint("transactions_entry_source", "transactions", _NEW)


def downgrade() -> None:
    # ⚠ Will fail if any row has been written as FORM — correctly. Silently rewriting those
    # rows to another source to make a downgrade succeed would falsify the provenance of a
    # record that exists to be trusted.
    op.drop_constraint("transactions_entry_source", "transactions", type_="check")
    op.create_check_constraint("transactions_entry_source", "transactions", _OLD)
