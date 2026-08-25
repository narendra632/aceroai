"""The server's own condition, and the promise that reading it never breaks anything.

Two properties matter more than the numbers themselves.

**A measurement that cannot be taken is absent, not zero.** `/proc` does not exist on
Windows, so these readers must degrade rather than raise — and the interface must be able
to tell "I could not measure this" from "this is at zero". A zero is a wrong answer wearing
the confidence of a right one.

**One broken reader degrades one field.** This endpoint is polled every ten seconds. A
monitoring surface that can itself fail loudly is worse than none, because it manufactures
the incidents it exists to report.
"""

import datetime as dt
from pathlib import Path

from app.config import settings
from app.services import vitals

MISSING = Path("/definitely/not/a/real/path/for/pytest")


# --- degradation ---------------------------------------------------------------------


def test_memory_is_absent_rather_than_zero_when_proc_does_not_exist(monkeypatch):
    """This is the Windows development machine, and it must not look like a fault."""
    monkeypatch.setattr(vitals, "MEMINFO", MISSING)
    assert vitals.memory() is None


def test_load_average_is_absent_rather_than_zero(monkeypatch):
    monkeypatch.setattr(vitals, "LOADAVG", MISSING)
    assert vitals.load_average() is None


def test_disk_is_absent_rather_than_zero_for_an_unreadable_path():
    assert vitals.disk(str(MISSING)) is None


def test_a_malformed_meminfo_does_not_raise(monkeypatch, tmp_path):
    bad = tmp_path / "meminfo"
    bad.write_text("this is not meminfo\nMemTotal: banana kB\n")
    monkeypatch.setattr(vitals, "MEMINFO", bad)
    assert vitals.memory() is None


def test_meminfo_without_memavailable_is_absent(monkeypatch, tmp_path):
    """`MemFree` alone is not an answer to the question being asked, so a kernel too old to
    report `MemAvailable` yields nothing rather than a misleading substitute."""
    old = tmp_path / "meminfo"
    old.write_text("MemTotal:       1000000 kB\nMemFree:          20000 kB\n")
    monkeypatch.setattr(vitals, "MEMINFO", old)
    assert vitals.memory() is None


# --- correctness of the readings we can synthesise -------------------------------------


def test_memory_is_computed_from_memavailable_not_memfree(monkeypatch, tmp_path):
    """The distinction that makes this reading meaningful.

    On any box running Postgres, `MemFree` is alarming and meaningless — the kernel has
    spent the rest on page cache, which is reclaimable. Reading `MemFree` here would report
    98% memory pressure on a perfectly healthy machine.
    """
    f = tmp_path / "meminfo"
    f.write_text(
        "MemTotal:       1000000 kB\n"
        "MemFree:          20000 kB\n"  # would imply 98% used
        "MemAvailable:    600000 kB\n"  # the truth: 40% used
    )
    monkeypatch.setattr(vitals, "MEMINFO", f)
    reading = vitals.memory()
    assert reading is not None
    assert reading.total_bytes == 1000000 * 1024
    assert round(reading.percent) == 40, "MemFree would have said 98"


def test_load_average_reads_the_one_minute_figure(monkeypatch, tmp_path):
    f = tmp_path / "loadavg"
    f.write_text("0.42 1.15 2.30 1/512 12345\n")
    monkeypatch.setattr(vitals, "LOADAVG", f)
    assert vitals.load_average() == 0.42


def test_capacity_percent_is_safe_at_zero_total():
    assert vitals.Capacity(used_bytes=0, total_bytes=0).percent == 0.0


def test_database_size_is_a_real_number(db):
    size = vitals.database_bytes(db)
    assert size is not None and size > 0


def test_uptime_is_measured_from_import():
    assert vitals.uptime_seconds() >= 0


# --- the scheduler heartbeat -----------------------------------------------------------


def test_last_tick_is_none_when_the_process_has_not_ticked(monkeypatch):
    """None means "not yet in this process", which is TRUE after a restart and stops being
    true within one interval. It is not "unknown", and it is not an error."""
    from app.jobs import scheduler

    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    assert vitals.last_tick() is None


