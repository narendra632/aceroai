# Design — verified database backups

## The shape of the problem

Backup systems do not usually fail loudly. They fail by stopping, and stopping looks exactly
like working when the only evidence either way is the absence of an error. Every decision
below is chosen against that failure mode rather than against data loss directly, because
data loss is not the thing that goes wrong first — the *reporting* is.

Three separate things therefore have to be true, and each needs its own mechanism:

1. A copy exists. (`db_backup`)
2. The copy is usable. (`restore_check`)
3. Someone finds out when either of the above stops being true. (`backup_watch`, and the
   failure notification on the other two)

A system with only the first is the common case and is worth much less than it appears.

---

## Decision 1 — The backup runs as an Acero job, not as a cron on the host

**Chosen:** a `@job(...)` in `app/jobs/backups.py`, running in the API container like every
other scheduled job.

**Rejected: a systemd timer or crontab entry on the VM.** This is the genuinely close call,
and the argument for it is real: a host cron keeps running when the application is broken,
whereas an in-app job does not. That is a true advantage and it is written down here so the
choice can be revisited rather than rediscovered.

It loses anyway, for two reasons.

The first is that a cron's failures are invisible by construction. It writes to a log nobody
reads on a box nobody logs into. As an Acero job the backup gets `job_runs` history, a row in
the Settings job list, `catch_up` semantics, and a notification when it fails — which is the
entire problem restated as infrastructure that already exists and is already tested.

The second answers the argument directly. "The app is down, so the backup did not run" is a
tolerable failure *specifically here*, because this application is used daily and by one
person. A dead API is discovered within hours by the person who needs the backup. That is not
true of a silent cron, which can be dead for a year while everything looks fine. Between two
failure modes, the one that announces itself is preferable to the one that does not — and
`observability` already makes a stalled scheduler visible, which covers the case where the
process lives but the timer does not.

