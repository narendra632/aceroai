# Tasks — verified database backups

## 0. Verify the assumptions before writing anything

Everything in this section either confirms a belief this change depends on, or removes an
obstacle that would otherwise surface at a random moment during it.

- [x] 0.1 Record the starting state in this folder so later claims can be checked against it:
      database **9,566 kB** (2026-09-05), **no backup has ever been taken**, disk 30 GB at
      **23%** after the expansion, bucket `gs://aceroai-backups` created in the `us`
      multi-region with public access prevention on and uniform access
- [x] 0.2 ⚠ **`pg_dump` in the built image is not older than the server — VERIFIED BY
      BUILDING IT**, not by reasoning: `python:3.12-slim` resolves to Debian 13 (trixie),
      whose own repository carries `postgresql-client-17` at 17.11, so no third-party apt
      repository is needed. The built image reports
      `pg_dump (PostgreSQL) 17.11 (Debian 17.11-0+deb13u1)`. The base is now pinned to
      `python:3.12-slim-trixie` so a future float to a Debian without that package is a build
      failure rather than a silent downgrade. Original wording follows:
      **Confirm `pg_dump` in the built image is not older than the server.** Build the
      image and run `pg_dump --version` inside it; the server is Postgres 17
      (`pgvector/pgvector:pg17`) and a client older than 17 refuses to dump it outright. Pin
      the client version explicitly rather than inheriting whatever the base image's Debian
      release provides — see `design.md` Decision 10. **If this cannot be made to hold, stop
      and re-plan**: every other task assumes a dump can be taken at all
