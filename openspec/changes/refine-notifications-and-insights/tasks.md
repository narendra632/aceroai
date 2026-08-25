# Tasks

## 0. Verify the assumptions before any production code

Everything in this section is a belief about a runtime, not a fact about the code. Each one is
load-bearing for something built later, and each is cheap to check now and expensive to
discover wrong afterwards.

⚠ The container checks require the VM, which only Narendra can reach. They are therefore
**deferred to deployment**, and the code is written so that a wrong assumption degrades a
single reading rather than breaking anything — which is the reason each reader is independently
failure-isolated in section 4.

- [x] 0.1 **Verified.** On Windows `MEMINFO.exists()` is False, and `memory()` and
      `load_average()` both return `None` without raising — confirmed both against the real
      absent `/proc` and against paths pointed deliberately at nothing. `disk()` works and
      returns `None` for an invalid path
- [x] 0.2 **Verified: mean 1.46 ms** over 10 warm calls (min 1.05, max 1.82) against a 32.5 MB
      development database. Cheap enough for a 10-second poll with three orders of magnitude
      to spare
- [x] 0.3 **Six readers of `notifications`, and exactly two exceptions**, matching the design:
      *lists rows, must filter* — `list_for_user`, `unread_count`, `mark_read`,
      `mark_all_read`; *asks what happened, must not filter* — `_pushed_today`,
      `_already_said`. `raise_notification` writes; `prune_notifications` deletes by age and
      correctly ignores `deleted_at`, so soft-deleted rows age out normally
- [x] 0.4 **Confirmed.** `_already_said` selects on `(user_id, kind, tag)` with **no time
      bound and no deleted filter**. Both facts matter: the missing filter is the invariant to
      preserve, and the missing time bound is what `disk_watch` has to fix to reuse it
- [x] 0.5 **Confirmed:** `if cap and _pushed_today(db, user.id) >= cap`. Zero is falsy, so
      `0` already means unlimited and no new branch is needed
- [x] 0.5a ⚠ **Found while timing 0.2, and it invalidates part of the plan.** `last_tick` was
      to be read from the newest `job_runs` row. That is wrong: a row is written only when an
      occurrence fires, and there are **six hours between the 21:00 nudge and the 03:15
      sweep** in which a healthy scheduler writes nothing. The reading would have reported a
      dead scheduler every night. Replaced with an in-process heartbeat set by `tick_once()`
      — cheaper, and it targets the actual failure (the APScheduler thread dying while uvicorn
      keeps serving). See design Decision 12
- [x] 0.5b The `job_runs(started_at DESC)` index the original plan implied is **not** added.
      Measured at 0.04 ms on a sequential scan, and the query it would have served no longer
      exists — it was measuring the wrong thing, not measuring it slowly
- [x] 0.5c Confirmed the API runs as a **single uvicorn process** (no `--workers` in the
      Dockerfile `CMD`), which is what makes an in-process heartbeat valid. Not a new
      assumption — two workers would already mean two schedulers
- [ ] 0.6 Reproduce the notification panel flash deliberately (throttle the network in
      DevTools and open the bell) so the defect is observed rather than assumed, and so there
      is something to compare against afterwards

### Deferred to deployment (verified on the VM, not before)

- [ ] 0.7 Inside the running `api` container, confirm `/proc/meminfo` `MemTotal` reports the
      host's ~1 GB rather than a cgroup limit. `docker-compose.prod.yml` sets no `mem_limit`
      on `api`, which is *why* this should hold — if a limit is ever added, this reading
      silently starts meaning something else
- [ ] 0.8 In the same container, confirm `shutil.disk_usage("/")` reports the host's ~10 GB
      through the overlay filesystem, and not a container-sized figure. ⚠ `disk_watch`
      depends on this being right — a container-sized reading would make the threshold
      meaningless
- [ ] 0.9 Confirm `/proc/loadavg` is readable from the container and its first field is the
      1-minute average

## 0b. Three defects found while getting the existing suite green

None of these were in the plan. All three were **already in the code**, and all three were
found because the suite stopped passing on the development machine while remaining green in
CI — which is itself the finding that connects them.

