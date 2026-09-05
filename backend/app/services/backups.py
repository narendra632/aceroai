"""Copies of the database that outlive the machine, and the proof that they restore.

Three claims have to be true, and each needs its own mechanism, because each fails
independently and silently:

1. **A copy exists.** `write_backup` — a full `pg_dump` written to durable storage.
2. **The copy is usable.** `verify_newest` — restored into a scratch database and checked
   against what it said it contained.
3. **Someone finds out when either stops.** `last_successful_at`, read by `backup_watch`.

The third is the one people leave out. A backup system that has stopped looks exactly like
a backup system with nothing to report, and the difference is only discovered on the day it
matters.

**Why a full copy every night rather than an incremental chain.** A full dump is
independently restorable; an incremental chain needs its base plus every fragment since,
unbroken, and a single missing fragment invalidates everything after it — silently, until a
restore is attempted. At this size (single-digit megabytes) the full copy costs nothing, so
the usual argument for incrementals does not apply. The accepted cost is stated rather than
hidden: **up to 24 hours of work can be lost.**

**Nothing here ever deletes a backup.** Old copies expire through lifecycle rules on the
bucket. Code that deletes backups is code that can delete the wrong backup, on the one asset
with no second copy, on a path exercised once a night in production only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import subprocess
import tempfile

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.adapters.object_store import ObjectStore, ObjectStoreError
from app.config import settings
from app.db.models import JobRun
from app.db.session import Base, engine

log = logging.getLogger(__name__)

#: The job whose successful runs `backup_watch` looks for. Named here rather than imported
#: from the jobs module, so the service does not depend on the layer that calls it.
BACKUP_JOB = "db_backup"

MANIFEST_SUFFIX = ".manifest.json"

#: pg_dump/pg_restore flags. `--no-owner` and `--no-privileges` because the restore target
#: is a scratch database owned by whoever is restoring; carrying the original grants would
#: make verification fail for a reason that has nothing to do with the data being intact.
_DUMP_FLAGS = ("--format=custom", "--no-owner", "--no-privileges")

#: A dump of this database is small. A copy that comes back implausibly small is far more
#: likely to be a truncated write than a genuinely empty database, and treating it as a
#: successful backup is how an unusable copy becomes the newest one.
MIN_PLAUSIBLE_BYTES = 1024


class BackupError(RuntimeError):
    """A copy could not be made, or could not be shown to be good."""


def _conn_env() -> tuple[list[str], dict[str, str]]:
    """Connection arguments for the client tools, with the password kept out of argv.

    `PGPASSWORD` rather than a URL on the command line: arguments are visible in the process
    list to every user on the box, and a database password has no business being there.
    """
    url = make_url(settings.database_url)
    args = [
        "-h",
        url.host or "localhost",
        "-p",
        str(url.port or 5432),
        "-U",
        url.username or "postgres",
    ]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env


def _database_name() -> str:
    return make_url(settings.database_url).database or "postgres"


def _run(cmd: list[str], env: dict[str, str], *, stdin_path: str | None = None) -> bytes:
    """Run a client tool, raising `BackupError` with its stderr on failure.

    stderr rather than the return code alone: "pg_dump: error: aborting because of server
    version mismatch" is the difference between a five-minute fix and an afternoon, and it
    is lost if only the exit status survives.
    """
    try:
        with open(stdin_path, "rb") if stdin_path else _null_stdin() as source:
            proc = subprocess.run(cmd, stdin=source, capture_output=True, env=env, check=False)
    except FileNotFoundError as exc:
        raise BackupError(f"{cmd[0]} is not installed in this image") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip() or f"exit {proc.returncode}"
        raise BackupError(f"{cmd[0]} failed: {detail}")
    return proc.stdout


class _null_stdin:
    def __enter__(self):
        return subprocess.DEVNULL

    def __exit__(self, *exc):
        return False


def dump_version() -> str:
    """The `pg_dump` this image carries. Used by the startup check and recorded in manifests."""
    _, env = _conn_env()
    return _run(["pg_dump", "--version"], env).decode().strip()


def take_dump() -> bytes:
    """A complete, self-contained copy of the database, as bytes."""
    args, env = _conn_env()
    data = _run(["pg_dump", *args, "-d", _database_name(), *_DUMP_FLAGS], env)
    if len(data) < MIN_PLAUSIBLE_BYTES:
        raise BackupError(f"dump is implausibly small ({len(data)} bytes) — refusing to store it")
    return data


def row_counts(db: Session) -> dict[str, int]:
    """How many rows each table holds right now.

    Counted from the model metadata rather than from `information_schema`, so a table that
    exists in the database but not in this application (a leftover, a scratch table) does
    not silently become part of what a backup promises to contain.
    """
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        counts[table.name] = int(db.execute(select(func.count()).select_from(table)).scalar_one())
    return counts


def build_manifest(db: Session, data: bytes, *, taken_at: dt.datetime) -> dict:
    """What this copy claims to contain, written at the same moment as the copy itself.

    Without this a restore can only show that *a* file restored, which is a far weaker claim
    than that the right one did: a truncated custom-format dump frequently restores with no
    error at all, leaving a database that is quietly smaller than it should be.

    The counts describe the state **at dump time**. Verification compares against them and
    never against the live database, which has moved on since.

    ⚠ "At dump time" is approximate by one moment: `pg_dump` holds its own snapshot on its own
    connection, and these counts are read afterwards on this one. A row written in between
    leaves the dump holding slightly MORE than the manifest claims. That asymmetry is why
    `first_shortfall` tolerates a surplus and fails only on a shortfall — see its docstring.
    """
    return {
        "taken_at": taken_at.isoformat(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "pg_dump": dump_version(),
        "database": _database_name(),
        "row_counts": row_counts(db),
    }


def object_names(now: dt.datetime) -> list[str]:
    """Where this copy is stored: always daily, also weekly on Sundays, monthly on the 1st.

    Three prefixes rather than one, because retention differs per prefix and is enforced by
    lifecycle rules on the bucket. The same bytes are written up to three times on the rare
    day that is both — a few megabytes, against not having to compute which copies to keep.

    The name is ordered so that **lexical order is chronological order**, which is what lets
    "the newest copy" be the last element of a sorted listing.
    """
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    leaf = f"{_database_name()}-{stamp}.dump"
    names = [f"{settings.backup_prefix_daily}{leaf}"]
    if now.weekday() == 6:  # Sunday
        names.append(f"{settings.backup_prefix_weekly}{leaf}")
    if now.day == 1:
        names.append(f"{settings.backup_prefix_monthly}{leaf}")
    return names


def write_backup(db: Session, store: ObjectStore, *, now: dt.datetime | None = None) -> dict:
    """Take a copy and store it under every prefix it belongs to. Returns run detail.

    A copy whose dump was written but whose manifest was not is a failure, not a partial
    success: an unverifiable copy is exactly the thing this design exists to avoid, and
    counting it would make the newest copy the one that cannot be checked.
    """
    now = now or dt.datetime.now(dt.UTC)
    data = take_dump()
    manifest = build_manifest(db, data, taken_at=now)
    body = json.dumps(manifest, indent=2, sort_keys=True).encode()

    names = object_names(now)
    for name in names:
        store.put(name, data)
        store.put(name + MANIFEST_SUFFIX, body, content_type="application/json")

    return {
        "bytes": manifest["bytes"],
        "rows": sum(manifest["row_counts"].values()),
        "copies": len(names),
        "object": names[0],
    }


def newest_object(store: ObjectStore) -> str | None:
    """The most recent daily copy, or None when there is not one yet."""
    names = [
        n
        for n in store.list_prefix(settings.backup_prefix_daily)
        if not n.endswith(MANIFEST_SUFFIX)
    ]
    return names[-1] if names else None


def first_shortfall(
    expected: dict[str, int], actual: dict[str, int]
) -> tuple[str, int, int] | None:
    """The first table that came back with FEWER rows than the manifest promised, or None.

    Separated from the restore so the comparison — the part that decides whether a backup is
    trusted — is testable without a database server or a `pg_restore` binary. Tables are
    walked in sorted order so the table named in a failure is the same one every time,
    rather than whichever the dictionary happened to yield first.

    A table missing from the restore counts as zero rather than as an absence: a table that
    did not come back is the most serious form of "fewer rows than promised", not a
    different kind of event.

    ⚠ **A surplus is deliberately not a failure, and the reason is a race this design cannot
    close.** `pg_dump` runs as a separate process with its own snapshot, and the row counts
    are taken afterwards on a different connection — so a row written between the two makes
    the dump contain *more* than the manifest claims. Treating that as a mismatch would
    produce a false alarm about the one subsystem whose alarms must be believed.

    Nothing is lost by tolerating it. A surplus can only mean the manifest was taken a moment
    later than the dump; it cannot indicate missing data. **A shortfall is the danger** — a
    dump that restores with fewer rows than it promised — and that still fails, loudly, with
    the table named.
    """
    for table in sorted(expected):
        got = actual.get(table, 0)
        if got < expected[table]:
            return table, expected[table], got
    return None


def _recreate_scratch(name: str) -> None:
    """A empty database to restore into, replacing any left by an interrupted run.

    AUTOCOMMIT because Postgres refuses CREATE/DROP DATABASE inside a transaction block.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))


