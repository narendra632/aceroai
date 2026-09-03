## 0. Establish the baseline

- [x] 0.1 Record the current production evidence in the change folder so the fix can be
      checked against it later: `task_nudge` has raised exactly one notification ever
      (2026-08-24 19:04:53, tag `overdue-d2ffe9d7351b535e`, never delivered, since deleted),
      and every run since 2026-08-26 10:00 returns `{"overdue": 1, "already_told": true}`
      — recorded in `proposal.md` and quoted in the code and tests that fix it
- [ ] 0.2 Confirm the reschedule that triggered the bug: the task's `updated_at` should fall
      between 16:00 and 17:00 on 2026-08-25 — **NOT RUN**, needs the VM. It is optional
      confirmation rather than evidence: the reschedule is already *forced* by the data, since
      the tag matching at all proves the 08-24 notification was about the same task, whose due
      time is now later than the moment it was already overdue. The six consecutive
      `detail: null` runs (08-25 17:00 → 08-26 09:00) date it to that hour independently
- [x] 0.3 Run the full suite before touching anything and record the count — **546 passed**

## 1. Schema

- [x] 1.1 Write migration 013 adding `notifications.push_count`, with a column comment
      stating that it counts deliveries, not records
- [x] 1.2 ⚠ **Corrected while writing it.** The design said `DEFAULT 1` with no backfill,
      because every existing delivered row was delivered exactly once. True of those rows and
      wrong for the column: a DDL default also applies to future inserts, and a notification
      is INSERTed *before* delivery is attempted, so a row that never reaches a device would
      claim an interruption that never happened — and such rows are common (quiet hours, no
      subscription). Now `DEFAULT 0` plus a one-time
      `UPDATE ... SET push_count = 1 WHERE pushed_at IS NOT NULL`. `design.md` updated
- [x] 1.3 Update the `Notification` model — `push_count` added, `pushed_at` docstring changed
      to "when it was **last** delivered"
- [x] 1.4 Verify up → down → up with rows present: delivered row backfilled to 1, undelivered
      row 0, column dropped and both rows intact on downgrade, restored on re-upgrade

## 2. Delivery: urgency and lifetime

- [x] 2.1 `URGENCY = "high"` for every notification, with the RFC 8030 levels and the
      production measurement recorded next to the constant
- [x] 2.2 `_DIGEST_KINDS` deleted; nothing else read it
- [x] 2.3 `jobs/runner._deliver` passes `notifications.ttl_for(job.catch_up)` through
      `raise_notification` to `deliver`
