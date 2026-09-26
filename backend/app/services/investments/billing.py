"""Every model call the Investments module makes goes through here, and is paid for.

⚠ **Five call sites spent money and none of them said so.** Placing a company on a bottleneck,
reading the direction of a mention, answering a checklist question and then answering it again
to check, and transliterating a Hindi transcript each called the model directly, passed no
usage dict, and recorded nothing. Three consequences, found in review rather than in a bill:

1. **Insights under-reported spend.** Every background model call in the module was invisible
   on the page that exists to show what things cost.
2. **The monthly budget could not stop it.** The budget sums recorded spend; spend that is
   never recorded is spend it cannot see, so the ceiling was a ceiling on chat alone.
3. **The reading poll was not even asked.** It is not marked as an AI job — its main work, the
   exchange's filings, is free and must keep flowing whatever the budget says — so the runner
   skipped the budget check for it entirely, and a model call per Hindi video went through
   unconditionally.

So the budget is checked **per call**, not per job. Over the limit, the call raises before any
money moves, and every caller already degrades on failure to the honest state: a stance
becomes "mention only", a transliteration returns no names, a placement leaves the company
unmapped, a checklist verdict becomes UNKNOWN. The free work — the filings, the deterministic
matcher, the mention register — carries on, which is the right way round: a budget is a limit
on spending, not on reading.
"""

from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa

from app.config import settings
from app.core import llm, telemetry
from app.db.models import User
from app.db.session import SessionLocal
from app.services import budget

log = logging.getLogger(__name__)


def _payer() -> uuid.UUID | None:
    """Who this call is on behalf of.

    The job runner names them. Outside a job — a route handler, a script — this is a
    single-user application, so the one user is the payer. ⚠ Where there is more than one and
    nobody was named, the call is not attributed rather than attributed to the wrong person:
    a bill sent to a guess is worse than one not sent.
    """
    named = telemetry.billed_user.get()
    if named is not None:
        return named
    db = SessionLocal()
    try:
        ids = db.execute(sa.select(User.id).limit(2)).scalars().all()
    finally:
        db.close()
    return ids[0] if len(ids) == 1 else None


def _within_budget(user_id: uuid.UUID) -> None:
    """Raise `BudgetExceeded` if this month's allowance is already spent."""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is not None:
            budget.check(db, user)
    finally:
        db.close()


async def complete(messages: list[dict], *, effort: str, purpose: str) -> str:
    """One model call, checked against the budget before it is made and recorded after.

    `purpose` names the stage on the trace, so Insights can say what the money bought —
    "stance" and "transliterate" are different questions about whether a feature is worth it.
    """
    payer = _payer()
    if payer is not None:
        _within_budget(payer)

    tl = telemetry.Timeline()
    usage: dict = {}
    ok, error_type = True, None
    try:
        with tl.stage(purpose):
            return await llm.complete(messages, effort=effort, usage=usage)
    except Exception as exc:
        ok, error_type = False, type(exc).__name__
        raise
    finally:
        if payer is not None:
            await telemetry.record(
                tl,
                payer,
                "job",
                channel="job",
                provider=settings.llm_provider,
                model=settings.model_chat,
                effort=effort,
                usage=usage,
                ok=ok,
                error_type=error_type,
            )