def _drop_scratch(name: str) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def verify_newest(store: ObjectStore) -> dict:
    """Restore the newest copy into a scratch database and check it against its manifest.

    Order matters. The checksum is compared **before** anything is restored: there is
    nothing to learn from restoring a file already known not to be the file that was
    written, and doing so would only produce a second, more confusing failure.

    The live database is never a participant. The scratch database is created for this and
    dropped in a `finally`, so a failure part-way through can neither leave it behind nor
    stop the next run from starting.
    """
    name = newest_object(store)
    if name is None:
        raise BackupError("there is no copy to verify")

    data = store.get(name)
    manifest = json.loads(store.get(name + MANIFEST_SUFFIX))

    actual = hashlib.sha256(data).hexdigest()
    if actual != manifest["sha256"]:
        raise BackupError(
            f"{name} does not match its manifest — stored copy is corrupt or truncated "
            f"({len(data)} bytes, expected {manifest['bytes']})"
        )

    scratch = settings.backup_verify_dbname
    args, env = _conn_env()
    tmp_path = None
    try:
        _recreate_scratch(scratch)
        with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        _run(["pg_restore", *args, "-d", scratch, "--no-owner", "--no-privileges", tmp_path], env)

        restored = make_url(settings.database_url).set(database=scratch)
        from sqlalchemy import create_engine

        probe = create_engine(restored)
        try:
            with probe.connect() as conn:
                actual = {
                    table: int(conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one())
                    for table in manifest["row_counts"]
                }
        finally:
            probe.dispose()

        bad = first_shortfall(manifest["row_counts"], actual)
        if bad is not None:
            table, expected, got = bad
            raise BackupError(
                f"{name} restored with only {got} rows in {table!r}, manifest says {expected}"
            )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:  # pragma: no cover - best effort
                pass
        _drop_scratch(scratch)

    return {
        "object": name,
        "bytes": manifest["bytes"],
        "tables": len(manifest["row_counts"]),
        "rows": sum(manifest["row_counts"].values()),
    }


