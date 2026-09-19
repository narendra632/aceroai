"""016 — instruments carry the codes the price sources know them by

A display symbol is a poor key for fetching prices. The seed recorded GE Vernova T&D India
as `GVTD`, which is what it looks like and not what NSE calls it: the exchange's symbol is
`GVT&D`, and a lookup by the invented one finds nothing. Found by calling the sources before
writing any adapter, not by a failed price run.

Two provider IDs are added rather than derived at fetch time:

* `angel_token` — Angel One's numeric instrument ID (HDFCBANK is 1333). Filled from NSE's own
  bhavcopy, whose `FinInstrmId` column is the same number, so Angel's 35 MB instrument master
  never has to be parsed on a 1 GB server.
* `coingecko_id` — CoinGecko's slug. A ticker is not unique across coins; the slug is.

NSE `isin` is filled at runtime from the bhavcopy as well, not hard-coded here, so a stock
recorded next month is resolved by the same path as these four.

The data fixes are keyed by `(exchange, symbol)` and touch nothing that does not match, so
this is safe on a database that was never seeded.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None

_COINS = {"BTC": "bitcoin", "DOGE": "dogecoin", "ZIL": "zilliqa", "JASMY": "jasmycoin"}

#: Confirmed by Narendra against Groww on 2026-09-19. ⚠ Each fund has Direct/Regular ×
#: Growth/IDCW variants at different prices — these are the Direct Growth ones he holds.
_FUNDS = {
    "HDFCMIDCAP": ("118989", "INF179K01XQ0"),
    "HDFCFLEXICAP": ("118955", "INF179K01UT0"),
}


def upgrade() -> None:
    op.add_column("instruments", sa.Column("angel_token", sa.Text()))
    op.add_column("instruments", sa.Column("coingecko_id", sa.Text()))

    op.execute(
        """
        UPDATE instruments
           SET symbol = 'GVT&D',
               aliases = array_append(coalesce(aliases, '{}'::text[]), 'GVTD')
         WHERE exchange = 'NSE' AND symbol = 'GVTD'
        """
    )
    for symbol, slug in _COINS.items():
        op.execute(
            sa.text(
                "UPDATE instruments SET coingecko_id = :slug "
                "WHERE exchange = 'CRYPTO' AND symbol = :symbol"
            ).bindparams(slug=slug, symbol=symbol)
        )
    for symbol, (code, isin) in _FUNDS.items():
        op.execute(
            sa.text(
                "UPDATE instruments SET amfi_scheme_code = :code, isin = :isin "
                "WHERE exchange = 'MF_IN' AND symbol = :symbol"
            ).bindparams(code=code, isin=isin, symbol=symbol)
        )


def downgrade() -> None:
    for symbol, (code, _isin) in _FUNDS.items():
        op.execute(
            sa.text(
                "UPDATE instruments SET amfi_scheme_code = NULL, isin = NULL "
                "WHERE exchange = 'MF_IN' AND symbol = :symbol AND amfi_scheme_code = :code"
            ).bindparams(symbol=symbol, code=code)
        )
    op.execute(
        """
        UPDATE instruments
           SET symbol = 'GVTD', aliases = array_remove(aliases, 'GVTD')
         WHERE exchange = 'NSE' AND symbol = 'GVT&D'
        """
    )
    op.drop_column("instruments", "coingecko_id")
    op.drop_column("instruments", "angel_token")
