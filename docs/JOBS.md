# JOBS.md — how Acero does things without being asked

> Plain language first, code second. The *why* behind the architecture is in
> [`ARCHITECTURE.md`](ARCHITECTURE.md); notifications have their own file,
> [`NOTIFICATIONS.md`](NOTIFICATIONS.md).

Until now Acero only ever spoke when spoken to. Everything it knew about your day sat in
Postgres waiting for you to think to ask. This is the machinery that changed that.

---

## 1. The one idea worth understanding

**The scheduler does not decide what has run. The database does.**

That sounds like a technicality and it is the whole design. Here is the failure it prevents.

Suppose the day-end summary is scheduled for 21:00. At 20:58 you push a commit; CI builds,
deploys, and restarts the container. A normal scheduler keeps its state in memory, so the
restart wipes it. 21:00 arrives and passes. No summary. **No error, either** — nothing
failed, the moment simply went by while nobody was watching.

You would not find out for weeks, and when you did there would be nothing to look at.

So instead:

```
Every job resolves to an "occurrence" — a specific scheduled moment:

    day_end_summary @ 2026-08-24T21:00:00+05:30

That pair (job, occurrence) is UNIQUE in the job_runs table.

A tick asks:  what is the most recent occurrence, and is it already in the table?
              no  -> run it
              yes -> do nothing
```

Three things fall out of that, for free:

- **A missed run heals itself.** The tick runs every five minutes, so a run lost to a deploy
  happens a few minutes later instead of never.
- **Running twice is impossible.** Not "unlikely" — the second attempt violates a database
  constraint. A repeated tick, a second process and a hand-run command all converge on one
  execution.
- **You can re-run anything by hand** and it behaves identically, because there is only one
  path through the code.

---

## 2. The catch-up window is a *policy*, not a limit

Each job says how late it may still run.

| Job | Runs at | May still run until | Why |
|---|---|---|---|
| `morning_brief` | 07:30 | 11:30 | A "morning brief" at 4pm is not late, it is wrong |
| `day_end_summary` | 21:00 | midnight | So it still lands on the day it describes |
| `task_nudge` | hourly, 09–19 | +45 min | The next check beats a stale one |
| `budget_watch` | 09:00 | 21:00 | A spend warning is useful all day |
| `journal_nudge` | 20:30 | 22:30 | "Write about today", delivered tomorrow, is noise |
| `retention_sweep` | 03:15 | **however late** | Sweeping late beats not sweeping |
| `disk_watch` | every 6 h | +2 h | A full disk stops Postgres accepting writes |
| `db_backup` | 02:30 | +6 h | A night skipped in silence is a night with no copy |
| `restore_check` | 1st, 04:00 | +12 h | Monthly; a day late proves the same thing |
| `backup_watch` | 10:00 | +6 h | It reports a silence, so it must not join one |
| `prices_daily` | 07:30 | +12 h | Fills every missing close; late is as good as on time |
| `prices_india_close` | 19:00 weekdays | +12 h | NSE's file is out by ~18:30; tomorrow's run also catches up |
| `corporate_actions_watch` | 20:00 weekdays | +12 h | Actions are announced days before their ex-date |
| `investments_disk_watch` | 09:00 Mondays | +12 h | A 50 MB/year budget does not need a daily reading |
| `sources_poll` | 08:10, 12:10, 16:10, 20:10, 23:10 | +2 h | The feed is a window that empties; a gap cannot be re-asked |
| `universe_sync` | 06:30 Sundays | +2 days | The exchange list changes by a handful a month; stale costs a missed match, not a wrong one |
| `candidate_analysis` | 20:30 | +2 h | Half an hour before the evening run, so the day's new names are placed before proposals form |
| `investments_weekly_review` | 09:00 Saturdays | +12 h | No market is open, nothing is urgent, the week is complete |
| `investments_monthly_review` | 09:30 on the 1st | +12 h | After the weekly has had its Saturday |
| `investments_quarterly_review` | 10:30, 1 Jan/Apr/Jul/Oct | +12 h | An hour after the monthly, so both exist and neither races |

