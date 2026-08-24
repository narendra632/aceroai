# Design

Every decision below was made against one constraint that shapes almost all of them: this
runs on a **1 GB always-free e2-micro with a 10 GB disk and no database backup**, serving one
user. Cleverness that costs memory loses. Cleverness that costs a round trip does not matter.

---

## Decision 1 — The scheduler lives in the API process

`AsyncIOScheduler` started in the FastAPI lifespan, taking the seat the Telegram poller
vacates.

**Rejected — a separate worker container.** A second Python + SQLAlchemy + psycopg process
is 150–200 MB resident on a box that already runs Postgres, Caddy and the API inside 1 GB.
It also doubles the deploy surface and splits the logs. If this app ever has more than one
user, this is the first decision to revisit.

**Rejected — system cron or a systemd timer.** A second deploy artifact outside the compose
stack, with no access to `settings`, logging to somewhere else. It would work and it would
be invisible.

**Rejected — Celery/RQ + Redis.** A message broker, a result backend and a worker pool to
run six functions a day for one person.

**Accepted cost:** if the API is down, jobs do not run. Decision 3 makes that survivable
rather than silent.

---

## Decision 2 — APScheduler holds exactly ONE job

APScheduler is registered with a single interval job — `tick()`, every 5 minutes. `tick()`
walks our own registry and decides what to run.

This is the decision that makes everything else testable. The alternative — registering six
APScheduler jobs and letting it fire each one — means the scheduler's internal state and our
`job_runs` table are two sources of truth that can disagree, and it makes every test need a
running event loop and a real scheduler.

With one tick:

- Tests call `tick(db, now=...)` directly. No scheduler, no loop, no sleeping.
- Adding a job touches no scheduler code at all.
- APScheduler is reduced to what it is genuinely good at here: **parsing cron expressions
  with timezone awareness** (`CronTrigger.from_crontab(expr, timezone=...)`) and running a
  drift-free ticker with clean shutdown.

**Rejected — a hand-rolled `while True: await asyncio.sleep(300)`.** It would work, and it
would slowly grow its own drift handling, exception handling and shutdown logic. We already
own the dependency.

**Rejected — APScheduler's `SQLAlchemyJobStore`.** It persists *the schedule*, which is
already in code and does not need persisting. What needs persisting is **whether a run
happened**, which the job store does not record.

---

## Decision 3 — Occurrence keys, and a catch-up window that is a policy

Each tick, for each enabled job, the runner computes the **most recent due occurrence** and
looks for it in `job_runs`:

```
occurrence_key = "2026-08-24T21:00:00+05:30"      # the scheduled instant, local tz
UNIQUE (job_name, occurrence_key)
```

No successful row → run it. A second tick, a second process, or a manual trigger for the
same occurrence hits the unique constraint. **Exactly-once is enforced by Postgres, not by
careful coding.**

**Computing "most recent due occurrence".** APScheduler's `CronTrigger` only walks forward.
Rather than add `croniter` for a backwards walk, the runner steps forward from
`now - catch_up_window` and keeps the last fire time that is `<= now`. With a 24-hour window
and an hourly job that is at most 24 iterations — a few microseconds.

The bound is **not a workaround, it is the policy.** A job missed by more than its window is
recorded as `missed` and skipped rather than run late, because a "morning brief" delivered at
6 pm is noise, not a late delivery. `catch_up_window` defaults to 24 h and is per-job:
`retention_sweep` gets 7 days (sweeping late is strictly better than not sweeping),
`task_nudge` gets 2 hours (a nudge about a deadline that has since passed is worse than
silence).

**Rejected — running every missed occurrence.** A VM off for three days would wake up and
send three morning briefs, three day-end summaries and 36 nudges. Only the most recent
occurrence of each job is ever considered.

---

## Decision 4 — A Postgres advisory lock, knowingly redundant

Each job execution takes `pg_try_advisory_lock(hashtext('job:' || name))`, released in a
`finally`.

The unique constraint already makes double-execution impossible, so this is belt-and-braces
and worth stating as such. It costs about fifteen lines and buys: two uvicorn workers, a
manual `python -m app.jobs.run` while the scheduler is live, and a future second container
all remaining correct. `try_` rather than a blocking lock — a job that cannot get the lock
skips this tick rather than piling up.

---

## Decision 5 — Three levels of AI involvement; the third is rejected

**Level 0 — no model.** `task_nudge`, `budget_watch`, `journal_nudge`, `retention_sweep`.
"Which tasks are overdue" is SQL. Free, instant, and structurally incapable of inventing a
task.

**Level 1 — the job owns the facts, the model owns the voice.** `morning_brief`,
`day_end_summary`:

```
brief = {done: 4, open: 7, overdue: 2, journalled: false, spend_today: 0.031}
         ^ built in SQL by the job

model receives: SOUL.md + brief + "write 3-5 sentences using only these facts"
model returns:  prose
model never:    queries the database, chooses what to include, decides what is true
```

