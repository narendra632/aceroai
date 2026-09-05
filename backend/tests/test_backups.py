"""Backups: that a copy is made, that it is checked, and that silence is reported.

**What these tests prove and what they do not.** Everything here runs with no credentials
and no network, against an in-memory object store, because CI has neither. So this suite
proves the *logic*: what gets written where, what a manifest claims, which discrepancies are
caught, and what happens when storage refuses. It does not prove that bytes reach Google
Cloud Storage — nothing running in CI can. **That half is proven in production, by
`restore_check`**, which is the whole reason a monthly restore exists rather than a
reassuring green tick here.

`pg_dump` and `pg_restore` are shelled out to and are not present on every developer
machine, so the two functions that invoke them are substituted. Everything either side of
them is real.
"""

import datetime as dt
import hashlib
import json

import pytest

from app.adapters.object_store import ObjectStoreError
from app.config import settings
from app.jobs import backups as backup_jobs
from app.jobs.registry import JobResult
from app.services import backups


class MemoryStore:
    """An `ObjectStore` that keeps everything in a dict, and can be told to refuse."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.fail_on_put = False

    def put(self, name, data, *, content_type="application/octet-stream"):
        if self.fail_on_put:
            raise ObjectStoreError(f"cannot write {name!r}")
        self.objects[name] = data

    def get(self, name):
        if name not in self.objects:
            raise ObjectStoreError(f"cannot read {name!r}")
        return self.objects[name]

    def list_prefix(self, prefix):
        return sorted(n for n in self.objects if n.startswith(prefix))

    def delete(self, name):
        self.objects.pop(name, None)


DUMP = b"PGDMP" + b"x" * 4096  # over MIN_PLAUSIBLE_BYTES, so it is accepted

#: Captured before the autouse fixture replaces it, so the one test that wants the real
#: implementation can still reach it.
_REAL_TAKE_DUMP = backups.take_dump


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture(autouse=True)
def no_shelling_out(monkeypatch):
    """`pg_dump` is not on every machine. Everything around it is still real."""
    monkeypatch.setattr(backups, "take_dump", lambda: DUMP)
    monkeypatch.setattr(backups, "dump_version", lambda: "pg_dump (PostgreSQL) 17.11")


@pytest.fixture(autouse=True)
def bucket_configured(monkeypatch):
    monkeypatch.setattr(settings, "backup_bucket", "pytest-bucket")


# --- what a copy claims about itself ---------------------------------------------------


def test_a_manifest_describes_the_dump_it_was_built_from(db):
    now = dt.datetime(2026, 9, 5, 2, 30, tzinfo=dt.UTC)
    manifest = backups.build_manifest(db, DUMP, taken_at=now)

    assert manifest["sha256"] == hashlib.sha256(DUMP).hexdigest()
    assert manifest["bytes"] == len(DUMP)
    assert manifest["taken_at"] == now.isoformat()
    # Every table the application defines is accounted for. A backup that promises only the
    # tables that happened to be non-empty would verify happily while missing one entirely.
    assert "profile_facts" in manifest["row_counts"]
    assert "journal_entries" in manifest["row_counts"]


def test_row_counts_are_taken_from_the_models_not_the_database(db):
    """A stray table in the database is not part of what a backup promises to contain.

    `restore_check` leaves a scratch database behind only if it crashes, but the same
    reasoning covers any leftover: counting whatever `information_schema` happens to list
    would make verification fail for a table this application does not own.
    """
    from app.db.session import Base

    counts = backups.row_counts(db)
    assert set(counts) == {t.name for t in Base.metadata.sorted_tables}


# --- where copies are written -----------------------------------------------------------


def test_an_ordinary_weekday_writes_one_copy():
    names = backups.object_names(dt.datetime(2026, 9, 9, 2, 30, tzinfo=dt.UTC))  # a Wednesday
    assert len(names) == 1
    assert names[0].startswith(settings.backup_prefix_daily)


def test_sunday_also_writes_a_weekly_copy():
    names = backups.object_names(dt.datetime(2026, 9, 6, 2, 30, tzinfo=dt.UTC))  # a Sunday
    assert len(names) == 2
    assert any(n.startswith(settings.backup_prefix_weekly) for n in names)


def test_the_first_of_the_month_also_writes_a_monthly_copy():
    names = backups.object_names(dt.datetime(2026, 10, 1, 2, 30, tzinfo=dt.UTC))  # a Thursday
    assert len(names) == 2
    assert any(n.startswith(settings.backup_prefix_monthly) for n in names)


def test_a_first_that_is_also_a_sunday_writes_all_three():
    """The case that is easy to get wrong with `elif`, and that appears a few times a year."""
    first_sunday = dt.datetime(2026, 11, 1, 2, 30, tzinfo=dt.UTC)
    assert first_sunday.weekday() == 6 and first_sunday.day == 1
    names = backups.object_names(first_sunday)
    assert len(names) == 3


def test_names_sort_chronologically():
    """`newest_object` takes the last of a sorted listing, so lexical order must be time
    order. A name that sorted differently would silently verify an old copy forever."""
    earlier = backups.object_names(dt.datetime(2026, 9, 9, 2, 30, tzinfo=dt.UTC))[0]
    later = backups.object_names(dt.datetime(2026, 9, 10, 2, 30, tzinfo=dt.UTC))[0]
    assert sorted([later, earlier]) == [earlier, later]


# --- writing ----------------------------------------------------------------------------


def test_a_copy_is_stored_with_its_manifest(db, store):
    detail = backups.write_backup(db, store, now=dt.datetime(2026, 9, 9, 2, 30, tzinfo=dt.UTC))

    name = detail["object"]
    assert store.objects[name] == DUMP
    manifest = json.loads(store.objects[name + backups.MANIFEST_SUFFIX])
    assert manifest["sha256"] == hashlib.sha256(DUMP).hexdigest()


def test_a_refused_write_raises_rather_than_reporting_success(db, store):
    store.fail_on_put = True
    with pytest.raises(ObjectStoreError):
        backups.write_backup(db, store)
    assert store.objects == {}


def test_an_implausibly_small_dump_is_refused(monkeypatch):
    """A truncated dump is far more likely than a genuinely empty database, and storing it
    would make the newest copy the unusable one.

    The real `take_dump` is used here — only the subprocess underneath it is replaced — so
    the size guard itself is what is being tested rather than a restatement of it.
    """
    monkeypatch.setattr(backups, "take_dump", _REAL_TAKE_DUMP)
    monkeypatch.setattr(backups, "_run", lambda *a, **kw: b"tiny")

    with pytest.raises(backups.BackupError, match="implausibly small"):
        backups.take_dump()


# --- verifying --------------------------------------------------------------------------


def test_a_checksum_mismatch_is_caught_before_anything_is_restored(db, store):
    """Order matters: there is nothing to learn from restoring a file already known to be
    the wrong file, and attempting it only produces a second, more confusing failure."""
    backups.write_backup(db, store, now=dt.datetime(2026, 9, 9, 2, 30, tzinfo=dt.UTC))
    name = backups.newest_object(store)
    store.objects[name] = b"PGDMP" + b"y" * 4096  # same size, different bytes

    with pytest.raises(backups.BackupError, match="does not match its manifest"):
        backups.verify_newest(store)


def test_verifying_with_no_copy_is_an_error_not_a_pass(store):
    """ "Nothing to check" must never read as "checked and fine"."""
    with pytest.raises(backups.BackupError, match="no copy to verify"):
        backups.verify_newest(store)


def test_a_surplus_is_tolerated_because_the_manifest_is_a_moment_later():
    """`pg_dump` snapshots on its own connection and the counts are read afterwards, so a
    row written in between leaves the dump holding more than the manifest claims. Failing on
    that would be a false alarm about the one subsystem whose alarms must be believed — and a
    surplus cannot indicate missing data, which is the thing being guarded against."""
    assert backups.first_shortfall({"tasks": 12}, {"tasks": 13}) is None


def test_a_short_table_is_named_with_both_counts():
    bad = backups.first_shortfall({"tasks": 12, "users": 1}, {"tasks": 9, "users": 1})
    assert bad == ("tasks", 12, 9)


def test_a_table_that_did_not_come_back_counts_as_zero():
    bad = backups.first_shortfall({"tasks": 12}, {})
    assert bad == ("tasks", 12, 0)


def test_matching_counts_report_nothing():
    assert backups.first_shortfall({"tasks": 12, "users": 1}, {"tasks": 12, "users": 1}) is None


def test_the_mismatch_reported_is_stable():
    """Sorted, so a failure names the same table on every run rather than whichever the
    dictionary yielded first — a flaky error message is a message nobody trusts."""
    expected = {"z_table": 1, "a_table": 1}
    actual = {"z_table": 0, "a_table": 0}
    assert backups.first_shortfall(expected, actual)[0] == "a_table"


# --- the jobs ----------------------------------------------------------------------------


def _run(fn, db, user) -> JobResult:
    """Call a job's function directly.

    `@job` registers and returns the function unchanged, so there is nothing to unwrap —
    stated here because a decorator that looks like it wraps and does not is exactly the
    kind of thing a reader assumes the other way round.
    """
    return fn(db, user)


def test_a_failed_backup_notifies_and_is_not_counted_as_one(db, user, store, monkeypatch):
    """The distinction the whole capability turns on.

    The job catches the storage failure and reports it, so the runner records the run as
    `ok` — the job did what it is for. What must NOT happen is that run then counting as a
    backup. `detail` carries no `object` key, which is what `last_successful_at` looks for.
    """
    store.fail_on_put = True
    monkeypatch.setattr(backup_jobs, "configured_store", lambda: store)

    result = _run(backup_jobs.db_backup, db, user)

    assert result.notify is not None
    assert result.notify.kind == "backup"
    assert not result.silent, "a failure is not a quiet night"
    assert "object" not in (result.detail or {})


def test_a_successful_backup_is_quiet_but_recorded(db, user, store, monkeypatch):
    monkeypatch.setattr(backup_jobs, "configured_store", lambda: store)

    result = _run(backup_jobs.db_backup, db, user)

    assert result.notify is None, "a nightly success notification trains you to ignore them"
    assert result.detail["object"]
    assert result.detail["bytes"] == len(DUMP)


def test_no_bucket_is_skipped_rather_than_failed(db, user, monkeypatch):
    """A developer machine has no bucket and must not fail every night."""
    monkeypatch.setattr(settings, "backup_bucket", "")
    monkeypatch.setattr(backup_jobs, "configured_store", lambda: None)

    result = _run(backup_jobs.db_backup, db, user)
    assert result.silent
    assert result.notify is None


# --- the watcher --------------------------------------------------------------------------


def _fake_staleness(monkeypatch, *, stale, hours):
    monkeypatch.setattr(backups, "staleness", lambda db, now=None: (stale, hours))


def test_a_recent_backup_says_nothing(db, user, monkeypatch):
    _fake_staleness(monkeypatch, stale=False, hours=11.0)
    result = _run(backup_jobs.backup_watch, db, user)
    assert result.silent and result.notify is None


def test_backups_having_stopped_is_reported(db, user, monkeypatch):
    _fake_staleness(monkeypatch, stale=True, hours=73.0)
    result = _run(backup_jobs.backup_watch, db, user)
    assert result.notify is not None
    assert "stopped" in result.notify.title.lower()


def test_never_having_backed_up_reports_rather_than_waiting(db, user, monkeypatch):
    """The dangerous case. With no first success to compare against, a naive check has
    nothing to measure and stays quiet — which is exactly backwards."""
    _fake_staleness(monkeypatch, stale=True, hours=None)
    result = _run(backup_jobs.backup_watch, db, user)
    assert result.notify is not None
    assert "never" in result.notify.title.lower()


def test_the_alarm_repeats_daily_rather_than_once(db, user, monkeypatch):
    """Following `disk_watch`: an unresolved condition is said again tomorrow. A backup that
    stopped a week ago is more urgent than one that stopped yesterday, not less."""
    _fake_staleness(monkeypatch, stale=True, hours=99.0)
    result = _run(backup_jobs.backup_watch, db, user)
    assert dt.datetime.now(dt.UTC).strftime("%Y-%m-%d") in result.notify.tag


def test_staleness_reads_only_successful_runs(db, user):
    """A night of correctly-reported failures must not read as a night of backups."""
    import uuid

    from app.db.models import JobRun

    db.add(
        JobRun(
            id=uuid.uuid4(),
            job_name=backups.BACKUP_JOB,
            occurrence_key="pytest-job-failed-1",
            status="ok",
            finished_at=dt.datetime.now(dt.UTC),
            detail={"error": "ObjectStoreError"},  # no "object" key
        )
    )
    db.commit()

    assert backups.last_successful_at(db) is None
