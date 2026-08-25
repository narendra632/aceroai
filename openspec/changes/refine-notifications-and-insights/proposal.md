# What Acero said, what it runs on, and a strip of wasted space

## Why

The jobs-and-push change shipped and works. Using it for a day surfaced four things, and the
uncomfortable part is that **three of them are defects rather than missing features** — two
of them break requirements this project had already written down and archived.

**1. The notification panel lies while it loads.** `NotificationBell.tsx` holds its rows in
`useState<NotificationRow[]>([])` with no status of any kind, and `NotificationList` renders
the "Nothing yet." empty state whenever the array is empty. So opening the bell states
confidently that there are no notifications, then contradicts itself a moment later. The same
line swallows failures — `.catch(() => {})` — which means a dead backend and an empty inbox
are rendered **identically**. The `ui-standards` capability already forbids exactly this, in
two scenarios that have been archived since the UI-polish change: *"an error is never rendered
as an empty result, which would misreport a fault as 'you have nothing'"* and *"the wait is
shown, rather than an empty screen that later changes without warning"*. The bell was written
by hand, after those requirements, and never picked them up.

**2. Nothing Acero says can ever be removed.** Notifications and generated briefings are the
only user-facing records in the application with no delete. Every other one — tasks, journal
entries, conversations, facts — is soft-deleted with an undo toast, and `ui-standards` states
the rule as a requirement. Notifications were simply left out. They are bounded (pruned at
`notification_retention_days`, 90) so this is not a growth problem; it is that three identical
"Acero is set up" rows from testing push will sit in the panel until November with no way to
be rid of them.

**3. There is no way to see whether the machine is healthy.** Acero runs on a 1 GB / 10 GB
e2-micro **with no database backup** — a deliberate, priced decision. The numbers that decide
whether that gamble is still safe (disk headroom, memory pressure, how fast the database is
growing) are visible only over SSH. Worse, there is one failure mode the application is
uniquely blind to: **if the scheduler stops ticking, nothing anywhere reports it.** Jobs just
silently stop happening, and the first evidence is a morning brief that never arrives.

**4. A full-width strip of the desktop interface holds one icon.** The shell renders a
bordered row across the entire window whose only content is the notification bell, pushed to
the far right. Everything between the sidebar and that bell is empty, on every page. Below it,
`InsightsView` and `KnowledgeView` each draw a *second* bordered header for their own title.

## What Changes

### A. Notifications and briefings become removable, the same way everything else is

Soft delete plus an undo toast — `deleted_at`, `toast.undo()`, `useOptimisticList`, exactly
the idiom `TasksView.remove` established and `ui-standards` requires. A per-row dismiss for the
one you want gone, and **"Clear read"** in the panel header for the common case, because a
notification list is a log and the real motion is "get rid of what I have dealt with" rather
than curating entries one at a time.

One invariant is easy to get wrong, and investigating it turned out to matter more than
expected: **removing the record of something Acero said does not make it unsaid.**

Two pieces of code ask the `notifications` table about the past, and neither may be taught to
ignore deleted rows:

- `_already_said()` decides whether a nudge is news or repetition, by looking for a row with
  the same tag. Filter deleted rows out of it and **deleting the "3 tasks are overdue"
  notification makes the next hourly nudge push it again** — delete would silently become
  "remind me within the hour", on the notification the user most wants recurring.
- `_pushed_today()` counts what was delivered. It is the honest answer to "how many times has
  this buzzed today", and clearing the panel must not reset it to zero.

Everywhere else, adding soft delete means hiding deleted rows from every query. These two are
the exceptions, and both are pinned by tests so the "inconsistency" is not later tidied away.

Briefings get the same treatment, and deleting one does **not** cause it to be regenerated —
`job_runs` decides what has run, not `generated_reviews`. That falls out of the exactly-once
design rather than being something this change has to build.

### B. The panel tells the truth about what it is doing

Three states, and a detail that matters more than the states: the skeleton appears **only when
there is nothing cached**. Re-opening the panel keeps the rows it already has and refreshes
underneath them, so the flash is *removed* rather than replaced by a spinner.

### C. Live vital signs on Insights

A new authenticated `GET /api/insights/vitals` reporting disk, memory, database size, load
average, process uptime, and **when the scheduler last ticked** — the one that no other part
of the system would ever tell you about. Polled every 10 seconds while the page is open,
**paused whenever the tab is hidden**, so a forgotten background tab does not poll a 1 GB VM
all day for a page nobody is looking at.

Deliberately **not** on `/health`, which is public — Caddy and uptime probes hit it — and must
never disclose disk figures or host detail.

**No new dependency.** `psutil` is the obvious reach and is not needed: `shutil.disk_usage`,
`/proc/meminfo` and `/proc/loadavg` cover it from the standard library.

⚠ `/proc` does not exist on Windows, so **memory and load will be absent on the development
machine** and present only on the VM. The interface omits what it cannot measure rather than
rendering zeros, and this is documented prominently so it does not read as a bug locally.