- [x] 0b.1 ⚠ **The job advisory lock never worked, and leaked connections.**
      `pg_try_advisory_lock` is scoped to a Postgres *connection*; a SQLAlchemy `Session` is
      not pinned to one, and `Session.commit()` returns its connection to the pool.
      `run_job` commits several times, so the `finally`'s `pg_advisory_unlock` ran on a
      **different connection than the one holding the lock**. Two consequences: the lock
      leaked onto pooled connections (observed as idle backends whose last statement was
      `ROLLBACK`, still holding locks for finished jobs), and it **excluded nothing** — a
      concurrent run would check out a different connection and acquire it happily. The
      `UNIQUE (job_name, occurrence_key)` constraint had been carrying the guarantee alone.
      Fixed with a dedicated connection held for the job's lifetime (`_job_lock`). The
      comment claiming "the lock dies with the connection anyway" was false under pooling
      and is gone
- [x] 0b.2 ⚠ **The test suite depended on the developer's `.env`.** Eight tests assert the
      unconfigured-push behaviour and passed only because CI and a fresh checkout have no
      VAPID keys. They began failing the moment real keys were added locally in order to
      test push on a phone. Fixed with an autouse fixture that blanks the keys for every
      test; `fake_push` sets its own on top
- [x] 0b.3 ⚠ **Six tests asserted on rows they did not create.**
      `select(PushSubscription)` with no `WHERE` counted the real browser subscription
      registered during local push testing. Scoped to the test user, with the reason in the
      module docstring
- [x] 0b.4 A latent one, found in passing: the quiet-hours test set a 0..23 window commented
      "effectively always quiet, whatever time the suite runs". The window is half-open, so
      hour 23 falls outside it — the test was wrong for exactly one hour a day. Now derived
      from the current hour, which also exercises the midnight wrap once daily
- [x] 0b.5 Suite green: **501 passed**

## 1. Migration 012

- [x] 1.1 New Alembic revision `012`, down-revision `e1f2a3b4c5d6`
- [x] 1.2 `notifications` gains `deleted_at TIMESTAMPTZ NULL`
- [x] 1.3 `generated_reviews` gains `deleted_at TIMESTAMPTZ NULL`
- [x] 1.4 Partial indexes on the live rows for both tables, matching how the other
      soft-deleted tables are indexed — the existing per-user ordering queries are the ones
      that must not regress
- [x] 1.5 `downgrade()` drops both columns and both indexes
- [x] 1.6 Verify `upgrade` → `downgrade` → `upgrade` on a scratch database, with rows present
      in both tables, and confirm no data is lost by the round trip
- [x] 1.7 Add both columns to `db/models.py`, with a comment on `notifications.deleted_at`
      pointing at the push-cap invariant so the next reader meets it before they change a
      `WHERE` clause

## 2. Notifications: removal, in the services layer

- [x] 2.1 `list_for_user` excludes deleted rows
- [x] 2.2 `unread_count` excludes deleted rows — a deleted unread notification must not keep
      the badge lit
- [x] 2.3 `mark_all_read` excludes deleted rows
- [x] 2.4 `mark_read` refuses a deleted row exactly as it refuses one that never existed
- [x] 2.5 `delete_notification(db, user_id, notification_id)` — soft, idempotent, returns the
      row or `None`
- [x] 2.6 `restore_notification(db, user_id, notification_id)` — the undo path
- [x] 2.7 `clear_read(db, user_id) -> list[uuid]` — soft-deletes every read, undeleted row and
      **returns the ids it actually deleted**, so undo restores exactly that set and not
      whatever happens to be read at the time undo is pressed
- [x] 2.8 `restore_notifications(db, user_id, ids)` — the batch undo
- [x] 2.9 ⚠ **`_pushed_today` is left filtering on `pushed_at` only, with no `deleted_at`
      clause**, and gains a comment stating why. A count of deliveries is a count of
      deliveries, not of surviving receipts — see design Decision 2
- [x] 2.10 ⚠ **`_already_said` is left unfiltered too**, and gains the stronger comment of the
      two. Filtering it would make dismissing a notification cause the next hourly nudge to
      re-push it — delete would silently mean "remind me within the hour"
- [x] 2.11 `prune_notifications` needs no change: a soft-deleted row ages out on the existing
      90-day cutoff. Confirm this is true rather than assuming it, and record the answer

## 2b. The daily ceiling is removed; the count stays

