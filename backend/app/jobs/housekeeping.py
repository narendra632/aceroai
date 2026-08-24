"""Jobs nobody sees.

`retention_sweep` is deliberately the first job this project has, because it has no model
call, no notification and no interface — so it exercises the scheduling machinery and
nothing else.

It also fixes a real defect rather than adding a feature. Retention used to run off the back
of a delivered reply, gated by an in-memory flag, which meant three things:

  - a week without messaging Acero was a week with nothing pruned,
  - it took DELETE locks on `turns`/`spans` while the app was in use, so its 3-second
    `lock_timeout` usually made it give up rather than do the work,
  - the state was memory-only, so every deploy re-armed it.

03:15 fixes all three. It is also the only job with `catch_up=None` — "however late" —
because sweeping late is strictly better than not sweeping at all. That is the opposite of a
morning brief, where late delivery is worse than silence, and it is exactly why that value
has to be stated out loud rather than reached by choosing a large number.
"""

import logging

from sqlalchemy.orm import Session

from app.db.models import User
from app.jobs.registry import JobResult, job
from app.services import retention

log = logging.getLogger(__name__)


@job(
    "retention_sweep",
    "15 3 * * *",
    description="Rolls yesterday's costs into permanent totals and prunes old traces.",
    # However late. Housekeeping deferred is housekeeping that still needs doing.
    catch_up=None,
)
def retention_sweep(db: Session, user: User) -> JobResult:
    counts = retention.sweep(db)
    counts["notifications_pruned"] = retention.prune_notifications(db)
    # Silent when there was nothing to prune, which is the common case on a quiet week and
    # must not read as a failure in `job_runs`.
    did_something = any(counts.values())
    return JobResult(detail=counts, silent=not did_something)