### D. The daily push ceiling is removed, and the count is kept

`daily_push_cap` defaults to **6**, while `task_nudge` alone can fire thirteen times a day.
The ceiling has therefore been silently swallowing notifications the user wanted — the hourly
overdue-task ping is explicitly wanted, and is exactly what a cap of six suppresses first.

The default becomes **0, which already means unlimited** (`_cap` is consulted as
`if cap and ...`, so zero is falsy and suppresses nothing). No migration, no enforcement, no
ceiling in practice.

The mechanism is *retained rather than deleted*, because its real function was never to shape
normal use — it was a fire extinguisher for a job that loops or a tag that stops matching. A
number that is zero costs nothing and can be set from Settings if that day ever comes.

What was a cap control in Settings becomes a plain readout of how many pushes were sent today,
with no ceiling attached — the count was always the more informative half.

### E. A disk watch, because the number alone asks to be remembered

Disk is the reading on this box that can actually stop it working: Postgres refuses writes on
a full disk, there is no backup, and the failure arrives without warning. A number on a page
only helps the day you think to look at it.

`disk_watch` runs four times a day, uses no model, and is silent below a threshold. It reuses
the reader the vitals endpoint uses, and the repetition-suppression `task_nudge` already
established — tagged by **5% band**, so crossing 80% tells you once, 81–84% stays quiet, and
crossing 85% is new information.

Reusing that required fixing a limitation in it: `_already_said()` has no time bound, which is
correct for a tag that is a hash of a changing set and wrong for one that can recur. It gains
an optional window, and disk uses 24 hours — told once on crossing, reminded daily while above.

### F. The wasted strip becomes the page header

The shell's top bar takes the page title and subtitle beside the bell, and the views stop
drawing their own. On Insights, the vitals sit above the cost tiles as their own bordered
block, with the 7d/30d/90d/All range control on that row's right-hand side.

The border is load-bearing, not decoration: the vitals are **"right now"** while everything
below them is scoped to the selected range. Placing them outside the range-scoped block and
enclosing them is what stops the range control from appearing to apply to them.

### G. The documentation audit the last change was supposed to have done

Requested explicitly, and it found real rot. The Learn page still teaches that the daily
rollup *"[r]uns once a day, on the first call of the day — no scheduler needed yet"* — on the
same page that now has an entire section explaining the scheduler. Settings still tells the
user their model choice *"applies everywhere — web and Telegram"*, three days after Telegram
was retired. `retention.py`'s own docstring still says the rollup fires opportunistically.

This is the failure mode the `learnings` capability was built to prevent, and it turns out its
requirement only covers **planned work presented as built**. The inverse — *built* work still
described as planned, or a superseded implementation still taught as current — was not
covered. That requirement is widened here.

## Impact

- **Schema:** migration `012` adds `deleted_at` to `notifications` and `generated_reviews`.
- **Backend:** `api/insights.py`, `services/insights.py`, `services/notifications.py`,
  `services/journal.py`, `api/notifications.py`, `api/journal.py`, `services/retention.py`.
- **Frontend:** `AppShell`, `NotificationBell`, `InsightsView`, `JournalView`, `KnowledgeView`,
  `SettingsView`, `lib/api.ts`, one new vitals component.
- **Docs:** `ARCHITECTURE.md`, `NOTIFICATIONS.md`, `JOBS.md`, `REQUEST-ANATOMY.md`, the ER
  diagram, `learn/content.ts`, and `openspec/config.yaml` — whose project context still
  describes Telegram as a live channel.
- **No new dependencies.**

## Non-goals (this change)

- **Any notification ceiling.** Quiet hours remain; the daily count becomes a readout rather
  than a limit. Notification volume is now governed entirely by per-tag repetition
  suppression, which is where it belongs — the question is whether something is *news*, not
  how many times it has been said.
- **Alerting on anything except disk.** Memory, load and database size are shown and not
  watched. Disk earns a job because it is the reading that can stop the system working, and
  because its failure gives no warning; the others are diagnostic rather than fatal.
- **History or charting of vital signs.** These are instantaneous readings. There is no
  time series, no retention, and nothing stored — which is also why they cost nothing.
- **The database backup.** Its own trigger — the Investments page — has not fired yet. The
  disk reading this change adds is an input to that decision, not the decision.
- **Hard-deleting notifications on a shorter clock than the 90-day prune.** A soft-deleted row
  rides the existing cutoff. A second retention knob for a table that gains a handful of rows
  a day would be a config option and a test bought for nothing.
- **Pagination or search in the notification panel.** The list is capped at 50 and pruned at
  90 days; neither is close to binding.
- **Vital signs anywhere except Insights.** The disk watch reads the same numbers, but it
  reports by notification rather than by putting them on a second screen.
- **Restoring a notification or briefing from anywhere except the undo toast.** There is no
  trash view; the undo window is the whole recovery story, exactly as it is for tasks.