- [x] 2b.1 `settings.daily_push_cap` default `6` → `0`. No code change accompanies it —
      `_cap` is already consulted as `if cap and ...`, so zero suppresses nothing
- [x] 2b.2 Confirm `_suppression_reason` therefore never returns the cap reason at the new
      default, and that quiet hours are entirely unaffected
- [x] 2b.3 The mechanism is **retained, not deleted** — a job that loops is a real failure mode
      and per-tag suppression is no defence against a bug in the code computing the tags.
      Comment it as the extinguisher it now is
- [x] 2b.4 `PushStatusOut` keeps `daily_push_cap` and gains today's delivered count
- [x] 2b.5 Settings: the cap control becomes a plain readout — "N sent today" — with no
      ceiling attached and no input to change
- [x] 2b.6 `.env.example` and `docs/NOTIFICATIONS.md` updated: the default is unlimited, and
      what a non-zero value would be for
- [x] 2b.7 Existing tests that assert cap suppression are rewritten to set a cap explicitly
      rather than relying on the default. ⚠ A test that passes only because the default is 6
      is a test that will fail silently-wrong later

## 2c. `_already_said` gains a time bound

- [x] 2c.1 Optional `since: dt.timedelta | None = None` parameter; `None` preserves today's
      "has this ever been said" behaviour exactly
- [x] 2c.2 `task_nudge` passes nothing and is behaviourally unchanged — its tag is a hash of a
      set that genuinely changes, so an unbounded lookback is correct for it
- [x] 2c.3 Document why the bound exists: a tag that can **recur** needs one, and a tag that
      encodes a changing set does not. Getting this backwards produces either an alert that
      fires once per installation, or one that fires every run

## 3. Notifications and briefings: the API

- [x] 3.1 `DELETE /api/notifications/{id}` → the removed row
- [x] 3.2 `POST /api/notifications/{id}/restore` → the restored row
- [x] 3.3 `POST /api/notifications/clear-read` → the ids removed, for the undo to hold
- [x] 3.4 `POST /api/notifications/restore` taking those ids
- [x] 3.5 Every one of them scoped to `get_current_user`, and a 404 for another user's id that
      is indistinguishable from a 404 for an id that does not exist
- [x] 3.6 `services/journal.py`: `delete_briefing` / `restore_briefing` on `generated_reviews`,
      user-scoped, and `list_briefings` excluding deleted rows
- [x] 3.7 `DELETE /api/journal/briefings/{id}` and `POST /api/journal/briefings/{id}/restore`
- [x] 3.8 Schemas for all of the above in `api/schemas.py`

## 4. Vital signs: the reading layer

- [x] 4.1 `services/vitals.py` (or an equivalent section of `services/insights.py`) with one
      function per reading, each returning `None` rather than raising when it cannot measure
- [x] 4.2 Disk via `shutil.disk_usage`
- [x] 4.3 Memory via `/proc/meminfo`, using **`MemAvailable`, not `MemFree`** — on a box
      running Postgres, `MemFree` looks alarming and means nothing, because the page cache is
      doing its job
- [x] 4.4 Load average via `/proc/loadavg`, first field only
- [x] 4.5 Database size via `pg_database_size(current_database())`
- [x] 4.6 Last scheduler tick from the newest `job_runs` row, distinguishing **"never"** from
      "a long time ago" — they mean different things and only one of them is a fault
- [x] 4.7 Process uptime from a start time recorded at import
- [x] 4.8 Every reader is individually failure-isolated: one unreadable file must degrade one
      field, never the response

## 5. Vital signs: the endpoint

- [x] 5.1 `GET /api/insights/vitals`, behind `get_current_user`, in the existing insights
      router
- [x] 5.2 `Cache-Control: no-store` on the response
- [x] 5.3 ⚠ `/health` is **left exactly as it is** — it is unauthenticated and is what proves
      the backend is alive from outside the network. Confirm explicitly that this change adds
      nothing to it
- [x] 5.4 Response model with every measurement optional, so an absent reading is expressible
      in the type rather than encoded as a zero

## 5b. `disk_watch`

