# Design

## Decision 1 — Soft delete, not hard delete

`notifications` and `generated_reviews` gain `deleted_at TIMESTAMPTZ NULL`, matching
`tasks`, `journal_entries`, `chat_sessions` and `profile_facts`.

**Considered and rejected: hard delete.** It is the honest reading of "delete" and it needs no
migration. It was rejected because it makes undo impossible, and `ui-standards` already
requires that *"[d]estroying user data SHALL be recoverable for a short period"*. Choosing hard
delete would mean either violating an archived requirement or shipping a confirmation dialog
instead — and `TasksView` has already recorded why that trade goes the other way: *"Undo rather
than a confirm dialog: no friction on the intentional case, and it still protects the mistake
you only notice a second later."*

**Considered and rejected: a `dismissed_at` column distinct from deletion**, so "clear from my
panel" and "destroy" could differ. Rejected as a distinction without a user. There is one user,
one panel, and no second reader of these rows; two columns would mean two filters to get right
in every query for a behaviour nobody asked for.

## Decision 2 — Removing the record of something said does not make it unsaid

Adding soft delete means one thing everywhere else: hide deleted rows from every query. There
are **exactly two exceptions**, both of which read `notifications` as a record of *the past*
rather than as a list to display. Neither may be taught to filter deleted rows.

**`_already_said(kind, tag)`** decides whether a nudge is news or repetition. `task_nudge`
tags each notification with a fingerprint of the situation — which tasks are overdue right now
— and stays silent when the tag already exists.

Teach it to ignore deleted rows and delete acquires a second, invisible meaning: dismissing
the "3 tasks are overdue" notification erases the evidence that it was said, so the next hourly
run finds nothing, concludes the situation is new, and pushes it again. **Delete would become
"tell me again within the hour"** — on precisely the notification the user has said they want
recurring. Nothing would look broken; the app would just be mysteriously insistent.

**`_pushed_today()`** counts what was delivered today. With the ceiling removed (Decision 10)
it is now a readout rather than a gate, but the same reasoning holds and matters for a
different reason: it answers "how many times has this buzzed me today", and clearing the panel
must not reset that to zero. A count of deliveries is a count of *deliveries*, not of
surviving receipts.

The unifying rule, written into the spec so it survives someone later tidying the
inconsistency: **every reader that lists notifications filters deleted rows; every reader that
asks what already happened does not.** Both are pinned by tests.

**Considered and rejected: a separate `notification_events` table** recording deliveries and
utterances independently of the display rows, so the display table could be filtered freely.
That is the textbook-correct separation — an event log distinct from a view. Rejected as
disproportionate: it doubles the writes on the push path and introduces a second table to
prune, to buy a purity that two comments and two tests already deliver.

## Decision 3 — Deleting a briefing does not regenerate it

Worth recording because it is the kind of thing that looks like a bug the first time it is
noticed, and because it is a property rather than code.

`job_runs` is the source of truth for what has run, keyed on `(job_name, occurrence_key)`.
`generated_reviews` is *output*. Deleting the output leaves the run record untouched, so the
job does not re-fire, and the next occurrence is tomorrow's. Deleting last Tuesday's day-end
summary removes it permanently after the undo window — which is what "delete" should mean.

Had briefings been the source of truth, this change would have introduced a loop where deleting
a briefing caused Acero to spend money writing it again.

## Decision 4 — Vitals are a new authenticated endpoint, not an extension of `/health`

`/health` is unauthenticated. Caddy's proxy checks it, and it is the endpoint used to prove the
backend is alive from outside the network — that was how the CORS-shaped 502 was diagnosed
during the last deploy. It must keep returning `{"status": "ok"}` and nothing else.

Disk figures, memory totals and database size are infrastructure detail. On a single-user app
the practical risk is low, but "the health endpoint grew a few useful fields" is precisely how
an unauthenticated endpoint becomes a reconnaissance surface. `GET /api/insights/vitals` sits
behind `get_current_user` with the rest of the insights router, and returns
`Cache-Control: no-store`.

