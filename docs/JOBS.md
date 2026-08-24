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
| `task_nudge` | hourly, 09–21 | +45 min | Next hour's nudge beats a stale one |
| `budget_watch` | 09:00 | 21:00 | A spend warning is useful all day |
| `journal_nudge` | 20:30 | 22:30 | "Write about today", delivered tomorrow, is noise |
| `retention_sweep` | 03:15 | **however late** | Sweeping late beats not sweeping |

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
`retention_sweep`. *"Which tasks are overdue"* is a database query, not a question for a
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

`silent` is load-bearing. `task_nudge` runs twelve times a day and usually finds nothing —
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
| `pg_try_advisory_lock` | Two processes doing the same work at once |
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

## 8. Where the code is

```
backend/app/jobs/
  registry.py      what a job IS, the @job decorator, and the validation
  runner.py        what is DUE, and running it exactly once
  scheduler.py     the ticker — APScheduler holds exactly one job
  run.py           python -m app.jobs.run
  housekeeping.py  retention_sweep
  brief.py         morning_brief, day_end_summary   (the only jobs that call a model)
  nudges.py        task_nudge, budget_watch, journal_nudge

backend/app/services/job_prefs.py    on/off, and how the schedule is phrased for a person
backend/app/api/jobs.py              list and toggle
```

Tests: `backend/tests/test_jobs.py` (the machinery) and `test_job_content.py` (what the six
shipped jobs actually decide).