def test_last_tick_reads_the_schedulers_heartbeat_not_job_runs(monkeypatch):
    """⚠ The reading deliberately does NOT come from `job_runs`.

    A row is written there only when an occurrence fires, and the jobs cluster in waking
    hours — there are six hours between the 21:00 nudge and the 03:15 sweep in which a
    perfectly healthy scheduler writes nothing at all. Sourcing the heartbeat from
    `job_runs` would report a dead scheduler every single night, and a signal that cries
    wolf nightly is one nobody reads on the morning it is right.
    """
    from app.jobs import scheduler

    stamp = dt.datetime.now(dt.UTC)
    monkeypatch.setattr(scheduler, "_last_tick_at", stamp)
    assert vitals.last_tick() == stamp


def test_the_heartbeat_is_recorded_even_when_the_tick_fails(monkeypatch):
    """It records that the TICKER is alive, which is a different claim from "the work
    succeeded". A tick that raises every time still proves the timer is running; what
    failed is recorded against the job in `job_runs`. Conflating the two would make one
    broken job look like a dead scheduler."""
    import asyncio

    from app.jobs import scheduler

    def boom():
        raise RuntimeError("the tick itself blew up")

    monkeypatch.setattr(scheduler, "_last_tick_at", None)
    monkeypatch.setattr(scheduler, "_tick_sync", boom)

    assert asyncio.run(scheduler.tick_once()) == {}
    assert scheduler.last_tick_at() is not None


# --- the endpoint ----------------------------------------------------------------------


def test_vitals_requires_authentication(client):
    assert client.get("/api/insights/vitals").status_code == 401


def test_vitals_reports_what_it_can_and_omits_what_it_cannot(auth_client, monkeypatch):
    monkeypatch.setattr(vitals, "MEMINFO", MISSING)
    monkeypatch.setattr(vitals, "LOADAVG", MISSING)

    r = auth_client.get("/api/insights/vitals")
    assert r.status_code == 200
    body = r.json()

    assert body["memory"] is None
    assert body["load_1m"] is None
    assert body["disk"] is not None, "the disk is readable on every platform"
    assert body["database_bytes"] > 0
    assert body["tick_interval_seconds"] == settings.job_tick_seconds
    assert body["disk_warn_percent"] == settings.disk_warn_percent


def test_a_broken_reader_degrades_one_field_not_the_response(auth_client, monkeypatch):
    """A reader that raises outright — i.e. one that forgot to handle its own failure, or
    was added later by someone who did not read the rule. The endpoint holds the guarantee
    structurally so it does not depend on every reader remembering.

    This test was written expecting to pass and did not: the isolation lived only inside
    each reader, so one raising took the whole page down. That is the wrong shape for
    something polled every ten seconds.
    """

    def explode(_db):
        raise RuntimeError("the database size query failed")

    monkeypatch.setattr(vitals, "database_bytes", explode)

    r = auth_client.get("/api/insights/vitals")
    assert r.status_code == 200, "one broken reader must not fail the response"
    body = r.json()
    assert body["database_bytes"] is None
    assert body["disk"] is not None, "the other readings are unaffected"


def test_vitals_are_never_cached(auth_client):
    """Every request must produce a fresh reading. A cached vital sign is a wrong one."""
    r = auth_client.get("/api/insights/vitals")
    assert r.headers.get("cache-control") == "no-store"


def test_health_stays_exactly_as_it_was(client):
    """⚠ Pinned deliberately.

    `/health` is UNAUTHENTICATED — Caddy probes it, and it is what proves the backend is
    alive from outside the network when something breaks. Disk figures, memory totals and
    database size are infrastructure detail, and "the health endpoint grew a few useful
    fields" is exactly how an unauthenticated endpoint becomes a reconnaissance surface.

    This test exists to make that temptation fail loudly rather than pass review.
    """
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