**Considered and rejected: putting the vitals in the existing `/api/insights/overview`
response.** It would save a request. Rejected because `overview` is scoped to the selected date
range and is cached per range; vitals are instantaneous and polled. Merging them would make the
poll re-fetch the whole 90-day aggregate every 10 seconds, or force the aggregate to be
recomputed on a clock it has no reason to follow.

## Decision 5 — `/proc` and `shutil`, not `psutil`

`psutil` is the standard answer and would work. Rejected because everything needed is two files
and one syscall:

| Reading | Source |
|---|---|
| Disk used / total | `shutil.disk_usage("/")` — one `statvfs` |
| Memory total / available | `/proc/meminfo`, `MemTotal` and `MemAvailable` |
| 1-minute load | `/proc/loadavg`, first field |
| Database size | `SELECT pg_database_size(current_database())` |
| Last scheduler tick | the scheduler's own in-process heartbeat — **not** `job_runs`, see Decision 12 |
| Uptime | process start time recorded at import |

`MemAvailable` rather than `MemFree` deliberately: `MemFree` on a Linux box running Postgres
looks alarming and means nothing, because the page cache is doing its job. `MemAvailable` is
the kernel's own estimate of what a new process could actually get, which is the question
being asked.

**Platform behaviour, and why it is not a bug.** `/proc` is Linux-only. On the Windows
development machine, memory and load resolve to `None` and the interface omits those tiles
entirely rather than rendering `0`. Reading zero pressure would be worse than reading nothing:
it is a wrong answer presented with the same confidence as a right one.

**In the container**, `/proc/meminfo` reports the host's memory because
`docker-compose.prod.yml` sets no memory limit on `api`, and `shutil.disk_usage("/")` reports
the host disk through the overlay filesystem. Both are the numbers wanted — but both are
assumptions about the runtime rather than facts about the code, so section 0 verifies them on
the VM before the interface is built to display them.

## Decision 6 — 10-second polling, paused when hidden

**Considered and rejected: 5 seconds.** Nothing measured here moves meaningfully inside five
seconds — a 10 GB disk, a database growing a few MB a day, a load average that is itself a
60-second mean. It would double the request rate for no additional information, on the machine
being measured.

**Considered and rejected: server-sent events.** A stream would remove the polling entirely and
this codebase already has SSE. Rejected as the wrong shape: SSE is for a server that has
something to say. Here the server has nothing to volunteer — the client wants a snapshot on a
clock — and a long-lived connection per open tab is a worse trade than a 10-second GET.

The poll **stops when `document.visibilityState` is `hidden`** and resumes on return, taking an
immediate reading so the first thing seen is never stale. This is not an optimisation: a tab
left open in a background window would otherwise poll the VM roughly 8,600 times a day to
render a page nobody is looking at.

## Decision 7 — The shell owns the page header

Currently the desktop shell renders a bordered strip whose only child is the notification bell
in a `justify-end` flex, and its comment admits it: *"this strip exists only to give the bell
somewhere to live."* Beneath it, `InsightsView` and `KnowledgeView` each render their own
bordered `<header>`, `SettingsView` renders a `md:block` `<h1>`, and `LearnView` has an
in-content header of its own — four different treatments of the same idea.

The invariant introduced: **on desktop, the shell owns the page title and subtitle; a view owns
its content and its own controls.** `TITLES[view]` already exists for the mobile header and is
extended with a subtitle. Views stop drawing their own titles, which both removes the
duplication and reclaims a full row of vertical space on every page.

**Considered and rejected: a slot the shell renders and each view fills** (a portal, or a
context the view writes into). More flexible, and it would let a view contribute arbitrary
header content. Rejected as more machinery than the problem justifies: a static per-view title
and subtitle is a lookup table, and the one view that needs a header-adjacent control — the
Insights range picker — is being moved into the content anyway, next to the vitals.

