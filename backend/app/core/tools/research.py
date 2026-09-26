"""The research half of the Investments module, reachable from a conversation.

`tools/investments.py` covers the ledger: what is held, what it cost, what it is worth. This
covers everything above that — what was scored, what was suggested, what was refused and why,
what the sources said, what was predicted, and whether any of it is working.

⚠ **Almost all of it is read-only, and the one exception is a two-step.** A decision on a
suggestion is the row the whole system is eventually graded on: `decisions` and `claims` are
what `verdict` measures, so a model that could approve on the user's behalf would be writing
its own report card. `decide_suggestion` therefore returns a *draft* and `confirm_decision`
writes it, the same shape `record_transaction`/`confirm_transaction` already uses for the
ledger and for the same reason.

⚠ **Nothing here scores, ranks or recommends.** Every figure is computed by
`services/investments` and read back out. If a number is wrong it is wrong in one place, and
the page and the chat are wrong together rather than differently — which is convention 2, and
the reason a rule is never implemented twice.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Claim, Instrument, Portfolio, Proposal
from app.services.errors import Invalid, NotFound
from app.services.investments import (
    benchmarks,
    entry,
    framework_data,
    frameworks,
    pricing,
    proposals,
    reading,
    scoring,
    verdict,
)

#: Decisions awaiting confirmation, keyed by a short handle the model quotes back. In memory
#: rather than in the database for the same reason transaction drafts are: a draft is a
#: half-finished sentence in a conversation, not a fact about the record.
_PENDING: dict[str, tuple[uuid.UUID, str, str, Decimal | None]] = {}

#: How many rows a list tool returns before it stops. A chat answer nobody reads to the end is
#: the same as no answer, and the model re-asks with a filter when it needs more.
LIMIT = 12


def _mirror(db: Session, user_id: uuid.UUID) -> Portfolio:
    return proposals.mirror(db, user_id)


def _spec(db: Session) -> dict:
    try:
        return frameworks.current(db).spec
    except NotFound:
        return framework_data.spec()


def _money(value) -> str | None:
    return str(round(value, 2)) if value is not None else None


SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_suggestions",
            "description": (
                "What the system suggested and what it refused, with the rule that refused it. "
                "Use for 'did it suggest anything', 'why is nothing being suggested', 'what "
                "was blocked', or any question about buying or adding. A refusal is a real "
                "answer here: most nights everything is blocked, usually because nothing is "
                "cheap enough, and that is the system working rather than failing."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_company",
            "description": (
                "The full scorecard for one company: every component of its quality score with "
                "the reason for each, which red flags stand, which box it sits in, where the "
                "framework places it, and how deep the reading is. Use for 'why is X scored "
                "like that', 'is X any good', 'why is X blocked', or any question about a "
                "single company's assessment."
            ),
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
            "name": "get_research_queue",
            "description": (
                "Companies that sources named which the user does not follow — the research "
                "queue. Use for 'what's new', 'any new ideas', 'what came out of the channels'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reading",
            "description": (
                "Where the system reads from and what those sources named lately, plus how "
                "each source has actually performed. Use for 'what did my channels say', "
                "'which sources are worth reading', 'what's in the news about my holdings'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_predictions",
            "description": (
                "The falsifiable predictions the system has made, open and settled, and how "
                "many came true. Use for 'what has it predicted', 'is it any good at this', "
                "'what's it committed to'. These are written when a thesis is formed and can "
                "never be edited afterwards — they are the point of the whole module."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_benchmarks",
            "description": (
                "How the portfolio has done against index funds over the same period. Use for "
                "'am I beating the index', 'is this worth it', 'how am I doing really'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_verdict",
            "description": (
                "The six pre-committed go/no-go criteria and where each stands. Use for 'is "
                "this working', 'should I keep doing this', 'what's the verdict'. Criteria "
                "that are not yet testable say so — 'not yet' is different from 'failed'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decide_suggestion",
            "description": (
                "Prepare a decision on an open suggestion — approve, reject or modify — with "
                "the user's reason in their own words. Returns what WOULD be recorded and "
                "writes nothing; call confirm_decision to record it. Never invent the reason: "
                "it is the data that eventually shows what kinds of suggestion keep being "
                "turned down, so ask the user for it if they have not given one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "outcome": {
                        "type": "string",
                        "enum": ["APPROVE", "REJECT", "MODIFY"],
                    },
                    "reason": {
                        "type": "string",
                        "description": "The user's own words on why. Required.",
                    },
                    "modified_amount_inr": {
                        "type": "string",
                        "description": "Only for MODIFY: the amount the user wants instead.",
                    },
                },
                "required": ["symbol", "outcome", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_decision",
            "description": (
                "Record a decision prepared by decide_suggestion, after the user has confirmed "
                "it. Takes the handle that call returned."
            ),
            "parameters": {
                "type": "object",
                "properties": {"handle": {"type": "string"}},
                "required": ["handle"],
            },
        },
    },
]


# --- reading ---------------------------------------------------------------------------------


def get_suggestions(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    """Open suggestions, and the refusals — which are usually the whole story."""
    book = _mirror(db, user_id)
    rows = proposals.recent(db, book.id, limit=40)
    symbols = dict(
        db.execute(
            sa.select(Instrument.id, Instrument.symbol).where(
                Instrument.id.in_({r.instrument_id for r in rows})
            )
        ).all()
    )

    open_rows, blocked = [], []
    # ⚠ The newest word on each company, once. The run reconsiders every company every night,
    # so "the last forty suggestions" is three nights of the same twelve names — and an answer
    # listing Apar three times reads as three separate refusals rather than one standing one.
    seen: set[uuid.UUID] = set()
    for row in rows:
        if row.instrument_id in seen:
            continue
        seen.add(row.instrument_id)
        state = proposals.effective_status(db, row)
        entry_out = {
            "symbol": symbols.get(row.instrument_id),
            "action": row.action,
            "amount_inr": _money(row.target_amount_inr),
            "confidence": str(row.confidence) if row.confidence is not None else None,
            "quadrant": row.quadrant,
            "quality": f"{row.quality_earned} of {row.quality_available}",
            "raised_on": row.created_at.date().isoformat(),
        }
        if state == "BLOCKED":
            if len(blocked) < LIMIT:
                entry_out["blocked_by"] = row.blocked_by
                entry_out["thesis"] = (row.thesis or "")[:600]
                blocked.append(entry_out)
        elif state == "PENDING":
            entry_out["thesis"] = (row.thesis or "")[:900]
            open_rows.append(entry_out)

    return {
        "open": open_rows,
        "blocked": blocked,
        "note": (
            "A blocked suggestion was never offered and cannot be decided on. Most are blocked "
            "by G3_margin_of_safety, which means the company is good and the price is not — "
            "that is the rules working, not a fault. Its prediction is still recorded."
        ),
    }


def explain_company(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    """Everything the system thinks about one company, and why."""
    inst = entry.find_instrument(db, str(args["symbol"]).strip())
    if inst is None:
        raise NotFound(f"nothing held or tracked called {args['symbol']!r}")

    spec = _spec(db)
    mark = pricing.latest(db, [inst.id]).get(inst.id)
    # ⚠ The same assessment the page shows, not a second computation of it. An earlier version
    # scored here with no market value and reflexivity hard-coded off, so the assistant called
    # every company BORDERLINE with its margin of safety unread while the page beside it said
    # Q1 and Q3 — for the same company, at the same moment.
    assessed = scoring.assess(db, inst, spec, price=mark.price if mark else None)
    quality, flags = assessed.quality, assessed.flags
    mapping = frameworks.live_mapping(db, inst.id)

    return {
        "symbol": inst.symbol,
        "name": inst.name,
        "sector": inst.sector,
        "price": str(mark.price) if mark else None,
        "price_age": mark.age_text if mark else None,
        "score": f"{quality.earned} of {quality.available}",
        "score_out_of_possible": str(quality.possible),
        "coverage": f"{quality.coverage:.0%}" if quality.coverage is not None else None,
        "quadrant": assessed.quadrant,
        "market_value_inr": _money(assessed.market_cap),
        "years_read": quality.years_read,
        "years_possible": quality.history.obtainable if quality.history else None,
        "depth_note": (quality.history.why() if quality.history else "") or None,
        "components": [
            {
                "name": part.name,
                # ⚠ Three different renderings for three different facts, and the model must
                # keep them apart when it speaks: a number was measured, "not read" is a gap
                # in the filings, "does not apply" is a test that never described this kind of
                # company and is not a gap anyone can fill.
                "points": (
                    "does not apply"
                    if not part.applicable
                    else "not read"
                    if part.points is None
                    else f"{part.points} of {part.available}"
                ),
                "why": part.detail,
            }
            for part in quality.parts
        ],
        "flags_standing": [
            {"number": f.number, "question": f.question, "evidence": f.evidence}
            for f in flags
            if f.verdict == "YES"
        ],
        "flags_unknown": [f.number for f in flags if f.verdict == "UNKNOWN"],
        "framework": (
            {
                "bottleneck": mapping.b_bottleneck,
                "approved": mapping.approved_at is not None,
                "off_framework": mapping.off_framework,
                "rationale": mapping.rationale,
            }
            if mapping
            else None
        ),
        "note": (
            "earned and available must be quoted together — six of six is excellent and six "
            "of ten is mediocre, and the difference is only how much has been read"
        ),
    }


def get_research_queue(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    rows = reading.queue(db)
    return {
        "waiting": [
            {
                "symbol": row.symbol,
                "name": row.name,
                "status": row.status,
                "first_seen": row.first_seen_at.date().isoformat(),
                "named_by": row.named_by,
                "times_named": row.mention_count,
                "waiting_days": row.age_days,
                "said": row.excerpt,
                "proposed_bottleneck": row.proposed_bottleneck,
            }
            for row in rows[:LIMIT]
        ],
        "total": len(rows),
        "note": (
            "A queue line is a LEAD, never a recommendation. Nothing here has been bought, "
            "and a company arrives here because a source named it, not because it is good."
        ),
    }


def get_reading(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    sources = reading.registered(db)
    return {
        "sources": [
            {
                "name": s.name,
                "kind": s.kind,
                "trust": {1: "filing", 2: "press", 3: "commentary"}.get(s.trust_tier, "unknown"),
                "approved": s.approved_at is not None,
                "active": s.is_active,
                "last_read": s.last_polled_at.date().isoformat() if s.last_polled_at else None,
            }
            for s in sources
        ],
        "heard": [
            {
                "symbol": h.symbol,
                "held": h.is_held,
                "stance": h.stance,
                "source": h.source,
                "said": h.excerpt,
                "on": h.published_at.date().isoformat() if h.published_at else None,
            }
            for h in reading.recent(db, days=30)[:LIMIT]
        ],
        "attribution": [
            {
                "source": a.source,
                "named": a.named,
                "became_proposals": a.became_proposals,
                "hit_rate": str(a.hit_rate.value) if a.hit_rate.value is not None else None,
                "note": a.hit_rate.note,
            }
            for a in reading.attributions(db)
        ],
        "note": (
            "Evidence from commentary alone (trust 'commentary') can never carry a suggestion "
            "on its own — the sourcing gate refuses it whatever the commentary said."
        ),
    }


def get_predictions(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    """The falsifiable record — the thing the whole module exists to accumulate."""
    rows = db.execute(
        sa.select(Claim, Instrument.symbol, Proposal.blocked_by)
        .join(Proposal, Claim.proposal_id == Proposal.id)
        .join(Instrument, Proposal.instrument_id == Instrument.id)
        .order_by(Claim.due_by)
    ).all()

    settled = [r for r in rows if r[0].status in ("TRUE", "FALSE")]
    true = sum(1 for r in settled if r[0].status == "TRUE")
    return {
        "open": [
            {
                "symbol": symbol,
                "claim": claim.claim_text,
                "due_by": claim.due_by.isoformat(),
                "from": "a blocked idea" if blocked else "an offered suggestion",
            }
            for claim, symbol, blocked in rows
            if claim.status == "OPEN"
        ][:LIMIT],
        "open_total": sum(1 for r in rows if r[0].status == "OPEN"),
        "settled_total": len(settled),
        "came_true": true,
        "recently_settled": [
            {
                "symbol": symbol,
                "claim": claim.claim_text,
                "result": claim.status,
                "evidence": claim.resolved_evidence,
            }
            for claim, symbol, _ in sorted(
                settled, key=lambda r: r[0].resolved_at or dt.datetime.min, reverse=True
            )[:6]
        ],
        "note": (
            "Predictions are recorded whether or not the gates let the idea through, because "
            "calibration is a property of the judgement and not of the purchases. Each is "
            "frozen when the thesis is formed and can never be edited afterwards."
        ),
    }


def get_benchmarks(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    start = dt.date.today() - dt.timedelta(days=365)
    c = benchmarks.compare(db, user_id, start=start)
    return {
        "from": c.start.isoformat(),
        "to": c.end.isoformat(),
        "portfolio_pct": str(c.portfolio_pct) if c.portfolio_pct is not None else None,
        "blended_pct": str(c.blended_pct) if c.blended_pct is not None else None,
        "alternatives": [
            {
                "name": line.name,
                # ⚠ Said out loud. A benchmark that stands in for something else has to
                # announce it, or a comparison against the proxy reads as a comparison
                # against the index itself.
                "proxy_for": line.proxy_for,
                "return_pct": str(line.change_pct) if line.change_pct is not None else None,
                "detail": line.detail,
            }
            for line in c.lines
        ],
        # ⚠ False means the two sides were not measured over the same window, and a return
        # over one period against an index over another is not a comparison at all.
        "readable": c.readable,
        "detail": c.detail,
        "non_equity_share": str(c.non_equity_share),
        "caveat": c.caveat,
        "note": (
            "The alternative is an index FUND, not an index — an index cannot be bought, and "
            "a fund's NAV carries the fees a real alternative would have charged. If readable "
            "is false, or a caveat is present, say so before quoting any number."
        ),
    }


def get_verdict(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    result = verdict.assess(db, user_id)
    return {
        "criteria": [
            {
                "key": c.key,
                "question": c.question,
                # ⚠ Three states, and the model must not flatten them. None is "not yet
                # testable", which is a completely different claim from "failed".
                "status": "met" if c.met else ("not met" if c.met is False else "not yet"),
                "value": str(c.value),
                "target": c.target,
                "detail": c.detail,
                "sample": c.n,
            }
            for c in result.criteria
        ],
        "note": (
            "These were written down before any of them could be measured, which is the only "
            "reason they mean anything. 'Not yet' is not a failure and must never be reported "
            "as one."
        ),
    }


# --- the one write, in two steps --------------------------------------------------------------


def decide_suggestion(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    """Prepare a decision. ⚠ Writes nothing — see the module docstring for why."""
    outcome = str(args.get("outcome", "")).strip().upper()
    if outcome not in ("APPROVE", "REJECT", "MODIFY"):
        raise Invalid("a decision is approve, reject or modify")
    reason = str(args.get("reason", "")).strip()
    if not reason:
        raise Invalid("a decision needs a reason in the user's own words")

    inst = entry.find_instrument(db, str(args["symbol"]).strip())
    if inst is None:
        raise NotFound(f"nothing held or tracked called {args['symbol']!r}")

    book = _mirror(db, user_id)
    row = next(
        (p for p in proposals.open_proposals(db, book.id) if p.instrument_id == inst.id), None
    )
    if row is None:
        raise NotFound(
            f"there is no open suggestion for {inst.symbol} — it may have been blocked by a "
            "rule, already decided, or lapsed"
        )

    amount = args.get("modified_amount_inr")
    modified = Decimal(str(amount)) if outcome == "MODIFY" and amount else None

    handle = uuid.uuid4().hex[:6]
    _PENDING[handle] = (row.id, outcome, reason, modified)
    return {
        "handle": handle,
        "symbol": inst.symbol,
        "action": row.action,
        "outcome": outcome,
        "reason": reason,
        "amount_inr": _money(modified if modified is not None else row.target_amount_inr),
        "confirm_with": "confirm_decision",
        "note": (
            "Nothing has been recorded. Read this back and ask the user to confirm. Approving "
            "fills the paper book only — the real ledger is never written by a machine, so if "
            "they actually buy, they record that separately."
        ),
    }


def confirm_decision(db: Session, user_id: uuid.UUID, args: dict) -> dict:
    handle = str(args.get("handle", "")).strip()
    pending = _PENDING.get(handle)
    if pending is None:
        raise NotFound("that decision was not found — prepare it again with decide_suggestion")

    proposal_id, outcome, reason, modified = pending
    row = db.get(Proposal, proposal_id)
    book = _mirror(db, user_id)
    # An id is not an authorisation — the same rule the HTTP route follows.
    if row is None or row.portfolio_id != book.id:
        _PENDING.pop(handle, None)
        raise NotFound("that suggestion no longer exists")

    proposals.decide(
        db,
        row,
        user_id=user_id,
        outcome=outcome,
        reason=reason,
        modified_amount_inr=modified,
        via="CHAT",
    )
    db.commit()
    _PENDING.pop(handle, None)
    return {
        "recorded": True,
        "outcome": outcome,
        "note": (
            "Recorded, and it cannot be edited. Its invalidation conditions are now armed, so "
            "the system will say something if one of them comes true."
        ),
    }


HANDLERS = {
    "get_suggestions": get_suggestions,
    "explain_company": explain_company,
    "get_research_queue": get_research_queue,
    "get_reading": get_reading,
    "get_predictions": get_predictions,
    "get_benchmarks": get_benchmarks,
    "get_verdict": get_verdict,
    "decide_suggestion": decide_suggestion,
    "confirm_decision": confirm_decision,
}
