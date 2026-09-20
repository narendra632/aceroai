"""Market data on a schedule: the day's closes, overnight prices, and corporate actions.

The price jobs never notify. A source that fails leaves its holdings on their last price,
and the page already shows that price's age and marks it stale — which is the right place
for the news, because it is where the stale number is being read. A push saying "a feed was
down for an hour" is exactly the kind of alert that trains its reader to ignore alerts.

⚠ The first run of each price job on a database with no prices **is** the backfill: it fills
every missing day since the first trade (see `marketdata.feed`). Nothing to run by hand on
the server.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Instrument, User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services.errors import NotFound
from app.services.investments import corpactions, overview
from app.services.marketdata import feed, nse
from app.services.marketdata.http import ProviderError


@job(
    "prices_india_close",
    # 19:00. NSE publishes the bhavcopy between roughly 17:30 and 18:30; an hour of margin
    # costs nothing, and a file not yet out is simply fetched again tomorrow.
    "0 19 * * mon-fri",
    description="Records the day's closing prices for your Indian stocks, from NSE.",
    catch_up=dt.timedelta(hours=12),
)
def prices_india_close(db: Session, user: User) -> JobResult:
    return JobResult(silent=True, detail=feed.fill_closes(db, ("NSE",)).detail())


@job(
    "prices_daily",
    # 07:30. After the US close (01:30/02:30 IST), after AMFI's 23:00 NAV deadline, and
    # before anyone looks at the portfolio in the morning.
    "30 7 * * *",
    description="Records overnight prices: US stocks, the dollar rate, fund NAVs and crypto.",
    catch_up=dt.timedelta(hours=12),
)
def prices_daily(db: Session, user: User) -> JobResult:
    return JobResult(silent=True, detail=feed.fill_closes(db, ("MF", "US", "CRYPTO")).detail())


@job(
    "corporate_actions_watch",
    # 20:00, after the evening's filings. Actions are announced days to weeks before their
    # ex-date, so a daily look is ample.
    "0 20 * * mon-fri",
    description="Records splits and bonuses on your stocks, and applies them on the ex-date.",
    catch_up=dt.timedelta(hours=12),
)
def corporate_actions_watch(db: Session, user: User) -> JobResult:
    """Record what the exchange announced, apply what has fallen due, and say so once.

    Three steps, in this order and for this reason:

    1. **Record.** Every share-changing announcement on a held stock becomes a row — PENDING
       when its ratio could be read without ambiguity, NEEDS_REVIEW when it could not. Either
       way the holding is flagged from that moment, so the page stops presenting its profit
       and loss as reliable before the price ever moves.
    2. **Apply.** On the ex-date the quantity change is written into the ledger, which is what
       stops a 1:1 bonus reading as a 50% loss. ⚠ Only where the ratio was unambiguous; an
       announcement that could mean two things is never resolved by guessing, because the
       wrong guess is a larger fiction than the one being fixed.
    3. **Say so.** One notification per run. Applied changes take precedence over new
       announcements: a quantity that has already moved is the more urgent thing to check.

    The whole job is wrapped so a failed feed leaves the ledger untouched and reports the
    reason, rather than half-applying a batch.
    """
    try:
        book = overview.real_book(db, user.id)
    except NotFound:
        # ⚠ A database with no book yet is not a failure. Without this the job would record
        # an error every weekday evening on a fresh install, which is how a `job_runs` table
        # stops being worth reading.
        return JobResult(silent=True, detail={"reason": "no REAL book yet"})

    recorded: list = []
    failed: str | None = None
    try:
        found = feed.share_changing_actions(db, nse.corporate_actions())
    except ProviderError as exc:
        # An unreachable feed is not an absence of actions. Anything already recorded is
        # still applied below, because its ex-date does not wait for the feed to come back.
        failed = exc.reason
    else:
        recorded = corpactions.ingest(db, found)

    applied = []
    for action in corpactions.due(db):
        txn = corpactions.apply(db, book.id, action)
        if txn is not None:
            applied.append(action)
    db.commit()

    detail = {
        "recorded": len(recorded),
        "applied": len(applied),
        "needs_review": sum(1 for a in recorded if a.status == "NEEDS_REVIEW"),
    }
    if failed:
        detail["failed"] = failed

    if applied:
        action = applied[0]
        instrument = db.get(Instrument, action.instrument_id)
        symbol = instrument.symbol if instrument else "a holding"
        return JobResult(
            notify=NotificationSpec(
                kind="corporate_action",
                title=f"{symbol}: {corpactions.ratio_text(action) or action.action_type.lower()}",
                body=(
                    "Your holding has been adjusted, so the price change is not a gain or "
                    "loss. Check it against your broker — the entry is in the history and "
                    "can be withdrawn."
                ),
                url="/#investments",
                tag=f"corpaction-applied-{action.id}",
            ),
            detail=detail,
        )

    for action in recorded:
        instrument = db.get(Instrument, action.instrument_id)
        symbol = instrument.symbol if instrument else "a holding"
        when = f"ex-date {action.ex_date:%d %b %Y}" if action.ex_date else "date not yet fixed"
        needs_review = action.status == "NEEDS_REVIEW"
        return JobResult(
            notify=NotificationSpec(
                kind="corporate_action",
                title=f"{symbol}: {action.purpose.strip().capitalize()}",
                body=(
                    f"{when}. "
                    + (
                        "The announcement could not be read precisely enough to apply it, so "
                        "record the change yourself on the Investments page."
                        if needs_review
                        else "It will be applied to your holding on the ex-date."
                    )
                ),
                url="/#investments",
                tag=f"corpaction-{action.id}",
            ),
            detail=detail,
        )

    return JobResult(silent=True, detail=detail)