The model cannot hallucinate a completed task because it was never given the ability to
look — it was handed a number. That is the property that makes a message written while you
sleep and read before you are awake safe to send unreviewed.

**Level 2 — a full agent loop on a timer: REJECTED.** A job calling `handle_message` with
tools available has unbounded cost, unbounded runtime, and takes *actions* rather than
producing text. An agent acting unsupervised at 3 am is a different risk class from an agent
answering a question you just asked, and nothing in this change needs it.

**Three rules on the AI jobs:**

1. Traced as `turns.kind="job"` — the CHECK constraint has allowed this since migration 007
   and nothing has ever written it. Job spend appears on Insights as its own slice.
2. `budget.check()` runs **before** the call. Over the cap → `skipped_budget` in `job_runs`,
   which is a visible outcome, not a silent one.
3. **A generated summary is never fed to the memory extractor.** Learning facts from your own
   output is a feedback loop where a phrasing hardens into a belief.

---

## Decision 6 — Retention moves from opportunistic to scheduled, and `sweep()` does not change

Today `telemetry.record()` calls `retention.maybe_sweep()` after every delivered reply,
gated by an **in-memory** `_last_run` date behind a thread lock.

Three problems, all of them structural:

1. It only runs if you talk to Acero. A quiet week prunes nothing.
2. It runs during the day, taking DELETE locks on `turns`/`spans` while you are using the
   app. The 3-second `lock_timeout` means it correctly gives up — so the work often just
   does not happen.
3. The state is memory-only, so every deploy re-arms it.

`retention_sweep` at 03:15 fixes all three. **`sweep()`, `rollup()`, `prune_spans()` and
`prune_turns()` are not touched** — they are already idempotent and correct, and only the
trigger was ever wrong. Deleted: `maybe_sweep`, `_lock`, `_last_run`,
`telemetry._housekeeping`, and the call from `telemetry.record`.

The `lock_timeout`/`statement_timeout` guards move **out** of retention and **into** the
shared job runner, where every job gets them.

The sweep also gains one new duty: pruning `notifications` past
`notification_retention_days` (90). A notification centre is a third unbounded table, and it
would have been an oversight to add one in the same change that fixes the other two.

---

## Decision 7 — A notification is a row; push is a delivery channel

> **Write the row, then attempt delivery. Never the reverse.**

This is the same shape as "one brain": one store, many transports. The row survives a denied
permission, a closed laptop, a dead subscription, a failed send, and a swipe-away.

**Rejected — push as the record.** An OS toast is gone the moment it is dismissed. A system
whose only memory of "you have two overdue tasks" is a notification you flicked off the
lockscreen while walking is not a system that reduces what you have to remember.

**Consequence:** push failure is not job failure. A job that wrote its notification row and
failed to push is `ok`, with the push failure recorded on the subscription
(`last_error_at`), not on the job. Conflating them would make a phone left in a drawer look
like broken software.

---

## Decision 8 — Digests live in Journal, as a second tab

`generated_reviews` rows are 3–5 sentences — too long for a notification, too small for a
section of their own.

**Chosen: Journal gains two tabs — "Your entries" and "Acero's briefings".** They are the
same shape (dated, one per day, reflective), it adds no top-level navigation, and it puts
Acero's account of a day directly beside yours.

**Rejected — a new top-level "Briefings" view.** Seven nav items for a page holding one short
paragraph per day.

**Rejected — injecting the summary into Chat as an assistant message.** Conceptually the
purest form of "Acero speaks first", and it breaks two things: a `messages` row with no user
turn preceding it, and a chat session that grows an entry every night whether or not you
opened it. Attractive and wrong.

---

## Decision 9 — The service worker is hand-written

**Rejected — `vite-plugin-pwa`.** It brings Workbox plus a build-time configuration layer to
generate a precache manifest. We need two things: an offline shell and a `push` listener.

The strategy chosen needs **no generated manifest at all**:

- **navigation → network-first**, falling back to a cached shell
- **hashed build assets → cache-first** (they are content-addressed; they cannot go stale)
- **API requests → never touched** (cross-origin, authenticated, always fresh)

A versioned cache name (`acero-v1`) and a `activate` handler that deletes older ones is the
entire cache-invalidation story.

**Cross-origin note that would otherwise bite us:** the frontend is on Vercel, the API is on
DuckDNS. The service worker's scope is the **Vercel** origin. Push subscriptions are
registered per-origin (Vercel) but stored by our API. This works, and it requires `/sw.js` to
be served with `Cache-Control: no-cache` — hence a `vercel.json`, which the repo does not
currently have.

---

## Decision 10 — The push payload carries encrypted content

**Chosen:** aes128gcm-encrypted `{title, body, url, tag}` inside the push message.