**Considered and rejected: leaving the strip and putting the vitals in it.** That was the
first instinct and it is wrong twice over: it would put infrastructure readings above the page
title on every screen including Chat, and it would leave `InsightsView`'s duplicate header in
place.

## Decision 8 — The vitals block is bordered because of what the border means

The vitals are instantaneous. Everything else on Insights is scoped to 7d / 30d / 90d / All.
Rendering five tiles that look exactly like the four cost tiles, immediately above them,
invites the reading that "Disk" is also a 30-day figure.

So the block is enclosed, labelled, and carries a live indicator, and the range control sits on
its row *outside* that enclosure — visually belonging to the content below, which is what it
actually governs. This is the one piece of chrome in the change that is doing semantic work
rather than decoration, and it is why "just add five more tiles to the existing grid" was
rejected.

Thresholds colour the disk and memory bars, and **the strip is otherwise quiet**. A vital-signs
display that draws attention while everything is fine trains you to ignore it, which costs you
the one moment it exists for.

## Decision 9 — Widen the `learnings` requirement rather than only fixing the text

The Learn page currently teaches that the daily rollup runs *"on the first call of the day — no
scheduler needed yet"*, on a page that also explains the scheduler at length. The existing
requirement — *"Planned work is never presented as built"* — does not catch this, because this
is the **inverse**: built work still described as planned.

Fixing the sentence and leaving the requirement alone would guarantee a recurrence: the next
change that supersedes an implementation will leave the old explanation standing, and nothing
will have been learned. The requirement is widened to cover a superseded description, in both
directions.

**Considered and rejected: a test asserting the Learn content matches the code.** Tempting, and
`test_docs_diagrams.py` shows the appetite for structural checks. Rejected because the claim in
question is prose about *why* something happens; no assertion short of a language model can
tell that "no scheduler needed yet" has become false. `test_docs_diagrams.py` is explicit about
this boundary — it checks structure and *"make[s] no claim about whether a diagram describes
the code correctly; only a reader can judge that."* The honest mechanism here is the
end-of-task-list check, and widening what it is checked against.

## Decision 10 — The daily ceiling goes; the mechanism stays at zero

`daily_push_cap` defaults to 6. `task_nudge` is scheduled `0 9-21 * * *` — thirteen possible
firings — and the morning brief, day-end summary, budget watch and journal nudge sit on top of
that. The ceiling has been binding in ordinary use, which means it has been silently
discarding notifications the user wanted, and the first thing it discards each day is the
hourly overdue-task ping that is the most wanted of all.

A cap that is reached during normal operation is not a safety limit; it is an undocumented
feature that deletes your notifications after lunch.

The default becomes `0`. No code change is needed to make that mean "unlimited" — `_cap` is
consulted as `if cap and _pushed_today(...) >= cap`, so zero is falsy and suppresses nothing.

**Considered and rejected: deleting the mechanism outright.** It is the honest reading of
"remove the limit", and it would delete a column, a setting and a branch. Rejected because the
cap's real function was never to shape normal volume — it was the bound on *runaway* volume: a
job that loops, a tag that stops matching, a nudge whose fingerprint changes every run. Per-tag
suppression is the right control for expected volume and is no defence at all against a bug in
the thing computing the tags. A setting that is zero costs one falsy check and is the
difference between a bad hour and a bad hour with no way to stop it.

**Considered and rejected: raising the default to 50.** Splits the difference and keeps a
backstop armed by default. Rejected because a number chosen to be unreachable is a number
nobody can justify, and the first time it is reached it will be during exactly the incident
where nobody remembers it exists. Zero states the policy — there is no ceiling — and leaves
the extinguisher on the wall.

## Decision 11 — `disk_watch`, and the time bound `_already_said` was missing

Disk is the only reading here that can stop the system: Postgres refuses writes on a full
disk, there is no backup, and nothing warns first. Memory and load degrade visibly and
recover; disk does not.

The job is deliberately unremarkable — four times a day, no model, silent below the threshold,
and reading through the **same function the vitals endpoint uses**, so there is one definition
of "how full is the disk" rather than two that can drift.