- [x] 0.3 ⚠ **RESOLVED, AND IT WAS NOT A FLAKY TEST — it was a production defect.** The
      live lead was right: the missing row was always an early-inserted one, because
      `ORDER BY distance LIMIT n` leaves **exact ties unordered**, and the surviving rows were
      then chosen by physical row position. Two independent faults, both fixed:
      **(a) production** — `recall.vector_rank`, `memory.nearest_active` and the knowledge-graph
      neighbour query all ranked by distance alone, so the same question against unchanged data
      could recall different facts on consecutive calls. Ordering is now total
      (`distance, created_at DESC, id`): between two equally relevant memories, the newer wins.
      **(b) the fixture** — `1 + (i % 3) * 0.05` produced spreads of 1.00/1.05/**1.10**, and 1.10
      is exactly the spread of both certification facts, so seven filler facts sat at an
      identical distance to the rows the test asserted about. A test tied with its own filler
      asserts something the data does not determine, whatever the tiebreak rule is.
      **Neither is a quarantine.** Three regression tests added; two of them were confirmed RED
      against the old ordering before the fix was committed, and the third is honest in its own
      docstring about being a guard rather than a reproduction. Original wording follows:
      **Deal with the five flaky memory tests.** They fail at random in CI and a failed
      test blocks the deploy, so they will otherwise interrupt this change at an arbitrary
      point and be indistinguishable from a real regression introduced here. The prior
      investigation eliminated six hypotheses (fresh database, pgvector 0.8.5 vs 0.8.6, CI
      ordering, parallel workers, venv drift, and an HNSW index — disproved by `EXPLAIN`
      showing a sequential scan) and left one live lead: **in all five failures the missing
      row is the first-inserted or pre-existing one**, which makes this a row-visibility
      question rather than a vector-similarity one. Pursue that lead on a timebox; if it does
      not resolve, quarantine the five with an explicit skip marker naming this task and the
      lead, so the suite becomes trustworthy either way. A quarantine is an acceptable
      outcome; an intermittently red suite during this change is not
- [x] 0.4 Confirm the service account grant actually works end to end before building on it:
      from the VM, write and then delete a single test object in `gs://aceroai-backups` using
      Application Default Credentials. This proves the IAM grant, the access scopes and the
      metadata-server credential path together, and it is a one-line failure now rather than a
      confusing one later
- [x] 0.5 Full suite before touching anything: **575 passed**. ⚠ The first two attempts hung for 25 minutes against a dev database container that had been stopped for 43 hours — worth recording because a hung suite and a slow suite look identical from the outside

## 1. The object-store adapter

- [x] 1.1 `app/adapters/__init__.py` and `app/adapters/object_store.py` — the only module that
      imports `google.cloud.storage`, exposing `put`, `get`, `list_prefix` and `delete` over
      bytes, with a docstring recording why `adapters/` exists as a boundary
- [x] 1.2 The client is built **lazily**, never at import: CI has no credentials, and an import
      that requires them breaks collection of every test in the suite
- [x] 1.3 An in-memory implementation of the same interface for tests, in `tests/`, not in
      application code
- [x] 1.4 `google-cloud-storage` added with `uv add` (approved 2026-09-05); `uv.lock` committed

## 2. Taking a copy

- [x] 2.1 `app/services/backups.py` — `take_dump()` runs `pg_dump --format=custom` against the
      configured database as a subprocess, returning bytes plus the process result. Never
      through the ORM session: this is an external tool, and its failures are exit codes and
      stderr, not SQLAlchemy exceptions
- [x] 2.2 The connection details come from the existing `DATABASE_URL`. No second place to
      configure the database, and no new secret
- [x] 2.3 `build_manifest(db, dump_bytes)` — `taken_at`, server version, byte count, SHA-256,
      and a per-table row count. ⚠ **The plan's second sentence turned out to be unachievable
      and was wrong to assert.** It said the counts are read "in the same transaction the dump
      is consistent with"; they are not, and cannot be — `pg_dump` holds its own snapshot on
      its own connection, so a row written between the dump and the count leaves the dump
      holding slightly MORE than the manifest claims. Rather than pretend otherwise, the
      asymmetry is now the design: `first_shortfall` fails on a shortfall and tolerates a
      surplus, because a surplus can only mean the manifest was a moment later, while a
      shortfall is the actual danger. Closing the race properly would need the counts to come
      from inside pg_dump's snapshot, which its interface does not offer
- [x] 2.4 `object_names(now)` — returns the prefixes this copy belongs under: always `daily/`,
      additionally `weekly/` on Sundays, additionally `monthly/` on the 1st. Pure function,
      tested directly against a year of dates including the case where the 1st is a Sunday
- [x] 2.5 Upload the dump and its manifest under every applicable prefix; a partial upload
      (dump written, manifest not) is a failure, and the run reports it as one

## 3. Proving a copy restores

- [x] 3.1 `verify_newest()` — locate the newest object under `daily/`, download it and its
      manifest, and compare the SHA-256 **before** attempting any restore. A checksum failure
      is reported without restoring: there is nothing to learn from restoring a file already
      known to be wrong
- [x] 3.2 Restore into a scratch database created for the purpose, dropping any leftover from
      an interrupted previous run first
- [x] 3.3 Compare every table's row count against the manifest and report the first mismatch by
      table name with both counts. Comparison is against the manifest, never against the live
      database, which has moved on since the dump
- [x] 3.4 Drop the scratch database in a `finally`, so a failure part-way through cannot leave
      it behind or leave the next run unable to start
- [x] 3.5 The live database is untouched by a failed verification — **covered in two places,
      and neither is the full automated test the plan described.** The checksum path is tested
      (`test_a_checksum_mismatch_is_caught_before_anything_is_restored`) and it raises before
      any database is created at all, which is the strongest form of the guarantee. The
      mid-restore failure was verified **manually** in the end-to-end run (8.4b): the scratch
      database was confirmed gone afterwards with `SELECT datname FROM pg_database`. Automating
      that second case needs `pg_restore` on the test machine, which CI does not have —
      recorded rather than quietly counted as done

## 4. The three jobs

- [x] 4.1 `app/jobs/backups.py` — `db_backup`, nightly, `uses_ai=False`, with a `catch_up`
      generous enough that a restart does not silently skip a night
- [x] 4.2 `db_backup` reports success silently (`JobResult(silent=True)` with counts in
      `detail`) and notifies only on failure. A nightly "backup succeeded" notification would
      train the user to ignore the one that says it did not
- [x] 4.3 `restore_check`, monthly, `uses_ai=False`. Silent when the copy verifies; notifies on
      checksum failure, restore failure or row-count mismatch
- [x] 4.4 `backup_watch`, daily, at a different hour from `db_backup`. Reports when the newest
      successful `db_backup` in `job_runs` is older than the configured bound. **A separate job
      by design** — see `design.md` Decision 6 — with that reasoning in its docstring, because
      it is exactly the kind of thing a later reader would helpfully merge into `db_backup` and
      thereby break
- [x] 4.5 `backup_watch` follows the `disk_watch` convention: an unresolved condition is
      repeated daily rather than announced once
- [x] 4.6 Each run writes counts and identifiers to `job_runs.detail` — bytes, duration, object
      name, total rows — and never message text, per the column's stated rule

## 5. Configuration and retention

- [x] 5.1 New settings: bucket name, object prefix root, and the staleness bound for
      `backup_watch`, each with a comment explaining the value chosen. An empty bucket name
      disables the jobs cleanly rather than failing nightly, so a developer machine is not
      required to have a bucket
- [x] 5.2 Lifecycle rules on the bucket — configured 2026-09-06: `daily/` 14d, `weekly/` 56d, `monthly/` 365d, each with its prefix set. Original wording: — `daily/` 14 days, `weekly/` 56 days, `monthly/` 365
      days — configured in the console and **recorded in `docs/DEPLOY.md`**, since they are
      part of the system's behaviour and live outside the repository. Note explicitly that this
      is the one part of retention that cannot be verified by a test
- [x] 5.3 Confirm after configuring: bucket soft-delete is on by default and retains deleted
      objects for a further period; this is harmless at this size but should not be a surprise
      when object counts do not match expectations

## 6. Deployment

- [x] 6.1 `backend/Dockerfile` installs the PostgreSQL client at the pinned version from task
      0.2, with a comment stating why the version is pinned rather than floating
- [x] 6.2 A startup assertion that the available `pg_dump` is not older than the server, so a
      base-image change that silently downgrades it fails loudly at deploy rather than
      quietly at 3 a.m. months later
- [x] 6.3 Confirm image size growth is acceptable and record the before/after

## 7. Tests

- [x] 7.1 Manifest construction — checksum, counts, and that a manifest describes the dump it
      was built from
- [x] 7.2 `object_names` across a year of dates, including a 1st that falls on a Sunday
- [x] 7.3 Verification against a manifest: matching, one table short, a table missing entirely,
      a surplus (tolerated, see 2.3), a stable choice of which table is named, and checksum
      mismatch
- [x] 7.4 `backup_watch` boundaries: within the bound, exactly at it, past it, and the case
      where `db_backup` has never run at all — which must report, not stay silent
- [x] 7.5 A failed upload is recorded as failed and notifies; it is not recorded as a quiet
      night
- [x] 7.6 The whole suite runs with no credentials and no network, through the in-memory
      adapter. Note in the change record that CI proves the logic and production proves the
      round trip — the real upload is asserted by `restore_check`, not by a test

## 8. Verification

- [x] 8.1 From `backend/`: `uv run ruff format .`
- [x] 8.2 From `backend/`: `uv run pytest` — the full suite, green, with the count recorded and
      compared against 0.5. ⚠ Never start a second run while one is in flight: the suite shares
      the dev database and its fixtures purge it, so concurrent runs produce dozens of false
      failures
- [x] 8.3 From `frontend/`: `npm run lint` **and** `npm run build`. Lint runs checks that the
      build does not; this change touches no frontend code, so both should pass untouched, and
      running them confirms that rather than assuming it
- [x] 8.4 Confirm `.env` is **not** staged before committing
- [x] 8.4b ⚠ **Beyond the plan: a real dump and a real restore, end to end.** Docker was
      available locally, so `take_dump` and `verify_newest` were exercised for real inside the
      built image against the live dev database rather than left to the post-deploy steps —
      264,397 bytes, 1,068 rows across 14 tables, restored into a scratch database and
      compared. **Both failure paths were then made to fire**: the copy was truncated (checksum
      rejected it) and a manifest count inflated (`restored with 1 rows in 'users', manifest
      says 1000`). The scratch database was confirmed dropped afterwards. This is the half the
      test suite cannot prove, and it is now proven before deploy rather than after
- [x] 8.5 Done 2026-09-06 — `db_backup -f` returned `ok`, dump and manifest both present in the bucket. Original wording:, on the VM: force one `db_backup` run and confirm the object and its
      manifest appear in the bucket
- [x] 8.6 Done 2026-09-06 — `restore_check -f` returned `ok`: the real backup was rebuilt into a scratch database and every table matched its manifest. Original wording:: force one `restore_check` run against that object and confirm it
      verifies, then confirm the scratch database no longer exists
- [x] 8.7 Done 2026-09-06 — bucket pointed at a nonexistent name, `db_backup` reported `cannot write 'daily/agent-20260905T184251Z.dump'`, and the notification **arrived on the phone**. Setting restored and verified. Original wording: **Prove the alarm works by breaking it on purpose.** Point the bucket setting at a
      name that does not exist, run `db_backup`, and confirm the failure notification arrives
      on the phone. Restore the setting afterwards. An untested alarm is the same class of
      thing as an untested backup

## 9. Documentation

- [x] 9.1 `docs/DEPLOY.md` — the bucket, the IAM grant on the bucket rather than the project,
      the lifecycle rules, and the fact that no key file is involved
- [x] 9.2 `docs/JOBS.md` — the three new jobs, their schedules, and what each notifies about
- [x] 9.3 `docs/ARCHITECTURE.md` — backups in the component picture, and `adapters/` as a new
      boundary with its reason
- [x] 9.4 `docs/ROADMAP.md` — "no database backup" is the highest-risk entry there; close it,
      and record what is now true instead, including the accepted 24-hour loss window
- [x] 9.5 The Learn page — a card on why a backup that has never been restored is not a backup,
      which is the idea in this change most worth keeping
- [x] 9.6 **Docs and diagrams reflect what was built.** If any diagram, document or Learn card
      turns out not to need changing, say so explicitly here rather than dropping the item, so
      that "checked" and "forgotten" stay distinguishable