- [x] 5b.1 `settings.disk_warn_percent: int = 80`, and a band width of 5
- [x] 5b.2 `@job("disk_watch", "0 */6 * * *", catch_up=dt.timedelta(hours=2))` in
      `jobs/housekeeping.py`, `uses_ai=False`. ⚠ The catch-up window must be shorter than the
      6-hour gap or the registry refuses it at import — which is the guard working
- [x] 5b.3 Reads through the **same function the vitals endpoint uses**. One definition of
      "how full is the disk", not two that can drift apart
- [x] 5b.4 Below the threshold — and when the reading is unavailable — return
      `JobResult(silent=True)`. ⚠ An unmeasurable disk must never be reported as a full one
- [x] 5b.5 Tag is the 5% band the reading falls into (`disk-80`, `disk-85`, `disk-90`), so a
      disk sitting at 81% does not chatter across a single number
- [x] 5b.6 Suppressed with `_already_said(..., since=24h)`: told once on crossing a band,
      reminded daily while still above it
- [x] 5b.7 The notification says the percentage and the free space in plain units, and links
      somewhere useful
- [x] 5b.8 `detail` records the percentage and the band — counts and identifiers only, as
      `JobResult.detail` requires
- [x] 5b.9 Appears in Settings with the other jobs and can be turned off, for free, because it
      is registry-driven
- [x] 5b.10 Confirm no migration is needed — `user_job_prefs` is sparse, which was the point of
      building it that way

## 6. The API client

- [x] 6.1 `deleteNotification`, `restoreNotification`, `clearReadNotifications`,
      `restoreNotifications`
- [x] 6.2 `deleteBriefing`, `restoreBriefing`
- [x] 6.3 `getVitals`, with a type where every measurement is nullable

## 7. The notification panel

- [x] 7.1 Introduce `status: "loading" | "ready" | "error"`; stop treating an empty array as
      an answer
- [x] 7.2 The skeleton is shown **only when nothing is cached**. On re-open, the rows already
      held stay visible while a fresh copy loads — this is what removes the flash rather than
      replacing it with a spinner
- [x] 7.3 An error state that says the list could not be loaded and offers a retry, distinct
      from "Nothing yet."
- [x] 7.4 ⚠ Restructure the row: it is currently a single `<button>`, and a button may not
      nest inside a button. The row becomes a container with the open-action and the
      dismiss-action as siblings
- [x] 7.5 Per-row dismiss, always rendered rather than revealed on hover — there is no hover
      on the phone this app is installed on
- [x] 7.6 `aria-label` on dismiss naming the notification it removes, so it is distinguishable
      when read aloud or reached by keyboard
- [x] 7.7 Dismiss must not trigger the row's open action — stop propagation, and verify by
      keyboard as well as by pointer
- [x] 7.8 "Clear read" in the panel header, beside "Mark all read", shown only when there is
      something read to clear
- [x] 7.9 Both actions go through `toast.undo()` and optimistic mutation with rollback, in the
      idiom `TasksView.remove` established
- [x] 7.10 The unread badge updates correctly when an **unread** notification is dismissed
- [x] 7.11 Both the Popover and the Sheet variant carry all of this — they are separate render
      paths and this project has already shipped a bug that lived in only one of them

## 8. Briefings

- [x] 8.1 Per-row delete with undo, matching the journal entry treatment on the sibling tab
- [x] 8.2 The existing loading skeleton is already correct — confirm and leave it alone
- [x] 8.3 The empty state must not be reachable by deleting the last briefing without the
      user understanding why: check the copy still reads correctly in that case

## 9. The shell header

- [x] 9.1 Extend `TITLES` to carry a title and a subtitle per view
- [x] 9.2 The desktop strip becomes the page header: title and subtitle on the left, the bell
      on the right. Its comment — *"this strip exists only to give the bell somewhere to
      live"* — is deleted along with the reason for it
- [x] 9.3 `InsightsView` drops its own `<header>`
- [x] 9.4 `KnowledgeView` drops its own `<header>`
- [x] 9.5 `SettingsView` drops its `md:block` `<h1>`
- [x] 9.6 `LearnView`'s in-content header reviewed for duplication and reconciled
- [x] 9.7 The mobile header is unchanged in structure and keeps the hamburger, the title and
      the bell — it was never the problem
- [x] 9.8 Check every view at desktop width for a doubled title or a lost one

## 10. The vitals block on Insights