- [x] 2.4 `catch_up=None` maps to `MAX_TTL_S` (four weeks, FCM's maximum) rather than an
      absent header, which the protocol does not allow; notifications raised outside a job use
      `push_ttl_default_s`
- [x] 2.5 `push_ttl_digest_s` / `push_ttl_nudge_s` replaced by `push_ttl_default_s`; also
      updated in the `learn.py` allow-list and its schema, which expose them
- [x] 2.6 `_suppression_reason` untouched — quiet hours, the ceiling and the
      unconfigured-push case behave exactly as before, and a test pins that urgency did not
      quietly become an override

## 3. Repeat delivery against one record

- [x] 3.1 `deliver_again(db, user, row, *, ttl)` — re-sends an existing record, sets
      `pushed_at` and increments `push_count` through one shared `_record_delivery`, so the
      timestamp and the counter cannot disagree
- [x] 3.2 `todays_record(db, user_id, kind, tag)` — live and created since local midnight,
      with both bounds explained in the docstring
- [x] 3.3 `pushed_today` sums `push_count`, keeping its deliberate refusal to filter
      `deleted_at`
- [x] 3.4 `already_said` docstring corrected: it records the reasoning that was wrong, states
      the new test (does the tag contain something monotonic?), and marks itself as being for
      band-crossing subjects only

## 4. The overdue nudge

- [x] 4.0 Schedule `0 9-19 * * *` — eleven checks a day, verified against the real
      `CronTrigger`. **Revised after review**: see 4.6
- [x] 4.0a `catch_up` 45 min, under the 1-hour gap; the registry's `catch_up < min_period()`
      check passes at import
- [x] 4.0b The 21:00 collision is **resolved rather than deferred** — see 4.7
- [x] 4.0c **Not in the plan:** `human_schedule` had no case for a step (`9-21/2`) and fell
      through to printing the raw cron expression in Settings. Added, along with `*/6` — which
      means `disk_watch` stops showing `0 */6 * * *` to a person and now reads "every 6 hours"
- [x] 4.1 `due_at` included in the fingerprint
- [x] 4.2 `already_said` removed from `task_nudge`; find-or-create against `todays_record`
- [x] 4.3 `detail` carries `{"overdue": n, "reminder": k}` on a repeat
- [x] 4.4 Notification text unchanged; the module docstring records that the behaviour is
      deliberately not explained in it
- [x] 4.5 Coalescing unchanged — existing test still passes untouched

### Revised after reviewing the behaviour (fixes 1-3)

- [x] 4.6 **Detection and repetition separated.** A single two-hourly schedule had silently
      made the repetition interval the DETECTION delay as well: a task falling due at 11:05
      was not overdue at the 11:00 check and went unmentioned until 13:03. The check now runs
      hourly and `REMIND_EVERY = 2h` paces the interruptions. Found within the hour, nagged
      every two — which is what "remind me every 2 hours" actually meant
- [x] 4.6a Pacing measures time since the last **delivery**, not since the record was written,
      so a reminder held back by quiet hours is not counted as an interruption that already
      happened and goes out once the window ends
- [x] 4.6b A check between reminders returns `silent` with `{"holding": true}` — the job ran
      and correctly said nothing, which is exactly what `silent` is for
- [x] 4.7 **Window ends at 19:00.** `day_end_summary` fires at 21:00 and already lists what is
      overdue; two notifications in the same second saying overlapping things is how a
      reminder starts reading as noise. Pinned by a test that samples both jobs' real triggers
      rather than parsing their cron strings
- [x] 4.8 **A reminder describes the situation as it reads now.** `JobResult.remind` carries a
      `Reminder(record, title, body)` rather than a bare row, and `deliver_again` updates the
      wording before sending. Renaming an overdue task changes what the reminder says instead
      of repeating this morning's name. `created_at` and the tag are untouched, so "overdue
      since 10:03" survives — the tag pins WHICH situation, the wording describes it

## 5. Frontend

- [x] 5.1 "Reminded N times · last 2h ago" under the body when `push_count > 1`, in muted
      metadata type rather than as a badge
- [x] 5.2 `push_count` returned by the API and added to `NotificationRow`
- [~] 5.3 Structurally safe at any width — it is a sibling `<span>` in the existing flex
      column, so it stacks below the body and cannot displace the dismiss control, and the
      string is short enough to wrap gracefully. **Not visually confirmed on a device**;
      folded into 8.5
- [x] 5.4 Undo toast and `useOptimisticList` untouched

## 6. Tests

- [x] 6.1 Every kind is sent `Urgency: high` — parametrised over five kinds, asserting the
      header the transport actually received
- [x] 6.2 Quiet hours still suppress, and urgency does not defeat them; window derived from
      the current hour
- [x] 6.3 `TTL` equals the producing job's `catch_up`; `catch_up=None` gives `MAX_TTL_S`; no
      job gives the default
- [x] 6.4 **The production regression, end to end** — raised, deleted, rescheduled, silent,
      overdue again, raised again with a different tag. Two independent fixes must hold for it
      to pass
- [x] 6.5 Still overdue → same record, `push_count` incremented, `created_at` unchanged, one
      row not four
- [x] 6.6 Removing the record produces a fresh one on the next check
- [x] 6.7 Completed / dropped / deleted / snoozed already parametrised; due-time-moved-out
      added as its own test
- [x] 6.8 `pushed_today` counts deliveries, not records
- [x] 6.9 A deliberately-set ceiling counts repeat deliveries against itself
- [x] 6.10 `todays_record` — finds it, ignores a different tag, ignores a removed record,
      ignores yesterday's
- [x] 6.11 `disk_watch` and `budget_watch` band-crossing tests pass untouched
- [x] 6.12 **Not in the plan:** the runner path for `remind` — a job handing back a record
      causes re-delivery through `run_job`, with one row and `Urgency: high`
- [x] 6.13 An hourly check does not become an hourly buzz: held between reminders, delivered
      once the interval passes
- [x] 6.14 A record that never reached a device is always due for a reminder — at both the
      service and the job level
- [x] 6.15 Renaming an overdue task changes the reminder's wording, against the same record,
      without moving `created_at`
- [x] 6.16 The last check falls before `day_end_summary`, asserted from both jobs' real
      triggers

## 7. Documentation

- [x] 7.1 `ARCHITECTURE.md` — sequence diagram (`remind` branch, urgency and TTL on the
      delivery arrow), notification-journey diagram (said-already-today branch), the prose
      under it, the `notifications` ERD, and the services file table
- [x] 7.2 Learn page — cron example, the "deleting the record does not unsay it" card (its
      worked example was the overdue nudge, which now behaves the opposite way), the
      `notifications` store card, and the "should it interrupt?" policy card
- [x] 7.2a **Added:** a new concept card, *"Why a notification can arrive late"*, carrying the
      21:03:12 → 21:40 measurement. Nothing on the Learn page explained the single most
      user-visible thing in this change
- [x] 7.3 `AGENTS.md` checked — no stale claim; `JOBS.md`, `NOTIFICATIONS.md` and
      `REQUEST-ANATOMY.md` corrected instead
- [x] 7.4 `NOTIFICATIONS.md` §4 gained the urgency finding and the `catch_up` → `TTL` table;
      `JOBS.md` gained "A situation you have to act on" and records why the old
      changing-set reasoning was wrong

## 8. Verify

- [x] 8.1 `uv run ruff format .` and `uv run ruff check .` — clean
- [x] 8.2 `uv run pytest` — **575 passed**, from a 546 baseline
- [x] 8.3 `npm run build` — clean
- [x] 8.4 Both dev servers restarted from the new code. ⚠ Killing uvicorn's parent left the
      `--reload` CHILD holding port 8000, so the port stayed occupied after the parent was
      gone and a naive restart would have kept serving the old code — the exact failure mode
      the "stale dev servers" note warns about, in a form that hides from `Get-Process`.
      Backend on `127.0.0.1:8000`; vite binds IPv6 only, so it answers on `localhost:5173`
      and NOT on `127.0.0.1:5173`
- [x] 8.5 Tested by Narendra on the live app. Manually: task due one minute ago → nudge arrives; next check re-delivers against
      the same record and the panel says "Reminded 2 times"; move the due date out → it stops.
      Check the row at ~360px while there
- [x] 8.6 `openspec validate reliable-urgent-notifications --strict`

## 9. Production

- [x] 9.1 `.env` confirmed unstaged before both commits
- [x] 9.2 Deployed. ⚠ The FIRST push did not deploy at all: `deploy` has `needs: backend`,
      and five memory tests failed — in code this change never touched, and they passed on
      the re-run with identical backend code. Recorded as a flake worth its own
      investigation in `docs/ROADMAP.md`. Live and verified via the public
      `/openapi.json`, which now serves `push_count` and `push_ttl_default_s`
- [x] 9.3 Confirmed on the phone by Narendra
- [ ] 9.4 After a day, check `push_count` against the hours the task was overdue, and record
      whether `Urgency: normal` had also been deferred — the open question in `design.md`

## 10. Limitations reviewed

Three were found by walking the behaviour rather than the code, and all three are now fixed —
see 4.6, 4.7 and 4.8. Two remain, both deliberately:

- [ ] 10.1 ⚠ **A warning raised during quiet hours can go a full day without buzzing.**
      Pre-existing, and outside this change. `disk_watch` runs at 00:00, 06:00, 12:00 and
      18:00; the first two fall inside quiet hours, so the notification is recorded and not
      delivered — correct. But at 12:00 `already_said` finds it within its 24-hour window and
      stays quiet, so it is never pushed at all. The row is in the panel; the phone never
      rings.

      The general fix is *"deliver what quiet hours held, once quiet hours end"*, which is a
      feature in its own right and not something to bolt onto this change. **Worth doing
      soon: production disk is at 77% against an 80% threshold.** Recorded in
      `docs/ROADMAP.md`

- [x] 10.2 **Whether the phone actually rang is unknowable from the server.** Web push has no
      delivery receipt, so `push_count` means "handed to the push service", not "the device
      buzzed". Not fixable — it is how the protocol works. The remaining device-side variable
      is Android's app-standby bucket, which throttles rarely-opened apps regardless of
      urgency; setting the browser to Unrestricted is the user's half of this
