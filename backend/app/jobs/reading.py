"""Reading the world on a schedule.

One job. It polls every approved source, stores what is new, and writes down every tracked
company each item named.

⚠ **It notifies only about tier-1 filings on companies actually held, and only for the
subjects that change a business.** An exchange announcement feed carries several hundred items
a day; a job that pushed each one would be a job whose notifications are dismissed unread
within a week, and the one about a factory fire would be dismissed with them.

⚠ **Commentary never notifies at all.** A video naming a holding is a thing to read on a
schedule, not an interruption — and interrupting on it is how a channel ends up setting the
agenda for a portfolio.
"""

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import User
from app.jobs.registry import JobResult, job
from app.jobs.registry import Notification as NotificationSpec
from app.services.errors import NotFound
from app.services.investments import candidates, frameworks, reading

#: Reg-30 subjects worth being told about the same evening. ⚠ Deliberately short. Everything
#: else is still recorded and still appears in the reading list; it simply does not buzz.
MATERIAL = (
    "bagging/receiving of orders",
    "acquisition",
    "amalgamation",
    "merger",
    "demerger",
    "credit rating",
    "resignation",
    "fund raising",
    "allotment of securities",
    "fire",
    "plant",
    "commissioning",
    "litigation",
    "regulatory",
    "search",
    "seizure",
    "default",
    "resolution plan",
)


def _material(heard: reading.Heard) -> bool:
    text = (heard.excerpt or "").lower()
    return heard.is_held and heard.trust_tier == reading.FILING and any(k in text for k in MATERIAL)


@job(
    "sources_poll",
    # ⚠ **The last run of the day is at 23:10, and it is not padding.** NSE's announcement
    # feed is a WINDOW that empties: it held 56 items at 23:40 on 20 Sep 2026 and 0 the next
    # morning. Anything filed after the previous poll and before that reset is gone for good,
    # because a feed with no history cannot be asked again. Companies file late — the 21:41
    # and 23:41 items on that Saturday were both real disclosures — so the day closes with a
    # poll after them rather than before.
    "10 8,12,16,20,23 * * *",
    description="Reads exchange filings and approved channels, and notes every company named.",
    # ⚠ Shorter than the SHORTEST gap between runs (20:10 to 23:10), which the registry
    # insists on: a catch-up longer than the interval can never fire, because the next
    # scheduled run arrives first.
    catch_up=dt.timedelta(hours=2),
)
def sources_poll(db: Session, user: User) -> JobResult:
    """Poll every readable source and record what it said.

    ⚠ One commit at the end. A poll that committed per source would leave a half-read round
    behind on a failure, and the next run would treat the items it had already stored as
    seen — which is the one way this design could silently lose a filing.
    """
    results = reading.poll_all(db)
    db.commit()

    stored = sum(r.stored for r in results)
    mentions = sum(r.mentions for r in results)
    detail = {
        "sources": len(results),
        "stored": stored,
        "mentions": mentions,
        "silent": [r.source for r in results if r.silent],
        "failed": {r.source: r.error for r in results if r.error},
        "named": sorted({name for r in results for name in r.names}),
    }

    if not mentions:
        return JobResult(silent=True, detail=detail)

    worth_saying = [h for h in reading.recent(db, days=1, limit=20) if _material(h)]
    if not worth_saying:
        return JobResult(silent=True, detail=detail)

    lead = worth_saying[0]
    others = len(worth_saying) - 1
    title = f"{lead.symbol}: a filing worth reading"
    body = lead.excerpt or lead.source
    if others:
        body = f"{body} (+{others} more)"

    return JobResult(
        detail=detail,
        notify=NotificationSpec(
            kind="investments_filing",
            title=title,
            body=body[:300],
            url="/#investments",
            # ⚠ One tag per day, so four polls replace one another on the device instead of
            # stacking into a column nobody reads.
            tag=f"filings-{dt.date.today().isoformat()}",
        ),
    )


@job(
    "universe_sync",
    # Weekly, Sunday morning. The exchange's list changes by a handful of names a month —
    # listings, delistings, renames — and a stale entry costs a missed match, not a wrong one.
    "30 6 * * sun",
    description="Refreshes the list of listed companies the reader recognises names with.",
    catch_up=dt.timedelta(days=2),
)
def universe_sync(db: Session, user: User) -> JobResult:
    """Keep the vocabulary current.

    ⚠ Silent by design. Nobody needs telling that the exchange listed four companies this
    week, and a job that notified on it would be teaching its reader to dismiss notifications.
    """
    report = reading.sync_universe(db)
    db.commit()
    return JobResult(silent=True, detail=report)


@job(
    "candidate_analysis",
    # 20:30, half an hour before the evening synthesis — so anything the day's reading turned
    # up has already been placed, read and scored by the time proposals are formed.
    "30 20 * * *",
    description="Reads the filings of companies your sources named, and places them.",
    uses_ai=True,
    catch_up=dt.timedelta(hours=2),
)
def candidate_analysis(db: Session, user: User) -> JobResult:
    """Take the next few queued candidates through placement, filings and scoring.

    ⚠ A few, not all. Each costs a model call and several filing fetches, and a queue that
    suddenly gained forty names would otherwise spend an evening's whole budget on companies
    nobody has looked at yet.

    ⚠ Silent. A company having been read is not news — what it turned out to be worth is, and
    that reaches you through the research queue and the evening's proposals rather than as an
    interruption of its own.
    """
    try:
        version = frameworks.current(db)
    except NotFound:
        return JobResult(silent=True, detail={"reason": "no approved framework yet"})

    results = candidates.analyse_pending(db, version.spec, version.id)
    db.commit()

    if not results:
        return JobResult(silent=True, detail={"analysed": 0})

    return JobResult(
        silent=True,
        detail={
            "analysed": len(results),
            "placed": {r.symbol: r.bottleneck_id for r in results if r.bottleneck_id},
            "unplaced": [r.symbol for r in results if not r.bottleneck_id],
            "scores": {
                r.symbol: f"{r.quality_earned}/{r.quality_available}"
                for r in results
                if r.is_scoreable
            },
        },
    )
