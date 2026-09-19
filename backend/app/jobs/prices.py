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

from app.db.models import User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services import notifications
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
    description="Tells you when a stock you hold announces a split, bonus or consolidation.",
    catch_up=dt.timedelta(hours=12),
)
def corporate_actions_watch(db: Session, user: User) -> JobResult:
    """Announce a share-changing action once, before it shows up as a phantom loss.

    The ledger is not touched. Parsing a ratio out of NSE's free text and writing it to an
    append-only record without anyone reading it is how a feed invents a holding.

    One action is announced per run. Two on one day for one person's handful of stocks is
    rare, and the second is announced the next evening — well before any ex-date.
    """
    try:
        actions = nse.corporate_actions()
    except ProviderError as exc:
        return JobResult(silent=True, detail={"failed": exc.reason})

    found = feed.share_changing_actions(db, actions)
    for inst, action in found:
        tag = f"corpaction-{inst.symbol}-{action.ex_date or 'undated'}"
        if notifications.already_said(db, user.id, "corporate_action", tag):
            continue
        when = f"ex-date {action.ex_date:%d %b %Y}" if action.ex_date else "date not given"
        return JobResult(
            notify=NotificationSpec(
                kind="corporate_action",
                title=f"{inst.symbol}: {action.purpose.strip().capitalize()}",
                body=(
                    f"{action.company}, {when}. Record it on the Investments page once it "
                    "happens, or the price change will read as a gain or loss that never "
                    "happened."
                ),
                url="/#investments",
                tag=tag,
            ),
            detail={"matched": len(found), "announced": inst.symbol},
        )
    return JobResult(silent=True, detail={"matched": len(found)})