⚠ **Sunday is deliberately empty of reviews.** There is a real risk in a system like this
that it fills every available slot with output, and output is not insight. `universe_sync`
runs on a Sunday because it is bookkeeping nobody reads; nothing that asks for attention does.

⚠ **Why `sources_poll` closes the day at 23:10.** NSE's announcement feed is not a history,
it is a *window that empties*: it held 56 items at 23:40 on 20 Sep 2026 and 0 the next
morning. Anything filed after the last poll and before that reset is gone for good, because a
feed with no history cannot be asked again. Companies do file late — the 21:41 and 23:41 items
that Saturday were both real disclosures — so the day ends with a poll after them rather than
before, and the catch-up window is 2 h because the shortest gap between runs is 3 h.

⚠ **A trap, found by measurement.** The window must be *shorter than the gap between runs*.
A daily job with a 24-hour window can never be missed — its occurrences are 24 hours apart,
so there is always one inside the window. The window then reads like a staleness policy
while actually meaning "deliver however late", and a 07:30 brief would still go out at 07:29
the next morning.

That was the original default here. It is now **a startup failure**: the registry computes
the real gap between occurrences and refuses a window that cannot expire. "However late" has
to be spelled `catch_up=None`, out loud.

A run that misses its window is recorded as `missed` rather than forgotten, so "nothing
happened" and "nothing was supposed to happen" never look the same afterwards.

---

## 3. Where the AI sits

Three levels. Most jobs are at the first one.

**Level 0 — no model at all.** `task_nudge`, `budget_watch`, `journal_nudge`,
`retention_sweep`, `disk_watch`. *"Which tasks are overdue"* is a database query, not a question for a
language model. Free, instant, and structurally incapable of inventing a task.

**Level 1 — the job owns the facts, the model owns the voice.** The two summaries:

```
1. The job gathers a brief, deterministically, in SQL:
      { done: 4, open: 7, overdue: 2, journalled: false }

2. The model receives SOUL.md + that brief + "write 3-5 sentences using only these facts"

3. The model never queries the database, never chooses what to include,
   and has no tools at all.
```

The model cannot hallucinate a completed task **because it was never given the ability to
look** — it was handed a number. That property is what makes a message written at 21:00 and
read before you are properly awake safe to send unreviewed.

**Level 2 — a job that can act: deliberately not built.** A job calling `handle_message` with
tools available would have unbounded cost, unbounded runtime, and would take *actions*. An
agent acting unsupervised at 3am is a different risk class from one answering a question you
just asked.

Two further rules, both enforced by tests:

- Every job model call is traced as `turns.kind="job"`, so job spend appears on Insights as
  its own slice beside chat, embeddings and extraction.
- **A generated summary is never fed to the memory extractor.** Learning facts from your own
  output is a feedback loop where a phrasing hardens into a belief you never stated.

---

## 4. Adding a job

One decorator, in one file under `backend/app/jobs/`, plus an import in `__init__.py`:

```python
@job(
    "weekly_review",
    "0 18 * * sun",              # named weekday, never a number — see below
    uses_ai=True,
    description="A look back across the week, on Sunday evening.",
    catch_up=dt.timedelta(hours=4),
)
def weekly_review(db: Session, user: User) -> JobResult:
    ...
    return JobResult(notify=..., review=..., detail={...})
```

Everything else comes from the registry and **cannot be forgotten**: run recording,
idempotence, failure isolation, the spending check, tracing, the toggle in Settings,
quiet hours, and the daily push cap.

Per-job preferences live in a **sparse** table — no row means "use the declared default" — so
a new job needs **no migration**.

### What a job returns

```python
JobResult(
    notify=Notification(...),   # a row to write, and maybe a push
    review=ReviewDraft(...),    # a longer briefing, kept and readable by date
    detail={...},               # counts, recorded on job_runs for debugging
    silent=True,                # ran, correctly had nothing to say
)
```

`silent` is load-bearing. `task_nudge` runs eleven times a day and usually finds nothing —
that is the job *working*. A column of `silent` in `job_runs` is healthy, a column of
`failed` is not, and an absence of rows is a third thing entirely.

