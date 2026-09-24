"""Register where the system reads from.

    uv run python -m app.scripts.seed_sources          # write it
    uv run python -m app.scripts.seed_sources --check  # report only, write nothing

Idempotent: a source already registered under the same handle is left exactly as it is,
including whether it has been approved.

⚠ **The exchange feeds arrive approved; the channels do not.** Reading what a company itself
told the exchange is not a judgement call — the module already reads NSE's bhavcopy for the
close of record and its corporate-action feed for splits, and an announcement feed is the same
record from the same registrar. A commentator is a different thing entirely: adding one
changes what the system can be talked into, so it lands unapproved and waits for you.

⚠ **What the candidate channels actually publish, measured rather than assumed.** Their last
fifteen uploads each were fetched and run through the matcher on 20 Sep 2026:

  * *Aswath Damodaran* — 15 uploads, **0** naming a tracked company. Valuation method, almost
    entirely US-listed examples. Worth reading; not an idea source for this portfolio.
  * *Yadnya Investment Academy* — 15 uploads, **0**. Active and Indian, but macro and
    personal finance rather than company calls.
  * *Zerodha* — 15 uploads, **0**. IPO explainers and product walkthroughs.
  * *Capitalmind* — the YouTube channel at that handle carries **two uploads, from 2006**. It
    is not the investing firm; their work is a newsletter, which this reads no better than a
    browser does. Registered as a link rather than a feed.

⚠ **That first measurement was of TITLES, and a title is advertising copy.** Re-measured on
24 Sep 2026 with the spoken words — 819 to 10,535 transcribed words per video:

  * *Yadnya* and *Zerodha* both publish **Hindi** captions, in Devanagari, even where the
    title is written in Latin. The deterministic matcher reads Latin-script names, so it sees
    nothing in them; `investments/spoken.py` transliterates and the exchange's register still
    decides what counts.
  * *Damodaran* publishes English, 6,000–8,600 words a video, and names no NSE-listed company
    across four recent uploads. His subject is method and his examples are American.

So the finding survives the better measurement, and now rests on what was actually said rather
than on what the thumbnails claimed. Which makes it a finding about the CHANNELS — and a
finding is only useful if the thing it is about can be changed, which is why channels are now
added, switched off and swapped from the Investments page rather than from this file.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.investments import reading
from app.services.marketdata import feeds

#: The exchange's own feeds. Tier 1: a company telling the exchange something IS the filing.
EXCHANGE = [
    (
        "announcements",
        "NSE announcements",
        "Every Reg-30 disclosure: orders won, plant commissioning, litigation, ratings.",
    ),
    ("results", "NSE results filings", "Quarterly and annual results as they are filed."),
    ("board_meetings", "NSE board meetings", "Board meeting intimations, with their purpose."),
    (
        "shareholding",
        "NSE shareholding patterns",
        "Quarterly shareholding. ⚠ Empty between quarters — that is the cadence, not a fault.",
    ),
    ("insider", "NSE insider trading", "Promoter and designated-person dealing disclosures."),
]

#: Commentary. ⚠ Tier 3, unapproved, and a proposal resting only on these fails its sourcing
#: gate whatever they say.
CHANNELS = [
    (
        "YOUTUBE",
        "Aswath Damodaran",
        "UCLvnJL8htRR1T9cbSccaoVw",
        "NYU Stern. Valuation method from the person who wrote it down. Measured 20 Sep 2026: "
        "0 of 15 recent uploads named a tracked company — a teaching source, not an idea one.",
    ),
    (
        "YOUTUBE",
        "Yadnya Investment Academy",
        "UCUWbS9qoyLKTdOlvgK1GBlA",
        "Indian retail research, daily cadence. Measured 20 Sep 2026: 0 of 15 recent uploads "
        "named a tracked company; the recent run is macro and personal finance.",
    ),
    (
        "YOUTUBE",
        "Zerodha",
        "UCjOVNkq-_HY9Q_LQv0FwlqA",
        "The broker's own channel — IPO breakdowns and market mechanics. Measured 20 Sep 2026: "
        "0 of 15 recent uploads named a tracked company.",
    ),
]


def run(db: Session, *, check: bool) -> dict:
    added: list[str] = []
    already: list[str] = []
    known = {(s.kind, s.handle) for s in reading.registered(db)}

    for handle, name, notes in EXCHANGE:
        label = f"[1] {name}"
        if ("RSS_EXCHANGE", handle) in known:
            already.append(label)
            continue
        if not check:
            reading.register(
                db,
                kind="RSS_EXCHANGE",
                name=name,
                handle=handle,
                trust_tier=reading.FILING,
                notes=notes,
                approved=True,
            )
        known.add(("RSS_EXCHANGE", handle))
        added.append(label)

    for kind, name, handle, notes in CHANNELS:
        label = f"[3] {name}  (needs your approval)"
        if (kind, handle) in known:
            already.append(f"[3] {name}")
            continue
        if not check:
            reading.register(
                db,
                kind=kind,
                name=name,
                handle=handle,
                trust_tier=reading.COMMENTARY,
                notes=notes,
                approved=False,
            )
        known.add((kind, handle))
        added.append(label)

    return {"added": added, "already": already}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args()

    with SessionLocal() as db:
        report = run(db, check=args.check)
        if not args.check:
            db.commit()

        for line in report["added"]:
            print(f"  registered  {line}")
        for line in report["already"]:
            print(f"  already     {line}")

        pending = [s for s in reading.registered(db) if s.approved_at is None]
        if pending:
            print(f"\n{len(pending)} sources are waiting for you to approve them:")
            for source in pending:
                print(f"  {source.name} - {source.notes}")
            print("\nApprove them on the Investments page, or leave them off. Nothing is read")
            print("from an unapproved source, so leaving them is a safe default.")

        readable = reading.registered(db, only_readable=True)
        print(f"\n{len(readable)} sources are readable now:")
        for source in readable:
            print(f"  [tier {source.trust_tier}] {source.name}")
        print(f"\nFeeds available in the adapter: {', '.join(sorted(feeds.NSE_FEEDS))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