def last_successful_at(db: Session) -> dt.datetime | None:
    """When a copy last succeeded, or None if one never has.

    Read from `job_runs` rather than from the bucket. The question `backup_watch` asks is
    "did the work happen", and a listing of the bucket cannot distinguish "the job has
    stopped running" from "the bucket setting was changed" — which are the same alarm but
    would otherwise need two mechanisms to notice.

    None is deliberately not "recent". A system that has never backed up must report, not
    stay quiet until a first success gives it something to compare against.

    ⚠ **A run's status is not enough to identify a success.** `db_backup` catches a storage
    failure and returns a notification rather than raising, so the user is told at the time
    — which means the runner records that run as `ok`, because the job did exactly what it
    is supposed to do. What separates the two is the `object` key, written to `detail` only
    when bytes actually reached the bucket. Filtering on status alone would let a night of
    correctly-reported failures read as a night of backups, which is the precise deception
    this whole capability exists to prevent.
    """
    return db.execute(
        select(func.max(JobRun.finished_at)).where(
            JobRun.job_name == BACKUP_JOB,
            JobRun.status == "ok",
            JobRun.detail.has_key("object"),  # noqa: W601 - JSONB `?`, not dict.has_key
        )
    ).scalar_one_or_none()


def staleness(db: Session, *, now: dt.datetime | None = None) -> tuple[bool, float | None]:
    """(is it stale, hours since the last success). Hours is None when there never was one."""
    now = now or dt.datetime.now(dt.UTC)
    last = last_successful_at(db)
    if last is None:
        return True, None
    if last.tzinfo is None:  # pragma: no cover - column is timestamptz
        last = last.replace(tzinfo=dt.UTC)
    hours = (now - last).total_seconds() / 3600
    return hours >= settings.backup_stale_hours, hours


def unavailable_reason(store: ObjectStore | None) -> str | None:
    """Why the backup jobs cannot run, or None when they can."""
    if store is None:
        return "no backup bucket configured"
    return None


def check_tooling() -> None:
    """Log loudly at startup if this image cannot take a backup.

    Deliberately a log line rather than a refusal to start. A missing `pg_dump` breaks
    backups; it does not break the assistant, and taking the whole application down over it
    would turn a recoverable deployment mistake into an outage. The condition still cannot
    hide: the nightly job reports it, and `backup_watch` reports the resulting silence.

    Only meaningful when a bucket is configured. A developer machine has neither and should
    say nothing.
    """
    if not settings.backup_bucket:
        return
    try:
        log.info("backups: %s", dump_version())
    except BackupError as exc:
        log.error(
            "BACKUPS CANNOT RUN: %s. A bucket is configured but this image cannot take a "
            "dump, so nothing will be copied off this machine until it is fixed.",
            exc,
        )


__all__ = [
    "BACKUP_JOB",
    "BackupError",
    "ObjectStoreError",
    "build_manifest",
    "first_shortfall",
    "dump_version",
    "last_successful_at",
    "newest_object",
    "object_names",
    "row_counts",
    "staleness",
    "take_dump",
    "unavailable_reason",
    "verify_newest",
    "write_backup",
]