**Repetition is the whole design problem.** A condition that persists for a week must not
produce twenty-eight notifications. `task_nudge` solved this already with a tag that encodes
the situation, so the job reuses it: the tag is the **5% band** the reading falls into.
Crossing 80% says so once; 81–84% is the same band and stays quiet; crossing 85% is genuinely
new and says so again. Bands rather than exact percentages because a disk oscillating across
a single number would otherwise chatter.

Reusing `_already_said` exposed a real limitation in it. It has **no time bound** — it asks
whether this tag has *ever* been raised. That is correct for `task_nudge`, whose tag is a hash
of a set that genuinely changes, and wrong for any tag that can recur. Left alone, clearing
space to 75% and drifting back to 80% next month would find the old row and stay silent
forever: the alert would fire once in the lifetime of the installation.

So `_already_said` gains an optional window, and `disk_watch` passes 24 hours: **told once on
crossing a band, reminded daily while still above it.** `task_nudge` passes nothing and keeps
its current behaviour exactly.

**Considered and rejected: alerting on memory and load too.** Both are visible on Insights and
neither is fatal — memory pressure resolves itself through the page cache and load is a
symptom rather than a cause. Watching everything measurable is how a notification channel
becomes noise, and the value of the disk alert depends entirely on it being rare.

**Considered and rejected: making the threshold a per-user preference.** It is one number on
one machine. `settings.disk_warn_percent` is the right home; a UI control for it would be
configuration theatre.

## Decision 12 — The scheduler heartbeat is in memory, not in `job_runs`

Found in section 0, while timing the query that was going to provide this reading. The
original plan — "newest row in `job_runs`" — is wrong, and wrong in the direction that makes a
monitoring signal actively harmful.

**`job_runs` gets a row only when an occurrence fires.** Most ticks write nothing: every job
has either already run for its occurrence or has no occurrence due. The jobs are clustered in
waking hours, so between `task_nudge` at 21:00 and `retention_sweep` at 03:15 there are **six
hours during which a perfectly healthy scheduler writes nothing at all**.

"Newest job run" would therefore report the scheduler as six hours stale every night. A signal
that cries wolf nightly is a signal nobody reads on the morning it is finally right — which
would leave the system *worse* off than having no reading, because the reading would exist and
be ignored.

So `tick_once()` records its own completion time in a module global, and `vitals.last_tick()`
reads that. This costs nothing, removes a database query from the polled path entirely, and
targets the failure precisely: **the APScheduler thread dying while uvicorn keeps serving
requests**, which produces no error, no failed request and no log line anywhere.

The timestamp is set in a `finally`, deliberately. It records that the *ticker* is alive,
which is a different claim from "the work succeeded" — a tick that raises on every pass still
proves the timer is running, and what failed is already recorded against the job in
`job_runs`. Conflating them would make one broken job look like a dead scheduler.

**Considered and rejected: a `scheduler_state` heartbeat row updated each tick.** It survives
restarts and would work with multiple processes. Rejected on cost and on meaning: it is a write
every five minutes — roughly 105,000 a year whose entire purpose is to be overwritten — and the
restart-survival it buys is not wanted. `None` after a restart is *correct information*: this
process has not ticked yet. It becomes true again within one interval, and `uptime` reported
beside it is what distinguishes "just booted" from "the ticker has stopped".

**Considered and rejected: adding an index on `job_runs(started_at DESC)`.** This was the
first instinct when the query looked slow, and it would have optimised a query that should not
exist. Measured: 0.04 ms on a sequential scan, and the existing `job_runs_recent` index leads
with `job_name` so it could not serve a global ordering anyway. The reading was not slow — it
was measuring the wrong thing.

**Valid because the API runs as a single uvicorn process** — no `--workers` in the Dockerfile
`CMD`. That is not a new assumption: the entire job design already depends on it, since two
worker processes would mean two schedulers.
