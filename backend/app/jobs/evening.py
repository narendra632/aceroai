"""The one run that thinks.

Every other scheduled job in this module is bookkeeping — record a close, read a filing, notice
an announcement. This one reads what all of that produced and decides whether anything is worth
suggesting.

⚠ **Proposing nothing is a normal and frequently correct outcome**, and it is recorded either
way. A system that only leaves a trace on the days it acted can never be measured against the
days it should have acted and did not, and the record becomes a highlight reel.

⚠ **It notifies at most once an evening**, and only when there is something to decide. A
notification for every company considered would be eleven a night, none of which asks anything
of the reader — which is how a channel stops being read before it has ever carried anything
urgent.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Instrument, User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services.errors import NotFound
from app.services.investments import proposals


@job(
    "evening_synthesis",
    # 21:00. After the Indian close is recorded, after the day's filings, and late enough that
    # anything arriving during the session has been seen. ⚠ Daily rather than on weekdays: a
    # weekend run reads the week's filings and usually proposes nothing, which is cheap.
    "0 21 * * *",
    description="Reads the day and decides whether anything is worth suggesting.",
    catch_up=dt.timedelta(hours=4),
)
def evening_synthesis(db: Session, user: User) -> JobResult:
    """Score every tracked company, apply the rules, and suggest — or say nothing.

    ⚠ The whole run is idempotent through `occurrence_key`, so a catch-up after a restart
    cannot write a second copy of the evening's suggestions. That matters more here than
    anywhere else in the module: a duplicated proposal is a duplicated decision to make.
    """
    key = dt.datetime.now(dt.UTC).astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    try:
        batch = proposals.synthesise(db, user.id, occurrence_key=f"{key:%Y-%m-%d}")
    except NotFound as exc:
        # No book yet on a fresh database. Not a failure, and recording one every evening
        # would make the job history worthless to read.
        return JobResult(silent=True, detail={"reason": str(exc)})
    db.commit()

    detail = batch.detail()
    if not batch.proposed:
        # ⚠ Silent, not absent. The `agent_runs` row is written regardless, so the evening is
        # on the record as one where nothing was worth suggesting.
        return JobResult(silent=True, detail=detail)

    first = batch.proposed[0]
    instrument = db.get(Instrument, first.instrument_id)
    symbol = instrument.symbol if instrument else "a holding"
    more = len(batch.proposed) - 1
    return JobResult(
        notify=NotificationSpec(
            kind="investment_proposal",
            title=(
                f"{symbol}: {first.action.lower().replace('_', ' ')}"
                + (f", and {more} other{'s' if more > 1 else ''}" if more else "")
            ),
            body=(
                "Nothing moves until you decide. Each one carries what it rests on and what "
                "would prove it wrong."
            ),
            url="/#investments",
            tag=f"proposals-{batch.batch_id}",
        ),
        detail=detail,
    )
