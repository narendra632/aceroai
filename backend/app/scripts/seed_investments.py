"""Seed the real portfolio, and the charge schedules that price it.

    uv run python -m app.scripts.seed_investments          # write it
    uv run python -m app.scripts.seed_investments --check  # reconcile only, write nothing

Every figure comes from `openspec/changes/add-investment-ledger/seed-reconciliation.md`,
worked out by hand from Groww, CoinSwitch and INDmoney screenshots **before any of this code
existed**. Idempotent: run it twice and nothing is duplicated.

⚠ Two crypto rows are honest AGGREGATES. Dogecoin (₹840 across 4 buys) and Bitcoin (₹150
across 2) are entered as one row each at the average price, dated to the FIRST buy, marked
`IMPORT` with a note saying so. The per-buy amounts are not recoverable from CoinSwitch's
history, and a labelled aggregate is honest where an invented breakdown would not be.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from decimal import Decimal as D

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import ChargeSchedule, Instrument, Portfolio, Transaction, User
from app.db.session import SessionLocal
from app.services.investments import costmodel
from app.services.investments import portfolio as pf

# --- instruments ----------------------------------------------------------------------
# ⚠ **The identifiers the price feeds need live HERE, in the seed data.**
#
# They were first written as data fixes in migration 016, which corrects the rows an existing
# database already has. That is right for an existing database and useless for a fresh one:
# on the server the migration ran against an empty schema and the seed then re-created the
# instruments with the old symbol and no codes, so GE Vernova and both funds silently went
# unpriced while everything else worked. A migration mends the past; the seed defines the
# present, and each identifier has to be in both.
#
# `symbol` is what the EXCHANGE calls it — NSE's is `GVT&D`, not the `GVTD` that looks right —
# because the bhavcopy is matched on it. Old names stay as aliases so chat still finds them.
INSTRUMENTS = [
    # symbol, exchange, name, asset_class, currency, aliases, ids
    ("HDFCBANK", "NSE", "HDFC Bank", "EQUITY_IN", "INR", None, {"sector": "PRIVATE_BANK"}),
    ("KAYNES", "NSE", "Kaynes Technology", "EQUITY_IN", "INR", None, {"sector": "EMS_ELECTRONICS"}),
    (
        "GVT&D",
        "NSE",
        "GE Vernova T&D India",
        "EQUITY_IN",
        "INR",
        ["GVTD"],
        {"sector": "CAPITAL_GOODS_POWER_EQUIPMENT"},
    ),
    ("SAILIFE", "NSE", "Sai Life Sciences", "EQUITY_IN", "INR", None, {"sector": "PHARMA_CDMO"}),
    ("SPCX", "NASDAQ", "SpaceX", "EQUITY_US", "USD", None, {}),
    # ⚠ Renamed under SEBI's scheme-naming standardisation, same ISIN. Both names are carried
    # or an AMFI lookup appears to break when only the label changed.
    (
        "HDFCMIDCAP",
        "MF_IN",
        "HDFC Mid Cap Fund Direct Growth",
        "MF_IN",
        "INR",
        ["HDFC Mid-Cap Opportunities Fund", "HDFCMIDCAPOPP"],
        {"amfi_scheme_code": "118989", "isin": "INF179K01XQ0"},
    ),
    (
        "HDFCFLEXICAP",
        "MF_IN",
        "HDFC Flexi Cap Direct Plan Growth",
        "MF_IN",
        "INR",
        None,
        {"amfi_scheme_code": "118955", "isin": "INF179K01UT0"},
    ),
    ("DOGE", "CRYPTO", "Dogecoin", "CRYPTO", "INR", None, {"coingecko_id": "dogecoin"}),
    ("BTC", "CRYPTO", "Bitcoin", "CRYPTO", "INR", None, {"coingecko_id": "bitcoin"}),
    ("ZIL", "CRYPTO", "Zilliqa", "CRYPTO", "INR", None, {"coingecko_id": "zilliqa"}),
    ("JASMY", "CRYPTO", "JasmyCoin", "CRYPTO", "INR", None, {"coingecko_id": "jasmycoin"}),
]

# --- watchlist ---------------------------------------------------------------------------
# Companies the framework names that are NOT held. Tracked, priced and scored; no
# transactions, so they never appear as a holding and never touch a return.
#
# ⚠ Without these the system can only ever say "hold" or "sell". A research analyst that can
# only comment on what you already own is a bookkeeper with opinions — the whole point of the
# structural framework is to say "look at this", and it has nothing to look at until here.
WATCHLIST = [
    # symbol, exchange, name, asset_class, currency, aliases, ids
    (
        "APARINDS",
        "NSE",
        "Apar Industries",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "CABLES_CONDUCTORS"},
    ),
    (
        "SOLARINDS",
        "NSE",
        "Solar Industries India",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "DEFENCE_MANUFACTURING"},
    ),
    (
        "NEULANDLAB",
        "NSE",
        "Neuland Laboratories",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "PHARMA_CDMO"},
    ),
    (
        "GENUSPOWER",
        "NSE",
        "Genus Power Infrastructures",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "SMART_METERING"},
    ),
    (
        "SYRMA",
        "NSE",
        "Syrma SGS Technology",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "EMS_ELECTRONICS"},
    ),
    (
        "PREMIERENE",
        "NSE",
        "Premier Energies",
        "EQUITY_IN",
        "INR",
        None,
        {"sector": "SOLAR_MANUFACTURING"},
    ),
    ("ROLEXRINGS", "NSE", "Rolex Rings", "EQUITY_IN", "INR", None, {"sector": "AUTO_COMPONENTS"}),
]

# (symbol, date, quantity, price, fx_rate, note)
#
# The Kaynes order of 1 at ₹3,080 on 2026-05-18 is ABSENT on purpose: it did not execute.
# Including it gives 6 shares and ₹19,974; excluding it gives exactly the 5 shares and
# ₹16,894.00 Groww reports. The arithmetic settles it — see seed-reconciliation.md §1.
BUYS = [
    ("HDFCBANK", "2026-04-27", "5", "787.80", "1", None),
    ("HDFCBANK", "2026-06-04", "7", "750.30", "1", None),
    ("HDFCBANK", "2026-06-05", "4", "746.80", "1", None),
    ("HDFCBANK", "2026-08-12", "13", "723.75", "1", None),
    ("HDFCBANK", "2026-08-12", "4", "722.65", "1", None),
    ("KAYNES", "2026-05-12", "1", "4133.20", "1", None),
    ("KAYNES", "2026-05-14", "1", "3388.00", "1", None),
    ("KAYNES", "2026-05-15", "1", "3271.00", "1", None),
    ("KAYNES", "2026-05-18", "1", "3102.00", "1", None),
    ("KAYNES", "2026-05-20", "1", "2999.80", "1", None),
    ("GVT&D", "2026-05-29", "1", "5000.00", "1", None),
    ("GVT&D", "2026-06-01", "1", "4748.00", "1", None),
    ("GVT&D", "2026-06-02", "1", "4639.50", "1", None),
    ("SAILIFE", "2026-04-30", "2", "1066.35", "1", None),
    ("SAILIFE", "2026-06-04", "4", "1159.00", "1", None),
    # One remittance, one rate: ₹14,955 converted at 96.01 gave $155.77, and INDmoney trades
    # from the USD balance rather than converting per trade.
    ("SPCX", "2026-06-16", "0.24352711", "204.70", "96.01", None),
    ("SPCX", "2026-06-17", "0.26236842", "190.00", "96.01", None),
    ("SPCX", "2026-07-03", "0.35654292", "155.97", "96.01", None),
    # ⚠ Units DERIVED from the amount at 8dp, not the 3dp Groww displays. A mutual fund
    # purchase is amount-driven — Rs 4,999.75 left the bank after stamp duty, and the unit
    # count is a consequence. At 3dp the cost basis comes out Rs 0.64 high on Flexi Cap,
    # which would quietly bias every return. Same rule as the SPCX fractional buys.
    ("HDFCFLEXICAP", "2026-02-11", "2.17241589", "2301.470", "1", None),
    ("HDFCFLEXICAP", "2026-03-06", "2.29164786", "2181.727", "1", None),
    ("HDFCFLEXICAP", "2026-04-30", "2.33961161", "2137.000", "1", None),
    ("HDFCMIDCAP", "2026-02-12", "22.11270969", "226.103", "1", None),
    ("HDFCMIDCAP", "2026-03-06", "23.22904519", "215.237", "1", None),
    ("ZIL", "2024-12-07", "93.4675", "3.177870", "1", None),
    ("JASMY", "2024-12-07", "45.2488", "4.420010", "1", None),
    (
        "DOGE",
        "2024-11-17",
        "23.8916",
        "35.158500",
        "1",
        "aggregate of 4 buys (17 & 24 Nov, 10 & 22 Dec 2024) totalling Rs 840 — per-buy "
        "amounts not recoverable from CoinSwitch; dated to the first buy",
    ),
    (
        "BTC",
        "2024-11-17",
        "0.00001978",
        "7583417.593528",
        "1",
        "aggregate of 2 buys (17 Nov 2024, 1 May 2026) totalling Rs 150 — per-buy amounts "
        "not recoverable from CoinSwitch; dated to the first buy",
    ),
]

#: What the hand reconciliation says must come out. The seed is only correct if it does.
EXPECTED = {
    "HDFCBANK": ("33", "24477.65"),
    "KAYNES": ("5", "16894.00"),
    "GVT&D": ("3", "14387.50"),
    "SAILIFE": ("6", "6768.70"),
    # Units are 0.0003 below Groww's DISPLAYED total, which rounds to 3dp. Worth Rs 0.74 at
    # current NAV; the cost basis is exact, and that is the figure returns depend on.
    "HDFCFLEXICAP": ("6.80367536", "14999.25"),
    "HDFCMIDCAP": ("45.34175488", "9999.50"),
    "SPCX": ("0.86243845", "155.31"),
}


def _schedules(db: Session) -> None:
    """Write the charge schedules, dated so a later correction is a new row, not an edit."""
    for venue, spec in costmodel.DEFAULT_SCHEDULES.items():
        exists = db.execute(sa.select(ChargeSchedule).where(ChargeSchedule.venue == venue)).first()
        if exists:
            continue
        db.add(
            ChargeSchedule(
                id=uuid.uuid4(),
                name=f"{venue} as verified 2026-09-06",
                venue=venue,
                effective_from=dt.date(2020, 7, 1),  # uniform stamp duty regime
                spec=spec,
                source_note="docs/transactioncostsreference.md, verified 2026-09-06",
            )
        )


def _instruments(db: Session) -> dict[str, Instrument]:
    """Create what is missing, and correct what is already there.

    ⚠ Correcting matters as much as creating. A database seeded before these identifiers
    existed holds rows without them, and a row found by an old alias must be RENAMED rather
    than joined by a second row: creating `GVT&D` beside an existing `GVTD` would split one
    holding's transactions across two instruments, and the page would show both halves.
    """
    out: dict[str, Instrument] = {}
    # Held and watched go through the identical path: an instrument is an instrument, and
    # what makes one a holding is having transactions, not a flag on this row.
    for symbol, exchange, name, asset_class, currency, aliases, ids in (
        *INSTRUMENTS,
        *WATCHLIST,
    ):
        names = [symbol, *(aliases or [])]
        found = (
            db.execute(
                sa.select(Instrument).where(
                    Instrument.exchange == exchange,
                    Instrument.deleted_at.is_(None),
                    sa.or_(
                        Instrument.symbol.in_(names),
                        *([Instrument.aliases.overlap(names)] if names else []),
                    ),
                )
            )
            .scalars()
            .first()
        )
        if found is None:
            found = Instrument(
                id=uuid.uuid4(),
                symbol=symbol,
                exchange=exchange,
                name=name,
                asset_class=asset_class,
                currency=currency,
                aliases=aliases,
                **ids,
            )
            db.add(found)
        else:
            found.symbol = symbol
            keep = {*(found.aliases or []), *(aliases or [])} - {symbol}
            found.aliases = sorted(keep) or None
            for field, value in ids.items():
                if getattr(found, field, None) != value:
                    setattr(found, field, value)
        out[symbol] = found
    db.flush()
    return out


def _books(db: Session, user: User) -> Portfolio:
    """REAL now, MIRROR empty. ⚠ Not nested books — the difference between them is the
    measurement the whole module exists to produce."""
    real = db.execute(
        sa.select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.kind == "REAL")
    ).scalar_one_or_none()
    if real is None:
        real = Portfolio(id=uuid.uuid4(), user_id=user.id, name="Real portfolio", kind="REAL")
        db.add(real)
    if not db.execute(
        sa.select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.kind == "MIRROR")
    ).first():
        db.add(
            Portfolio(
                id=uuid.uuid4(),
                user_id=user.id,
                name="What Acero would have done",
                kind="MIRROR",
            )
        )
    db.flush()
    return real


def seed(db: Session, *, write: bool = True, user: User | None = None) -> dict:
    if user is None:
        user = db.execute(sa.select(User).order_by(User.created_at)).scalars().first()
    if user is None:
        raise SystemExit("no user — run create_user first")

    _schedules(db)
    insts = _instruments(db)
    book = _books(db, user)

    added = 0
    for symbol, date, qty, price, fx, note in BUYS:
        trade_date = dt.date.fromisoformat(date)
        exists = db.execute(
            sa.select(Transaction).where(
                Transaction.portfolio_id == book.id,
                Transaction.instrument_id == insts[symbol].id,
                Transaction.trade_date == trade_date,
                Transaction.quantity == D(qty),
                Transaction.price == D(price),
            )
        ).first()
        if exists:
            continue
        db.add(
            Transaction(
                id=uuid.uuid4(),
                portfolio_id=book.id,
                instrument_id=insts[symbol].id,
                txn_type="BUY",
                trade_date=trade_date,
                quantity=D(qty),
                price=D(price),
                currency=insts[symbol].currency,
                fx_rate_inr=D(fx),
                entry_source="IMPORT",
                note=note,
            )
        )
        added += 1

    if write:
        db.commit()
    else:
        db.flush()
    return {"transactions_added": added, "portfolio_id": book.id}


def reconcile(db: Session, portfolio_id: uuid.UUID) -> list[str]:
    """Compare the seeded book against the hand-computed figures. Returns any disagreements.

    This is the test the whole change exists to pass, run against the real database rather
    than a fixture.
    """
    problems = []
    positions = {p.symbol: p for p in pf.positions(db, portfolio_id)}
    for symbol, (qty, cost) in EXPECTED.items():
        pos = positions.get(symbol)
        if pos is None:
            problems.append(f"{symbol}: not held")
            continue
        if pos.quantity != D(qty):
            problems.append(f"{symbol}: quantity {pos.quantity}, expected {qty}")
        if round(pos.cost_basis, 2) != D(cost):
            problems.append(f"{symbol}: cost {round(pos.cost_basis, 2)}, expected {cost}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the real investment portfolio.")
    parser.add_argument("--check", action="store_true", help="reconcile only, write nothing")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        result = seed(db, write=not args.check)
        problems = reconcile(db, result["portfolio_id"])
        if args.check:
            db.rollback()

        print(f"transactions added: {result['transactions_added']}")
        for symbol, pos in sorted((p.symbol, p) for p in pf.positions(db, result["portfolio_id"])):
            print(f"  {symbol:14} {pos.quantity:>14}  cost {round(pos.cost_basis, 2):>12}")

        if problems:
            print("\nDISAGREES WITH THE HAND RECONCILIATION:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("\nreconciles with seed-reconciliation.md")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