**Rejected: GCP disk snapshots.** They copy the whole 30 GB disk rather than the 9.5 MB that
matters, are opaque (no way to inspect a snapshot's contents or restore one table), and prove
nothing about whether Postgres can actually read what is inside. They are a machine-recovery
tool, not a data-integrity tool, and this change is about data integrity.

**Rejected: Cloud SQL managed backups.** Would require abandoning self-hosted Postgres. The
`pgvector` extension, the pinned pg17 image, and the free-tier e2-micro all argue against it,
and managed backups are not the reason to change hosting model.

---

## Decision 2 — A full dump every night, not an incremental chain

**Chosen:** `pg_dump --format=custom` of the entire database, nightly.

**Rejected: WAL archiving / point-in-time recovery.** PITR reduces the worst-case loss from
24 hours to seconds, which sounds strictly better and is not, at this size. PITR stores a base
copy plus a continuous stream of every change, and restoring requires the base **plus every
fragment since, unbroken**. A single missing or corrupt segment invalidates everything after
it, and does so silently until a restore is attempted. That is precisely the class of failure
this change exists to eliminate.

The trade is explicit: **up to 24 hours of loss is accepted** in exchange for every backup
being independently restorable. At 9.5 MB the full copy costs nothing, so the usual reason to
prefer incrementals — size — does not apply. If the acceptable loss window ever shrinks (real
money in the Investments ledger would be the trigger), PITR is added *alongside* this, not
instead of it.

`--format=custom` rather than plain SQL because it compresses by default and supports
selective restore — the ability to pull back one table without replaying the whole database
is worth having on the day it is needed.

---

## Decision 3 — Every dump carries a manifest

**Chosen:** each dump is uploaded with a sibling JSON object recording `taken_at`, the server
version, byte count, SHA-256 of the dump, and a per-table row count.

Without this, a restore verifies only that *a* file restored. With it, the restore can assert
that **this** dump contains what it claimed to contain — and the checksum catches the
truncated upload, which is the most likely silent corruption on this path and is invisible to
`pg_restore` (a truncated custom-format file often restores partially without error).

The row counts are the honest check. Comparing a restored database against the *live* one is
wrong, because the live one has moved on since the dump; comparing it against what was true
**at dump time** is the only comparison that can be exact.

**Rejected: trusting `pg_restore`'s exit code.** It reports whether restore commands
succeeded, not whether the data is the data. Both failures above pass it.

---

## Decision 4 — Retention is enforced by object lifecycle rules

**Chosen:** three prefixes — `daily/`, `weekly/`, `monthly/` — with GCS lifecycle rules of 14,
56 and 365 days. The job writes to `daily/` every night, additionally to `weekly/` on Sundays,
and additionally to `monthly/` on the 1st. Steady state is 34 objects, roughly 100 MB, about
₹0.25/month.

**Rejected: the application deleting its own old backups.** Code that deletes backups is code
that can delete the wrong backup, and it would be the least-exercised path in the system —
run once a night, in production only, on the one asset with no second copy. Lifecycle rules
move that risk to infrastructure that Google operates and that cannot run at all when the
application is misbehaving.

**Why keep twelve monthlies.** The dailies and weeklies cover mistakes noticed quickly.
Monthlies cover the failure that takes months to surface: a bug writes wrong data, and every
subsequent backup faithfully preserves the corruption. Only a backup predating the bug holds
the truth, and only a series of them allows bisecting to *when* it started. For append-only
Investments tables, where the record is the product, this is the scenario that matters most.
It costs about ₹0.15/month.

---

## Decision 5 — The restore is verified into a scratch database on the same server

**Chosen:** `restore_check` creates `acero_restore_check`, restores into it, compares against
the manifest, and drops it. The next run drops any leftover first, so a crashed run cannot
wedge the following one.

**Rejected: a throwaway Postgres container per check.** Cleaner isolation, and a second
Postgres process on a 1 GB box next to the live one is a poor trade for a check that runs
monthly on 9.5 MB of data.

**Rejected: restoring into the live database with a schema prefix.** Restoring production data
next to production data, monthly, forever. The one plausible way this change could itself
cause the loss it exists to prevent.

**This is the check that catches the `pgvector` failure.** A dump of this database contains
`CREATE EXTENSION vector`; a restore into a server without it fails. Because the scratch
database is on the same server, that failure would *not* be caught here — which is worth
stating plainly rather than implying more coverage than exists. What this verifies is that the
dump is complete, uncorrupted, and restorable by this server. Verifying restorability onto a
*different* machine is a stronger claim requiring a second machine, and is deliberately out of
scope.

---

## Decision 6 — The staleness alarm is a separate job

**Chosen:** `backup_watch`, daily, reports when the newest successful `db_backup` run in
`job_runs` is older than 48 hours.

It cannot live inside `db_backup`, because a job that does not run cannot report that it did
not run. That sounds obvious and is the exact mistake that makes most backup monitoring
decorative.

48 hours rather than 24 so that one missed night — a restart, a transient network failure,
a catch-up window that closed — does not cry wolf, while two consecutive failures always
speak. The band-crossing convention from `disk_watch` applies: an unresolved condition is
repeated daily rather than announced once.

---

## Decision 7 — No new table

**Chosen:** `job_runs.detail` records each backup run (bytes, duration, object name, row-count
total); the manifest object holds the per-table detail.

**Rejected: a `backup_runs` table.** It would duplicate what `job_runs` already stores for
every job, and add a schema migration to a change that otherwise needs none. The project
convention is that derived values are computed rather than stored; "when did the last backup
succeed" is a query over `job_runs`, not a fact needing its own home.

`job_runs.detail` is documented as *"Counts and identifiers only, never message text"*, which
is exactly what this writes.

---

## Decision 8 — Cloud Storage sits behind an adapter

**Chosen:** `app/adapters/object_store.py` is the only module importing
`google.cloud.storage`. Everything else takes an interface with `put`, `get`, `list` and
`delete`.

This is what makes the work testable without network access or credentials — CI has neither.
The service logic (manifest construction, prefix selection, checksum comparison, the failure
paths) is fully exercised against an in-memory substitute; the real upload is exercised in
production and asserted by `restore_check`. Stating that split honestly matters: **CI proves
the logic, production proves the round trip.**

It also introduces `adapters/` to this codebase, which the Investments spec assumes will exist
for its eight external HTTP dependencies. One adapter is a thin start, not a framework.

---

## Decision 9 — Authentication reuses Application Default Credentials

The VM's attached service account already authenticates Vertex through the metadata server
with no key file on disk, and its access scopes are already `cloud-platform`. Granting that
same account `Storage Object Admin` **on the bucket only** adds a capability without adding a
secret.

**Rejected: a service-account key file in `.env`.** It would be the first long-lived
credential on the disk, for a benefit — none — that does not exist.

The bucket is private with public access prevention on, and GCS encrypts at rest by default.
This is worth stating because **the dump contains everything**, including password hashes and
push subscription keys. The security posture of the backup is exactly the security posture of
the bucket, and it should never quietly become weaker than the database it copies.

---

## Decision 10 — `pg_dump` must not be older than the server

`pg_dump` refuses to dump a server newer than itself. The server is Postgres 17
(`pgvector/pgvector:pg17`); the backend image is `python:3.12-slim`, which carries no
PostgreSQL client at all, and whose Debian base determines which version `apt-get install
postgresql-client` would provide — Debian 12 would give 15, which cannot dump this server.

The version is therefore **pinned explicitly and asserted at startup**, not assumed from the
base image. A silent base-image bump that downgrades the client would otherwise break backups
at the next deploy, with the first symptom being a failure notification months of nights later
— or, if the failure path itself regressed, no symptom at all.

Task 0.2 verifies this in the built image before any of the backup logic is written.
