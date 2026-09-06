"""Investment tools: record what happened, read what is held.

⚠ **The model never writes directly.** `record_transaction` returns a *draft* — what it
understood, costed and validated — and the user confirms it with `confirm_transaction`. Two
steps rather than one, deliberately: a model that can append to the ledger in a single call is
a model that can invent a holding, and D1 of the whole module exists to prevent exactly that.

Every function here calls `services/investments`. There is no rule implemented in this file
that the REST API does not also get, which is convention 2 and the reason it exists.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Portfolio, User
from app.services.errors import Invalid, NotFound
from app.services.investments import entry, pricing, taxrules
from app.services.investments import portfolio as pf

#: Drafts awaiting confirmation, keyed by a short handle the model quotes back.
#:
#: In memory rather than in the database on purpose: a draft is a half-finished sentence in a
#: conversation, not a fact about the portfolio. Persisting it would put something in the
#: record that never happened, which is the one thing this ledger is built to avoid. Losing
#: them on restart costs the user one retyped sentence.
_PENDING: dict[str, tuple[uuid.UUID, entry.Draft]] = {}


def _book(db: Session, user: User, kind: str = "REAL") -> Portfolio:
    book = db.execute(
        sa.select(Portfolio).where(
            Portfolio.user_id == user.id, Portfolio.kind == kind, Portfolio.deleted_at.is_(None)
        )
    ).scalar_one_or_none()
    if book is None:
        raise NotFound(f"no {kind} portfolio — seed it before recording transactions")
    return book


def _decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise Invalid(f"{field} must be a number, got {value!r}") from exc


def _date(value, field: str = "date") -> dt.date:
    if not value or value == "today":
        return dt.date.today()
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise Invalid(f"{field} must be YYYY-MM-DD or 'today', got {value!r}") from exc


SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "record_transaction",
            "description": (
                "Understand a buy or sell the user describes and return it for confirmation. "
                "This does NOT write anything — always show the user what came back and wait for "
                "them to agree, then call confirm_transaction. Use for 'bought 4 HDFC at 722.65'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker or fund name."},
                    "action": {"type": "string", "enum": ["BUY", "SELL"]},
                    "quantity": {"type": "string", "description": "Units. Fractions allowed."},
                    "price": {"type": "string", "description": "Per unit, in its own currency."},
                    "date": {"type": "string", "description": "YYYY-MM-DD, or 'today'."},
                    "exchange": {
                        "type": "string",
                        "description": "Only for an instrument not seen before.",
                    },
                    "name": {"type": "string", "description": "Only for a new instrument."},
                    "asset_class": {
                        "type": "string",
                        "enum": ["EQUITY_IN", "EQUITY_US", "CRYPTO", "MF_IN"],
                        "description": "Only for a new instrument.",
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["INR", "USD"],
                        "description": "Only for a new instrument.",
                    },
                    "fx_rate_inr": {
                        "type": "string",
                        "description": (
                            "Rupees per unit of foreign currency, as ACTUALLY RECEIVED. Required "
                            "for a non-INR holding. Never guess it — ask the user."
                        ),
                    },
                },
                "required": ["symbol", "action", "quantity", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_transaction",
            "description": (
                "Write a draft the user has agreed to. Only call this after showing them the "
                "draft and receiving a clear yes."
            ),
            "parameters": {
                "type": "object",
                "properties": {"handle": {"type": "string"}},
                "required": ["handle"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": (
                "What the user holds: quantities, cost, current value where a price is known, "
                "and totals. Says explicitly which holdings are unpriced or stale."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_position",
            "description": "One holding in detail, including its lots and holding periods.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_price",
            "description": (
                "Record what something is worth right now. Use when the user states a price, "
                "e.g. 'HDFC Bank is at 712'. Writes immediately — a price is an observation, not "
                "a change to the record of what is held."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "price": {"type": "string"},
                },
                "required": ["symbol", "price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_transaction",
            "description": (
                "Withdraw an entry the user says was wrong. Nothing is deleted — a correcting "
                "entry is added and both stay in the history."
            ),
            "parameters": {
                "type": "object",
                "properties": {"handle": {"type": "string", "description": "From get_portfolio."}},
                "required": ["handle"],
            },
        },
    },
]


def record_transaction(db: Session, user: User, args: dict) -> dict:
    book = _book(db, user)
    draft = entry.prepare(
        db,
        book.id,
        symbol=str(args["symbol"]).strip(),
        txn_type=str(args["action"]).upper(),
        quantity=_decimal(args["quantity"], "quantity"),
        price=_decimal(args["price"], "price"),
        trade_date=_date(args.get("date")),
        exchange=args.get("exchange"),
        name=args.get("name"),
        asset_class=args.get("asset_class"),
        currency=args.get("currency"),
        fx_rate_inr=_decimal(args["fx_rate_inr"], "fx_rate_inr")
        if args.get("fx_rate_inr")
        else None,
    )
    handle = uuid.uuid4().hex[:8]
    _PENDING[handle] = (book.id, draft)
    return {
        "handle": handle,
        "draft": draft.as_dict(),
        "next": "show this to the user and call confirm_transaction only if they agree",
    }


def confirm_transaction(db: Session, user: User, args: dict) -> dict:
    handle = str(args["handle"])
    pending = _PENDING.pop(handle, None)
    if pending is None:
        raise Invalid("that draft has expired — describe the transaction again")
    book_id, draft = pending
    txn = entry.record(db, book_id, draft, entry_source="CHAT")
    return {
        "recorded": draft.as_dict(),
        "handle": str(txn.id)[:8],
        "note": "recorded — say what was written, including the charges",
    }


def get_portfolio(db: Session, user: User, args: dict) -> dict:
    book = _book(db, user)
    positions = pf.positions(db, book.id)
    marks = pricing.latest(db, [p.instrument_id for p in positions])
    valued = pricing.value(positions, marks, fx_inr=_fx_rates(db, positions, marks))
    totals = pricing.totals(valued)

    return {
        "holdings": [
            {
                "symbol": v.symbol,
                "quantity": str(v.quantity),
                "average_cost": str(round(v.cost_basis / v.quantity, 4)) if v.quantity else None,
                "currency": v.currency,
                "invested_inr": str(round(v.cost_basis_inr, 2)),
                "value_inr": str(round(v.market_value_inr, 2)) if v.is_priced else None,
                "unrealised_inr": str(round(v.unrealised_inr, 2)) if v.is_priced else None,
                "price_age": v.mark.age_text if v.mark else None,
                "price_is_stale": v.mark.is_stale if v.mark else None,
            }
            for v in valued
        ],
        "invested_inr": str(round(totals.invested_inr, 2)),
        "value_inr": str(round(totals.market_value_inr, 2)),
        "unrealised_inr": str(round(totals.unrealised_inr, 2)),
        "realised_inr": str(round(totals.realised_inr, 2)),
        # ⚠ Reported apart, never netted: under s.115BBH a crypto loss offsets nothing.
        "crypto_unrealised_inr": str(round(totals.ring_fenced_inr, 2)),
        "unpriced": totals.unpriced,
        "stale": totals.stale,
        "total_is_complete": totals.is_complete,
        "note": (
            "if total_is_complete is false, say so — the totals exclude the unpriced holdings"
        ),
    }


def get_position(db: Session, user: User, args: dict) -> dict:
    book = _book(db, user)
    inst = entry.find_instrument(db, str(args["symbol"]).strip())
    if inst is None:
        raise NotFound(f"nothing held or tracked called {args['symbol']!r}")
    pos = pf.position(db, book.id, inst.id)
    if pos is None:
        raise NotFound(f"the book has never held {inst.symbol}")

    periods = taxrules.holding_periods(pos.lots, pos.asset_class)
    waiting = taxrules.days_to_long_term(pos.lots, pos.asset_class)
    return {
        "symbol": pos.symbol,
        "name": inst.name,
        "quantity": str(pos.quantity),
        "average_cost": str(round(pos.cost_basis / pos.quantity, 4)) if pos.quantity else None,
        "invested_inr": str(round(pos.cost_basis_inr, 2)),
        "realised_inr": str(round(pos.realised_inr, 2)),
        "lots": [
            {
                "date": hp.lot.trade_date.isoformat(),
                "quantity": str(hp.lot.quantity),
                "unit_cost": str(round(hp.lot.unit_cost, 4)),
                "days_held": hp.days_held,
                "long_term": hp.is_long_term,
                "long_term_on": hp.long_term_on.isoformat() if hp.long_term_on else None,
            }
            for hp in periods
        ],
        "days_to_long_term": waiting,
        "losses_offset_other_gains": not taxrules.losses_are_ring_fenced(pos.asset_class),
        "note": (
            "if days_to_long_term is small and a sale is being considered, say what waiting "
            "is worth — the rate difference is 20% versus 12.5% for Indian equity"
        ),
    }


def record_price(db: Session, user: User, args: dict) -> dict:
    inst = entry.find_instrument(db, str(args["symbol"]).strip())
    if inst is None:
        raise NotFound(f"nothing held or tracked called {args['symbol']!r}")
    price = _decimal(args["price"], "price")
    pricing.record(db, inst.id, price, inst.currency, source="USER")
    db.commit()
    return {"symbol": inst.symbol, "price": str(price), "currency": inst.currency}


def undo_transaction(db: Session, user: User, args: dict) -> dict:
    book = _book(db, user)
    handle = str(args["handle"]).strip()
    match = next(
        (t for t in entry.history(db, book.id) if str(t.id).startswith(handle)),
        None,
    )
    if match is None:
        raise NotFound(f"no entry starting {handle!r}")
    entry.reverse(db, match.id)
    return {
        "withdrawn": handle,
        "note": "a correcting entry was added; nothing was deleted and both remain in history",
    }


def _fx_rates(db: Session, positions, marks) -> dict[str, Decimal]:
    """Rupee rates for any foreign currency held, from the newest FX observation.

    Absent a rate the holding is reported unpriced rather than valued at par — see
    `pricing.value`.
    """
    from app.db.models import FxObservation

    needed = {p.currency for p in positions if p.currency != "INR"}
    if not needed:
        return {}
    out: dict[str, Decimal] = {}
    for currency in needed:
        row = db.execute(
            sa.select(FxObservation)
            .where(FxObservation.pair == f"{currency}INR")
            .order_by(FxObservation.observed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            out[currency] = row.rate
    return out


HANDLERS = {
    "record_transaction": record_transaction,
    "confirm_transaction": confirm_transaction,
    "get_portfolio": get_portfolio,
    "get_position": get_position,
    "record_price": record_price,
    "undo_transaction": undo_transaction,
}
