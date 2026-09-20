"""What the machine underneath the application is doing right now.

Acero runs on a 1 GB / 10 GB e2-micro with no database backup. The numbers that decide
whether that remains a safe bet — how much disk is left, how much memory the kernel thinks a
new process could get, how fast the database is growing — were previously visible only over
SSH, which means visible only when something had already gone wrong.

Two rules shape everything here.

**A reading that cannot be taken is `None`, never a zero.** `/proc` does not exist on Windows,
so on the development machine memory and load are simply absent, and the interface omits them.
A zero would be worse than a gap: it is a wrong answer wearing the same confidence as a right
one, and "0% memory pressure" is the most reassuring possible way to say "I have no idea".

**One unreadable source degrades one field, never the response.** Every reader is isolated,
because this endpoint is polled every ten seconds and a monitoring surface that can itself
fail loudly is worse than no monitoring surface.

There is one reading here that nothing else in the system could ever give you: `last_tick`. If
the scheduler stops, no request fails, no log line appears and no job reports an error —
scheduled work simply stops happening, and the first evidence is a morning brief that never
arrives. An absence is the hardest thing for a system to notice about itself, so it is stated
as a number instead.
"""

import datetime as dt
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

#: Bound to names so tests can point them somewhere that does not exist, which is the only
#: honest way to exercise the "cannot measure" path on a machine where they do exist.
MEMINFO = Path("/proc/meminfo")
LOADAVG = Path("/proc/loadavg")

#: The filesystem whose fullness matters. Inside the container this is the overlay, which
#: reports the host's disk — the number wanted, and verified on deployment rather than
#: assumed here.
DISK_PATH = "/"

#: Set once, at import. The process start time is the only uptime that means anything to a
#: reader asking "did something restart without me noticing".
_STARTED_AT = dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class Capacity:
    """A used/total pair, plus the percentage nobody should have to compute twice."""

    used_bytes: int
    total_bytes: int

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return self.used_bytes / self.total_bytes * 100


def disk(path: str = DISK_PATH) -> Capacity | None:
    """How full the filesystem is.

    `shutil.disk_usage` reports `used` as total-minus-free, which on a filesystem with
    reserved blocks is not the same as total-minus-available. The difference is a percent or
    two and always in the pessimistic direction, which is the right direction for the one
    reading that can stop Postgres accepting writes.

    Shared with `jobs/housekeeping.disk_watch` deliberately: one definition of "how full is
    the disk", rather than two that can drift apart until the alert disagrees with the page.
    """
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        log.debug("disk usage unavailable for %s", path, exc_info=True)
        return None
    return Capacity(used_bytes=usage.total - usage.free, total_bytes=usage.total)


def memory() -> Capacity | None:
    """How much memory is actually available, from `/proc/meminfo`.

    Uses **`MemAvailable`, not `MemFree`**. On any Linux box running Postgres, `MemFree` is
    alarming and meaningless: the kernel has spent the rest on page cache, which is the cache
    doing its job and is reclaimable the moment anything needs it. `MemAvailable` is the
    kernel's own estimate of what a new process could actually get, which is the question
    being asked.

    Note this reports the HOST's memory when running in a container with no memory limit —
    which is what `docker-compose.prod.yml` does, and which is the number wanted on a 1 GB VM
    shared with Postgres and Caddy. If a limit is ever set, this quietly starts meaning
    something else.
    """
    fields = _read_meminfo()
    if fields is None:
        return None
    total = fields.get("MemTotal")
    available = fields.get("MemAvailable")
    if total is None or available is None or total <= 0:
        return None
    return Capacity(used_bytes=max(0, total - available), total_bytes=total)


def _read_meminfo() -> dict[str, int] | None:
    """`/proc/meminfo` as bytes, or None where there is no `/proc`."""
    try:
        raw = MEMINFO.read_text()
    except OSError:
        return None
    out: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        # Every value in meminfo is kB unless it says otherwise, and the ones that do not
        # say otherwise are counts we are not reading.
        out[key] = value * 1024 if len(parts) > 1 else value
    return out or None


def load_average() -> float | None:
    """The 1-minute load average.

    Worth a tile on a shared-core e2-micro specifically: the vCPU runs on burst credits, so
    sustained load is not merely slow, it is a resource that runs out.
    """
    try:
        raw = LOADAVG.read_text()
    except OSError:
        return None
    try:
        return float(raw.split()[0])
    except (IndexError, ValueError):
        return None


def database_bytes(db: Session) -> int | None:
    """The size of the database on disk.

    This is what explains the disk reading — and it is the part that grows, which the disk
    reading alone cannot tell you. `pg_database_size` stats files rather than scanning, so it
    is cheap enough to sit behind a ten-second poll.
    """
    try:
        return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
    except Exception:  # noqa: BLE001 - a vital sign must never take the response with it
        log.debug("database size unavailable", exc_info=True)
        return None


#: The tables the Investments module owns. Its build spec reserves 250 MB of a disk that is
#: already three-quarters full, and a budget nobody measures is a wish.
INVESTMENT_TABLES = (
    "instruments",
    "portfolios",
    "charge_schedules",
    "transactions",
    "price_observations",
    "fx_observations",
    "corporate_actions",
)


def table_bytes(db: Session, tables: tuple[str, ...]) -> int | None:
    """How much disk a named set of tables occupies, indexes and TOAST included.

    `pg_total_relation_size` rather than `pg_relation_size`: the price record is small rows
    under a four-column primary key, so its indexes are a large fraction of what it costs and
    a figure that left them out would under-report the thing being budgeted.

    ⚠ Named via `to_regclass`, which returns NULL for a table that does not exist rather than
    raising. A migration that has not run yet must not take this reading — or the whole
    endpoint — down with it.
    """
    try:
        total = db.execute(
            text(
                "SELECT coalesce(sum(pg_total_relation_size(c)), 0) "
                "FROM unnest(CAST(:names AS text[])) AS n(name), "
                "LATERAL to_regclass(n.name) AS c WHERE c IS NOT NULL"
            ),
            {"names": list(tables)},
        ).scalar_one()
        return int(total)
    except Exception:  # noqa: BLE001 - a vital sign must never take the response with it
        log.debug("table size unavailable", exc_info=True)
        return None


def last_tick() -> dt.datetime | None:
    """When the scheduler last completed a pass, or None if it has not yet in this process.

    ⚠ Read from the scheduler's own heartbeat, **not** from `job_runs`, and the difference is
    the whole point of the reading.

    `job_runs` gets a row only when an occurrence actually fires. Between the 21:00 nudge and
    the 03:15 sweep, six hours pass in which a perfectly healthy scheduler writes nothing at
    all. "Newest job run" would therefore report a dead scheduler every night, and a signal
    that cries wolf nightly is one nobody reads on the morning it is right.

    **None means "not yet in this process", not "unknown".** After a restart it is genuinely
    true and stops being true within one tick interval, which is why `uptime` is reported
    beside it: together they distinguish "just booted" from "the ticker has stopped".
    """
    from app.jobs import scheduler

    return scheduler.last_tick_at()


def uptime_seconds() -> float:
    return (dt.datetime.now(dt.UTC) - _STARTED_AT).total_seconds()