### ⚠ Never write a numeric day-of-week

APScheduler counts days from **Monday = 0**. Every crontab reference on earth counts from
**Sunday = 0**. So `0 18 * * 0` — which reads unmistakably as "Sunday evening" — fires on
**Monday**.

Measured against this exact version:

```
0 18 * * 0     -> Monday      <- what you did not mean
0 18 * * sun   -> Sunday
0 18 * * 6     -> Sunday      <- and this is Saturday in crontab
```

Nothing errors. The job simply runs on the wrong day, forever. The registry therefore
**refuses a numeric day-of-week at import**, turning a silent off-by-one into a startup
failure.

---

## 5. Running one by hand

```bash
cd backend
uv run python -m app.jobs.run --list                    # what exists
uv run python -m app.jobs.run                           # one tick, exactly as the scheduler does
uv run python -m app.jobs.run day_end_summary           # that job, if it is due
uv run python -m app.jobs.run day_end_summary --force   # that job, now, regardless
```

Deliberately the same code path as the scheduler, so there is one implementation to trust
rather than a production path and a debugging path that drift apart. `--force` bypasses the
already-ran and enabled checks and **nothing else** — the lock, the timeouts, the budget
check and the recording all still apply.

There is deliberately **no HTTP route that triggers a job**. Running work on demand from a
browser turns a scheduler into a remote execution endpoint; the legitimate need is served by
the command above, which requires shell access to the machine.

---

## 6. Safety rails

| Rail | What it stops |
|---|---|
| `UNIQUE (job_name, occurrence_key)` | The same run happening twice |
| `pg_try_advisory_lock`, on a **dedicated connection** | Two processes doing the same work at once |
| `lock_timeout = 3s` | Housekeeping blocking a request you are waiting on |
| `statement_timeout = 60s` | One runaway query wedging the tick |
| Everything caught and recorded | A failing job stopping the scheduler or reaching the app |
| `budget.check()` before AI jobs | Overnight work quietly blowing the monthly cap |

A failing job's entire blast radius is one row in `job_runs` with a status of `failed` and
the exception type.

---

## 7. Retention, and why it moved

Trace retention was the only recurring work this project had, and it ran **off the back of a
delivered reply** — `telemetry.record()` called `maybe_sweep()`, gated by an in-memory date.

Three problems, all of them the trigger's fault rather than the sweep's:

1. It only ran if you talked to Acero. A quiet week pruned nothing.
2. It ran during the day, taking DELETE locks on `turns` and `spans` while you were using the
   app. The 3-second `lock_timeout` meant it correctly gave up — so the work often just did
   not happen.
3. The state was memory-only, so every deploy re-armed it.

It is now a job at 03:15 with `catch_up=None`. `sweep()` itself is **unchanged** — it was
always idempotent and correct.

It gained one duty: pruning `notifications` past 90 days. A notification centre is a third
unbounded table, and adding one in the same change that bounds the other two would have been
a poor joke.

---

## 8. Backups: three jobs, because three things fail

Backups do not usually fail loudly. They fail by **stopping**, and a system that has stopped
looks exactly like a system with nothing to report. So the work is split three ways, and each
part answers a question the others cannot:

| Job | Question it answers | When |
|---|---|---|
| `db_backup` | Does a copy exist? | 02:30 nightly |
| `restore_check` | Is the copy usable? | 04:00 on the 1st |
| `backup_watch` | Has either stopped happening? | 10:00 daily |

**`backup_watch` must stay a separate job.** A job that does not run cannot report that it
did not run. Folding the staleness check into `db_backup` produces monitoring that works only
while the thing it monitors is healthy — which is the shape of backup monitoring that looks
fine for a year and then turns out to be decorative. It also runs at a different hour, so
whatever stops one is less likely to stop both unnoticed.

**A copy carries a manifest.** Beside every dump sits a small JSON file recording its
SHA-256 and the row count of every table *at the moment it was taken*. Without it, a restore
proves only that some file restored — and a truncated dump often restores with no error at
all, leaving a database quietly smaller than it should be. `restore_check` compares against
the manifest, never against the live database, which has moved on since.