- [x] 10.1 A bordered, labelled block above the cost tiles, with a live indicator
- [x] 10.2 Five readings as tiles consistent with the existing cost tiles, so they read as the
      same family without reading as the same group
- [x] 10.3 Capacity bars on disk and memory; plain values for the rest
- [x] 10.4 Threshold colouring on the two proportional readings, and **quiet otherwise** — a
      display that draws attention while everything is fine costs you the one moment it exists
      for
- [x] 10.5 The 7d/30d/90d/All control moves to the right-hand side of the vitals row,
      **outside** the border — it governs the content below, and the border is what says so
- [x] 10.6 Absent readings are omitted entirely. No zeros, no "unknown" tiles, no gaps where
      a tile would have been
- [x] 10.7 The last-tick reading is worded so "never" and "a while ago" are obviously
      different
- [x] 10.8 Polling every 10s, paused on `visibilitychange`, an immediate reading on return,
      and cleared on unmount
- [x] 10.9 The block renders independently of the main insights request — a failed overview
      must not hide the vitals, and a failed vitals poll must not hide the overview
- [x] 10.10 A failed poll leaves the last good reading visible and marks it stale rather than
      blanking the block
- [x] 10.11 375 px: the block wraps rather than overflowing, and the range control stays
      reachable

## 11. Tests

- [x] 11.1 Extend `test_soft_delete.py` for notifications: invisible to every reader, unread
      count, listing, mark-all-read, and restorable with the same identity
- [x] 11.2 Extend `test_soft_delete.py` for briefings, including that the job's `job_runs` row
      is untouched by deleting its output
- [x] 11.3 ⚠ **The repetition invariant:** raise a tagged notification, delete it, run the job
      again, and assert it stays **silent**. This is the test that stops someone "fixing"
      `_already_said` later, and it is the one that would otherwise be discovered as "the app
      keeps telling me about the same overdue task"
- [x] 11.4 ⚠ **The delivered-count invariant:** deleting delivered notifications does not
      reduce today's delivered count. Written against an explicitly set cap so it also proves
      the ceiling still works when someone chooses to set one
- [x] 11.4a A notification recorded but never delivered contributes nothing to the count,
      before or after deletion
- [x] 11.4b With the default settings, no notification is ever suppressed for volume — pins
      the removal of the ceiling, so it cannot come back by accident
- [x] 11.4c `_already_said` with a `since` window ignores a row older than the window, and
      without one still finds it — both halves, since only testing one would let the parameter
      silently do nothing
- [x] 11.4d `disk_watch`: silent below the threshold; raises on crossing; silent on the second
      run in the same band; raises again on crossing into the next band; **silent when the
      reading is unavailable**
- [x] 11.5 `clear_read` removes only read rows, and its returned id set is exactly what undo
      restores — including when something is marked read between the clear and the undo
- [x] 11.6 API tests for all six new routes, including another user's id returning 404
- [x] 11.7 Vitals: every reader returns `None` rather than raising when its source is missing,
      exercised by pointing them at a path that does not exist
- [x] 11.8 Vitals: one broken reader degrades one field and the response still succeeds
- [x] 11.9 Vitals: the endpoint requires authentication
- [x] 11.10 ⚠ `/health` returns exactly `{"status": "ok"}` and no more — pinned as a
      regression test, because the temptation to add "just one useful field" to it is exactly
      what this change is refusing
- [x] 11.11 Last-tick reports `None` for "never ticked", not a zero or an epoch date
- [x] 11.12 Confirm the whole suite still passes, and that nothing in it depends on
      notifications being undeletable

## 12. Documentation, diagrams, and the audit that was asked for

- [x] 12.1 ⚠ `frontend/src/lib/learn/content.ts` — the `rollup` step still says *"Runs once a
      day, on the first call of the day — no scheduler needed yet"*. Stale since the previous
      change moved it to `retention_sweep` at 03:15, on the same page that now explains the
      scheduler at length
- [x] 12.2 ⚠ `frontend/src/components/SettingsView.tsx` — *"This applies everywhere — web and
      Telegram."* Telegram was retired in migration 011
- [x] 12.3 ⚠ `backend/app/services/retention.py` — the rollup docstring still says it *"runs
      opportunistically and may fire twice for the same day"*. Reword to the scheduler
      reality while **keeping the idempotency rationale**, which is still the reason the
      upsert is written the way it is
