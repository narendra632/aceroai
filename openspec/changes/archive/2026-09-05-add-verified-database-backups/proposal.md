# Verified database backups

## Why

**The database has never been backed up.** There is one copy of everything this application
knows, on one 30 GB disk, in one zone, and nothing anywhere copies it. Measured on
2026-09-05 it is **9,566 kB** — nine and a half megabytes holding every journal entry, every
task, every memory fact and its embedding, the notification history, the job history and the
whole observability record.

That was a deliberate, priced decision, taken when the thing at risk was a personal assistant
whose contents could largely be retyped. **The price has changed.** The Investments module —
already specified in `docs/investmentsmoduletechnical.md` — makes twelve tables append-only
*on purpose*, because its product is not a portfolio but an unfalsifiable record of what was
believed and when. A frozen `price_snapshot` from three months ago, or a `framework_score`
made under a rule version since retired, cannot be recreated by anyone. The module's own
build spec makes backups a blocking Phase 0 prerequisite for exactly this reason, and it is
right.

**A backup that has never been restored is a guess, not a backup.** Files can be written
nightly for a year and be unusable — wrong flags, a truncated upload, or a missing extension
at restore time. This database uses `pgvector`; a restore that cannot create that extension
produces a file that looks like a backup and is not one. The failure is discovered on the one
day it matters. So this change delivers backups **and** the proof that they restore, or it
delivers nothing worth having.

**Silence is the characteristic failure of backup systems.** Not a loud error — an absence.
A job stops running, or starts failing, and nothing says so, because "nothing happened" looks
identical to "nothing needed to happen". Everything below is shaped by that: failures notify,
and the *absence* of success notifies too.

## What Changes

- **A nightly dump of the whole database is copied off the machine** to Google Cloud Storage.
  Full snapshot, not an incremental chain: at this size the copy is free, and one
  self-contained file per night cannot break the way a chain of fragments can.
- **Each dump is accompanied by a manifest** recording when it was taken, the server version,
  the byte count, a SHA-256 of the dump, and the row count of every table. The manifest is
  what makes verification possible — without a record of what the dump *should* contain,
  a restore can only prove that some file restored, not that the right one did.
- **Retention is enforced by the storage service, not by application code.** 14 daily, 8
  weekly, 12 monthly, by object lifecycle rules on three prefixes. Code that deletes backups
  is code that can delete the wrong backup.
- **A monthly restore actually happens.** The newest dump is downloaded, its SHA-256 checked
  against its manifest, restored into a scratch database on the same server, and its row
  counts compared table by table against the manifest. The scratch database is then dropped.
  A mismatch, a failed restore or a checksum failure raises a notification.
- **The absence of a recent backup is itself an alarm.** A separate daily check reports when
  no backup has succeeded in 48 hours. It is deliberately a *different* job from the one that
  takes the backup, because a job cannot report its own failure to run.
- **`pg_dump` enters the backend image**, at a version not older than the server. A client
  older than the server refuses to dump at all, which is the correct behaviour and a
  deployment failure if unnoticed.

## Capabilities

### New Capabilities

- **`backups`** — that the record survives the machine, and that this claim is checked rather
  than assumed. It is its own capability rather than part of `deployment` because its
  behavioural contract is about the *durability and verifiability of data*, not about how the
  application is served. A deployment can be perfect and lose everything.

### Modified Capabilities

**None.** Three new jobs are added and `scheduled-jobs` is deliberately untouched: it already
states *"Adding a new job requires no change to the scheduler or the schema"*, and these jobs
are that requirement being used, not changed. `observability` is likewise untouched — a
stalled scheduler is already visible there, and backup staleness is a different claim that
belongs with backups.

## Impact

**Schema.** None. No migration. Backup metadata lives in the manifest object beside each
dump, and each run is recorded in the existing `job_runs.detail`. A `backup_runs` table was
considered and rejected — see `design.md`.

**Backend.** New `app/services/backups.py` (dump, upload, manifest, restore verification) and
`app/adapters/object_store.py` (the only module that talks to Cloud Storage, so tests can
substitute it). Three new jobs in `app/jobs/backups.py`. New settings for the bucket name and
the staleness bound.

**Deployment.** `backend/Dockerfile` gains the PostgreSQL client. The VM's existing service
account has been granted `Storage Object Admin` on `gs://aceroai-backups` — no new secret, no
key file: the same Application Default Credentials path that already authenticates Vertex.

**Frontend.** None. Backup health surfaces through the existing notification panel and the
existing Settings job list.

**Documentation.** `docs/ARCHITECTURE.md`, `docs/DEPLOY.md` (the bucket and the IAM grant),
`docs/JOBS.md` (three new jobs), `docs/ROADMAP.md` (the "no database backup" entry is the
highest-risk item there and this closes it), and the Learn page.

**Dependencies — ⚠ Narendra must approve.** Both were approved in conversation on
2026-09-05, recorded here so the record is complete:

- **`google-cloud-storage`** (Python). `google-auth` is already present via `google-genai`,
  so the marginal weight is small. The alternative — hand-signed HTTP calls to the storage
  JSON API with no new dependency — was rejected as more code and more to get wrong on the
  one path that must not silently misbehave.
- **`postgresql-client`** in the backend image, at a version ≥ the server's 17.

## Non-goals (this change)

- **No point-in-time recovery.** Nightly full dumps mean the worst case is losing up to 24
  hours. PITR would reduce that to seconds and costs a continuous WAL archive, a chain whose
  breakage is silent, and materially more machinery. For hand-typed journal entries and
  hand-typed transactions, a day is an acceptable loss. Nothing here forecloses PITR later.
- **No automatic restore.** The system verifies that a restore *works*; it never restores over
  the live database on its own. Recovery is a human decision made with the full picture.
- **No GCP disk snapshots.** A different mechanism for a different problem — they copy the
  whole disk, are opaque, and cannot be inspected or selectively restored. `pg_dump` produces
  something a person can read and restore one table from.
- **No backup of anything but Postgres.** The `.env`, the Caddy certificates and the repo are
  all reconstructible from their sources; the database is not.
- **No `investments_disk_watch`.** The Investments spec places per-module disk reporting in
  Phase 0. It measured a real constraint when the disk was 77% full with 2.3 GB free; the disk
  is now 23% full with 22 GB free, and the tables it would measure do not exist. It belongs in
  the change that creates them.
- **No container log size caps.** Proposed and then withdrawn: the hypothesis was that
  unbounded container logs were consuming the disk, and measurement showed logs at
  effectively zero — frequent deploys recreate the containers and reset them. A fix for a
  problem that measurement disproved is scope, not caution.
- **No second backup destination.** One bucket, geo-redundant across US regions. A second
  provider doubles the failure surface of the upload path to protect against an outcome
  (multi-region GCS loss) far less likely than the ones already being protected against.