**Failures are reported by the job, not by the runner.** An unhandled exception is recorded
as `failed` and notifies nobody — that is the isolation guarantee, and it is right for most
work. A backup is the exception, so these jobs catch what they can name and hand back a
notification. The runner then records `ok`, because the job did its job: make a copy *or say
why it could not*. That is why `services.backups.last_successful_at` identifies a real
success by the `object` key in `detail` and never by the status — otherwise a night of
correctly-reported failures would read as a night of backups.

**Nothing here ever deletes a backup.** Old copies expire through lifecycle rules on the
bucket (14 daily / 8 weekly / 12 monthly). Code that deletes backups is code that can delete
the wrong backup, on the one asset with no second copy, on a path exercised once a night in
production only.

The accepted cost, stated rather than buried: a full copy nightly means **up to 24 hours of
work can be lost**. Point-in-time recovery would reduce that to seconds and costs an unbroken
chain of fragments whose breakage is silent until a restore is attempted — the exact failure
this design exists to remove. The trigger to revisit is real money in the Investments ledger.

---

## 9. Where the code is

```
backend/app/jobs/
  registry.py      what a job IS, the @job decorator, and the validation
  runner.py        what is DUE, and running it exactly once
  scheduler.py     the ticker — APScheduler holds exactly one job
  run.py           python -m app.jobs.run
  housekeeping.py  retention_sweep, disk_watch, investments_disk_watch
  reading.py       sources_poll, universe_sync, candidate_analysis
  reviews.py       investments_weekly_review, investments_monthly_review, investments_quarterly_review
  brief.py         morning_brief, day_end_summary   (the only jobs that call a model)
  nudges.py        task_nudge, budget_watch, journal_nudge
  backups.py       db_backup, restore_check, backup_watch

backend/app/services/job_prefs.py    on/off, and how the schedule is phrased for a person
backend/app/api/jobs.py              list and toggle
```

Tests: `backend/tests/test_jobs.py` (the machinery), `test_job_content.py` (what the shipped
jobs actually decide) and `test_backups.py` (the three backup jobs).

---

## Saying something once: tags, bands, and the lookback window

The hard part of a recurring job is not noticing the problem. It is **not telling you
twenty-eight times.**

Every job that can notify carries a **tag** describing *the situation it is reporting*, and
`already_said()` refuses to raise the same tag twice. What goes in the tag decides
everything, and there are two shapes:

**⚠ A tag that encodes a changing set — and why this reasoning was wrong.**

`task_nudge` used to hash the ids of the currently-overdue tasks, and the argument for it
ran: complete one and the hash changes, so the next nudge is new information; change nothing
and it stays silent. Such a tag "stops matching by itself", so it wants an *unbounded*
lookback.

That is true of the situation **changing**. It is silent about the situation **changing
back**. The tag samples the state; it cannot represent a transition, so `{gifts}` -> `{}` ->
`{gifts}` produces the identical tag at both ends.

In production it ran exactly like that. The nudge raised one notification in the lifetime of
the application, on 2026-08-24 — never delivered, because no browser had subscribed yet, and
then removed from the panel. The task was rescheduled; its new due time passed two days
later; the tag matched; and every run afterwards returned `already_told`. The feature was
silent from its first firing and nothing reported an error anywhere.

Two things changed. The tag now includes each task's **due time**, so rescheduling is
recognised as a different situation. And the overdue nudge no longer asks `already_said` at
all — see *A situation you have to act on* below.

**A tag that can recur.** `disk_watch` tags by the 5% band the reading falls into —
`disk-80`, `disk-85`. Crossing 80% says so once; 81–84% is the same band and stays quiet;
crossing 85% is worse and speaks again. Bands rather than exact percentages, so a disk
hovering around a single number cannot chatter across it.