- [x] 12.4 ⚠ `openspec/config.yaml` — the project context still lists Telegram as a live
      channel under the one-brain rule. This file feeds every future proposal, so its rot
      propagates further than any other file in this list
- [x] 12.5 Walk the whole Learn flow at desktop and phone width and confirm the jobs, push and
      PWA sections describe what was actually built — this was requested explicitly and is the
      point of the section existing
- [x] 12.6 Confirm the remaining Telegram references are the deliberate historical ones and
      leave them: `ARCHITECTURE.md` (the retained channel value and the ER label),
      `db/models.py` (the CHECK constraint comment), `ROADMAP.md`, and
      `docs/plans/phase0-completion.md`, which is a record of a past plan and must not be
      rewritten
- [x] 12.7 `docs/NOTIFICATIONS.md` — removal, the undo window, the removal of the ceiling, and
      **both** invariants: what a delivered count counts, and why deleting a notification does
      not make the nudge behind it repeat
- [x] 12.7a `docs/JOBS.md` — `disk_watch` in the job table, and a paragraph on band tagging
      and the `since` window, because that is the reusable half of it
- [x] 12.7b Any doc stating the daily cap as a live limit is corrected — it is now a readout
- [x] 12.8 `docs/ARCHITECTURE.md` — the ER diagram gains `deleted_at` on both tables; add the
      vitals endpoint where the API surface is described
- [x] 12.9 `docs/JOBS.md` — that deleting a briefing does not cause a re-run, and why
- [x] 12.10 A note, where a reader will actually meet it, that **memory and load are absent on
      Windows** and present only on the VM — so it does not read as a bug during local
      development
- [x] 12.11 `docs/ROADMAP.md` — record what this change closed, and that the disk-watch job
      is now a natural follow-on that was deliberately not taken
- [x] 12.12 Learn: an entry for the vitals, if and only if it teaches something rather than
      restating the interface. Any new Learn constant must be numeric — `api/learn.py`'s
      allow-list and `test_api_learn.py`'s int/float assertion are a security boundary
- [x] 12.13 **Docs and diagrams reflect what was built** — checked like the tests are

## 13. Verification

13.1-13.5 are automated and done. **Everything from 13.6 down is a human check** — a
person in front of the running app, or on the VM — and is deliberately left open rather
than assumed. 0.6-0.9 are the same: 0.6 wants a throttled browser, and 0.7-0.9 want the
container.

- [x] 13.1 `uv run ruff format .` from `backend/`
- [x] 13.2 `uv run ruff check .` from `backend/`
- [x] 13.3 `uv run pytest` from `backend/` — one run at a time, the dev database is shared
- [x] 13.4 `npm run build` in `frontend/` — this is the only thing that typechecks; `tsc
      --noEmit` checks nothing here
- [x] 13.5 `openspec validate refine-notifications-and-insights --strict`
- [ ] 13.6 Manually: open the bell on a throttled connection and confirm the flash from 0.6 is
      gone; dismiss one; undo it; clear read; undo that
- [ ] 13.7 Manually: delete a briefing, undo it, delete it again, and confirm no replacement is
      composed and no cost appears on Insights
- [ ] 13.8 Manually: watch the vitals update on a 10s clock, background the tab, confirm the
      requests stop, return, and confirm a reading is taken at once
- [ ] 13.9 Manually: confirm memory and load are simply absent locally on Windows and present
      after deploying to the VM
- [ ] 13.10 Every view at desktop and 375 px: one title, no duplication, nothing overflowing
- [ ] 13.11 Keyboard-only pass over the notification panel specifically — dismiss, clear read
      and undo must all be reachable. This is the check `ROADMAP.md` still lists as never
      having been done
- [ ] 13.12 Manually: force `disk_watch` above its threshold (point the reader at a full
      filesystem, or lower `disk_warn_percent` temporarily) and confirm one notification
      arrives, the second run in the same band is silent, and the next band speaks again
- [ ] 13.13 On the VM after deploying: complete the deferred checks 0.7–0.9, and confirm the
      disk percentage the job sees matches what `df -h` reports on the host
- [ ] 13.14 ⚠ Confirm `.env` is **not** staged before committing

