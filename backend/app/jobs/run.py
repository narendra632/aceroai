"""Trigger a job by hand.

    uv run python -m app.jobs.run                    # one tick, exactly as the scheduler does
    uv run python -m app.jobs.run day_end_summary    # that job, if its occurrence is due
    uv run python -m app.jobs.run day_end_summary -f # that job, now, regardless

Deliberately the **same code path** as the scheduler — `run_job` either way — so there is
one implementation to trust rather than a production path and a debugging path that drift
apart. `--force` bypasses the already-ran check and the enabled check, and nothing else:
the advisory lock, the timeouts, the budget check and the recording all still apply.
"""

import argparse
import sys

from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal
from app.jobs import registry, runner

# Importing the package registers every job. Without this the registry is empty and the
# command reports "unknown job" for a job that plainly exists.
import app.jobs  # noqa: F401  isort:skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a scheduled job by hand.")
    parser.add_argument("job", nargs="?", help="job name; omit to run one full tick")
    parser.add_argument(
        "-f", "--force", action="store_true", help="run even if not due or disabled"
    )
    parser.add_argument("--list", action="store_true", help="list registered jobs and exit")
    args = parser.parse_args(argv)

    if args.list:
        for entry in registry.all_jobs():
            ai = " [ai]" if entry.uses_ai else ""
            default = "on" if entry.default_on else "off"
            print(f"{entry.name:20s} {entry.schedule:14s} default={default}{ai}")
            print(f"{'':20s} {entry.description}")
        return 0

    db = SessionLocal()
    try:
        user = db.execute(select(User).order_by(User.created_at)).scalars().first()
        if user is None:
            print("no user exists yet", file=sys.stderr)
            return 1

        if args.job is None:
            for name, status in runner.tick(db, user).items():
                print(f"{name:20s} {status}")
            return 0

        entry = registry.get(args.job)
        if entry is None:
            known = ", ".join(j.name for j in registry.all_jobs())
            print(f"unknown job {args.job!r}. known: {known}", file=sys.stderr)
            return 1

        now = runner.now_local()
        occurrence = runner.most_recent_occurrence(entry, now)
        if occurrence is None:
            if not args.force:
                print(f"{entry.name}: nothing due within {entry.catch_up}; use --force")
                return 0
            occurrence = now
        key = runner.occurrence_key(occurrence)
        status = runner.run_job(db, entry, user, key, force=args.force)
        print(f"{entry.name:20s} {key}  ->  {status}")
        return 0 if status not in {"failed"} else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