But a band **can come back**. Free some space, drift up again next month, and an unbounded
lookback would find the year-old row and stay silent forever — the alert would fire once in
the lifetime of the installation. So `disk_watch` passes `since=24h`: **told once on
crossing, reminded daily while still above.**

Getting this backwards produces either an alert that never fires again, or one that fires
every run. Both look like the code working.

**The test is whether the tag contains something monotonic.** `journal-2026-08-27` and
`budget-warn-2026-08` each name one day or one month and can never come round again, so an
unbounded lookback is safe. `disk-80` names a state and needs `since`. The overdue
fingerprint named neither and had no bound, which is the failure above.

### A situation you have to act on

`already_said` answers *"is this news?"*, and news is the right control for a **measurement**.
It is the wrong control for **work the user still has to do**.

`task_nudge` therefore does not use it. It checks **hourly between 09:00 and 19:00** and
interrupts **at most every two hours** — up to six times a day if you ignore it.

⚠ Those are two numbers on purpose, and they were briefly one. A single two-hourly schedule
reads like *"remind me every two hours"* and quietly also means *"wait up to two hours to be
told at all"*: a task falling due at 11:05 is not overdue at the 11:00 check, so nothing is
said until 13:03. The schedule answers *how soon do I find out*; `REMIND_EVERY` answers *how
often am I nagged*. Pacing is measured from the last **delivery**, so a reminder held back by
quiet hours is not treated as an interruption that already happened.

The window ends at 19:00 rather than 21:00 because `day_end_summary` fires at 21:00 and
already lists what is overdue; two notifications arriving in the same second saying
overlapping things is how a reminder starts reading as noise.

The repetition ends when the task
is completed, dropped, deleted, snoozed, or its due time is moved into the future. Nothing
else ends it, and in particular reading or removing the notification does not.

That would be a column of near-identical rows in the panel each day, so it is **one record
per day, delivered repeatedly**: `notifications.todays_record` finds the record already raised for
this exact situation today and the runner delivers that again rather than writing another.
`push_count` is how many times, and the panel shows it as "Reminded 4 times". The wording is
recomputed on every reminder, so renaming an overdue task changes what the reminder says
rather than leaving it repeating this morning's name — the tag pins *which* situation the
record is about, and the text describes that situation as it reads now.

Two bounds on that lookup, each doing work. **Live**: if you delete today's reminder while
the task is still overdue, the next check writes a fresh record rather than re-delivering a
row that is not in the panel. **Today**: the panel is ordered newest-first, so a record from
three weeks ago would sit at the bottom of the list while the phone buzzed about it — invisible
in the very application doing the nudging.

The behaviour this trains is *deal with it, or reschedule it honestly*. That is deliberately
**not** stated in the notification text: a reminder that re-explains itself every two hours is
a worse reminder.

### Removing a notification does not make it unsaid

`already_said` deliberately **does not filter deleted rows.** It asks what has been *said*,
not what is still on screen. Were it filtered, dismissing a disk warning would erase the
evidence that it was ever said, so the next check would treat an unchanged situation as news
and push it again — delete would quietly mean *"tell me again shortly"*.

For the overdue nudge the question no longer arises, and the answer is the opposite anyway:
removing the reminder does not stop it, because it repeats until the task is dealt with.

### Deleting a briefing does not cause it to be written again

`job_runs` records what has run, keyed on `(job, occurrence)`. `generated_reviews` is only
that job's **output**. Removing the output leaves the run record untouched, so nothing
re-fires and nothing is spent composing a replacement.

Worth stating because it looks like a bug the first time you notice it, and because the
opposite arrangement — briefings as the source of truth — would have made deleting one cost
money to replace.

### What a job costs, and where you see it

A job that calls a model is traced as `turns.kind = "job"`, so its cost appears on **Insights**
beside your own messages — in the headline total, in the "Spend over time" chart as
**Scheduled**, and in *Recent calls* where you can open one and see where its time went.

That series was missing from the chart when scheduled jobs first shipped, which meant the
chart quietly understated spend while the tile above it did not. A chart that disagrees with
the number printed next to it is worse than no chart.

Most jobs cost nothing at all — eight of the ten never call a model.