## 14. Found while finishing, and worth recording

- [x] 14.1 **Two more instances of the exact rot this change was auditing for**, both of the
      "built work still described as planned" kind that the widened `learnings` requirement
      now covers. `docs/ARCHITECTURE.md` had a file-map row reading *"`app/jobs/` — **Empty
      package.** APScheduler is a dependency; no job is implemented yet"*, sitting **two rows
      below** the row describing the jobs inside it. `AGENTS.md` had the same claim twice
      over: a correct line about the jobs immediately followed by *"empty package — no
      scheduled job built yet"*, and a "Not built yet" list still naming jobs and PWA/push.
      A document that contradicts itself on the same screen is the clearest possible
      evidence that nobody re-read it
- [x] 14.2 `daily_push_cap` removed from the Learn allow-list — the sentence that quoted it
      is gone, and a dead entry in a security boundary is worse than dead code because it
      invites the reader to trust the list as complete
- [x] 14.3 `ARCHITECTURE.md` said "the 10 ORM tables"; there are 14
- [x] 14.4 The vitals endpoint's failure isolation was **moved from the readers to the
      endpoint**, after a test written to pass did not. Each reader handled its own expected
      failure, so a reader that raised outright took the whole response with it — the wrong
      shape for something polled every ten seconds. The guarantee is now structural
- [x] 14.5 ⚠ **The suite is not slower because of this change.** `tests/test_jobs.py` went
      from 5.0s to 27.7s and the full suite from 131s to 619s, which looked like the new
      per-job connection. Measured instead: `_job_lock` costs **8.8 ms**, while
      `hash_password` — bcrypt, in the per-test `user` fixture — costs **908 ms**, and an
      independent pure-CPU benchmark unrelated to this project ran **3-4x slower than this
      processor should**. The laptop was on battery at 26%. Plug it in before timing anything

## 15. Follow-up round (requested after the first look)

- [x] 15.1 ⚠ **The spend chart was silently understating spend.** `SERIES` had entries for
      `chat`, `embed` and `memory_extract` only, so `StackedArea` drew no band for
      `turns.kind = "job"` — the data was fetched and quietly dropped. The headline tile
      counted it (`summary` sums every kind), so **the chart disagreed with the number
      printed directly above it**. Measured: $0.00596 of scheduled spend across 4 calls,
      absent from the chart. Added as a fourth series, **Scheduled**
- [x] 15.2 `--series-4` added to both themes. Chosen by running the palette validator rather
      than by eye: light `#7c5cd6` on `#ffffff` and dark `#9179e8` on `#292824` both pass the
      lightness band, chroma floor, CVD separation and normal-vision floor. The one WARN
      (the existing green's contrast in light mode) is already relieved by the legend
- [x] 15.3 The "work you never see" note named only recall and learning. It now names the
      scheduled summaries too, since they are part of the fraction it quotes
- [x] 15.4 Server box spans the full width, and its tiles are **flex rather than a
      5-column grid** — the tile count varies by platform (five on the VM, three on Windows
      where `/proc` is absent) and a fixed grid left dead columns
- [x] 15.5 The four period figures moved into their own bordered box, a sibling of the
      Server box, with the range control **inside it on its heading line**. Each box now
      names its own time: "Server · right now" against "Cost and speed · last 30 days"
- [x] 15.6 That box renders in **every** state, including loading and error. The range
      control lives inside it, and a control that vanishes while its own data loads is a
      control missing at the one moment you want to change your mind
- [x] 15.7 Verified the scheduled calls on Insights are correct rather than assuming it.
      Aug 25 10:17 `morning_brief` was **due at 07:30** and ran at 10:17 because the machine
      was off until then — inside its 4-hour catch-up window. That is the catch-up policy
      working, visible in production for the first time
- [ ] 15.8 ⚠ **Noticed, not fixed, and out of scope here.** One `job` turn (Aug 24 10:00)
      has no matching `job_runs` row. A `force=True` re-run bypasses `already_ran` and
      spends money, but its `_record` then hits `UNIQUE (job_name, occurrence_key)` and the
      `IntegrityError` is deliberately swallowed — so a forced re-run is **invisible in job
      history while still costing money**. Worth a distinct occurrence key for forced runs