**Rejected — an empty push, with the service worker fetching the content from our API.** It
sounds cleaner and it is not: a service worker cannot read `localStorage`, which is where the
auth token lives. Making it work means putting the bearer token in IndexedDB so the worker
can read it — widening a credential's exposure to fix a problem that encryption already
solves. The push service relays the ciphertext and cannot read it; Google never sees the
content.

**Constraint this imposes:** ~4 KB after encryption, so the payload is a **pointer, not
content**. The body is one line; the substance is in the app. `tag` coalesces — a second
nudge replaces the first rather than stacking.

---

## Decision 11 — VAPID keys are generated once, by hand, into `.env`

`app/scripts/generate_vapid.py` prints a P-256 keypair. Narendra pastes it into `.env`
himself — the standing rule is that this repository's tooling never writes that file.

**Rotating VAPID keys invalidates every existing subscription**, so this is a one-time setup
and the script says so in its own output. The public key is genuinely public and ships to the
browser as `VITE_VAPID_PUBLIC_KEY`; the private key is a secret and lives only in `.env`.

**Dead subscriptions must be deleted, not retried.** A push service returns `404`/`410 Gone`
when a browser is uninstalled or its storage cleared. Ignoring that accumulates endpoints
that every job then pays for forever. `410` and `404` delete the row; everything else records
`last_error_at` and leaves it.

---

## Decision 12 — Notification policy is central, not per-job

Three controls, all applied by the runner so no job can forget them:

| Control | Default | Behaviour |
|---|---|---|
| Per-job enable | from the registry | Disabled → `skipped_disabled`, no row, no push |
| Quiet hours | 22:00–07:00 | Row **is** written; push suppressed. You see it in the bell in the morning |
| Daily push cap | 6 | Beyond it, rows are written and pushes are dropped |

Per-job preferences live in a **sparse** `user_job_prefs` table — absence means "registry
default". This is the specific mechanism that makes "adding a job needs no migration" true
rather than aspirational.

**Rejected — a JSONB preferences blob on `users`.** Cheaper to write, impossible to query,
and it would let a typo'd job name persist silently.

---

## Decision 13 — Telegram's data outlives Telegram's code

`users.telegram_chat_id` is dropped — nothing reads it.

`chat_sessions.channel` keeps its `('web','telegram')` CHECK, **unchanged**, with a comment
explaining why. Those rows are real conversations Narendra had. Rewriting them to `'web'`
would make the record lie about where they happened, and dropping them would destroy history
to tidy a constraint.

`handle_message(channel=...)` stays channel-agnostic. The `channels/` package is deleted
because there is exactly one channel now and it is the API — but the **one brain** rule is
unaffected, and it is what makes adding a channel back a small change rather than a rewrite.

**One thing deliberately kept:** `main.py`'s `RedactingFormatter` and the
`httpx → WARNING` line. The bot-token regex goes with Telegram, but provider URLs can carry
`?key=`, so the generic pattern and the log-level decision both stand. The *reason* changes;
the *decision* does not.

---

## Decision 14 — `/api/learn/constants` stays numbers-only

`test_api_learn.py` asserts every served field is `int` or `float`. That is not a style
preference — it is what makes leaking a secret-shaped string through that endpoint
structurally impossible.

So cron expressions do **not** go through it. The Learn page renders schedules from the job
list endpoint instead, and the constants endpoint gains only numbers: `job_count`,
`push_ttl_seconds`, `notification_retention_days`, `quiet_hours_start_hour`,
`quiet_hours_end_hour`, `daily_push_cap`, `job_tick_seconds`, `catch_up_window_hours`.

---

## Decision 15 — What a job returns

```python
@dataclass(frozen=True)
class JobResult:
    notify: Notification | None = None    # a row to write, and maybe push
    review: ReviewDraft | None = None     # a generated_reviews row
    detail: dict | None = None            # recorded on job_runs, for debugging
    silent: bool = False                  # ran, correctly had nothing to say
```

`silent=True` is load-bearing. `task_nudge` runs twelve times a day and usually finds
nothing — that is success, not a no-op to be logged as noise, and it must be distinguishable
from a failure at a glance in `job_runs`.

---

## Risks

| Risk | Handling |
|---|---|
| **Push cannot be tested in CI** — no browser, no push service | The sender is tested against a fake. Live verification on a Pixel is a **required task**, not optional |
| A job hangs and blocks the tick | `statement_timeout=60s`, `max_instances=1`, and the tick itself is `asyncio`-scheduled so a stuck job delays only later jobs in the same tick |
| iOS users get no push without installing | Detected and stated in the UI. Not fixable — Apple's rule |
| A digest reads as generic filler | The brief is deterministic and specific; if there is nothing to say, the job returns `silent` rather than padding |
| Notifications table grows unbounded | Pruned by `retention_sweep` at 90 days — the same oversight that made this change necessary is not repeated inside it |
