# Acero speaks first: scheduled jobs, and a way to reach you

## Why

Acero is **purely reactive**. It has never once started a conversation. Everything it knows
about your day — that two tasks went overdue, that you haven't journalled since Tuesday,
that this month's spend just crossed 80% of your ceiling — sits in Postgres waiting for you
to think to ask. The assistant that is supposed to reduce what you have to keep in your head
currently requires you to remember to consult it.

Two things are missing, and neither is useful without the other:

1. **Nothing runs on a schedule.** `app/jobs/` has been an empty package since Phase 0 and
   `apscheduler` has been a paid-for, unused dependency for just as long. The one piece of
   recurring work that exists — trace retention — rides on the back of a real user message
   through `retention.maybe_sweep()`, which its own docstring marks
   `TODO(scheduled-jobs)`. A quiet week is a week with no pruning, on a 10 GB disk.
2. **There is no way to reach you.** Telegram was that channel, and it has been the weakest
   part of the system since it shipped: a long-polling loop that only runs while the backend
   is up, a bot token that **leaked into production logs** before we caught it, and a second
   interface that every feature has to be re-tested against.

A digest nobody sees is a log line, and a notification system with nothing to say is
plumbing — so these ship together. Web push replaces Telegram with something the browser
already provides, encrypted end to end, with no third-party bot account and no credential to
leak. The PWA is what makes it installable and what iOS requires before it will deliver a
push at all.

## What Changes

### A. A scheduler whose source of truth is the database, not itself

APScheduler runs in the API process, taking the seat the Telegram poller vacates. But the
scheduler is only a **ticker** — a `job_runs` table decides whether a job has run.

Every job resolves to an **occurrence key** (`day_end_summary@2026-08-24`), unique in the
database. A job runs only when its due occurrence has no successful row. This is not
bookkeeping for its own sake; it is the difference between working and silently not working:
a deploy at 20:58 kills the 21:00 firing of an in-memory scheduler with no error anywhere.
Here the run simply happens at 21:10 when the new container ticks, and running twice is a
constraint violation rather than a duplicate notification.

### B. A registry, so a future job is one file

Adding a job is a decorator. Bookkeeping, idempotence, failure isolation, budget checks,
`turns.kind="job"` tracing, the Settings toggle, quiet-hours policy and the Learn entry all
come from the registry and cannot be forgotten. Per-job preferences live in a **sparse**
table, so **a new job needs no migration**.

Six jobs ship: `morning_brief` (07:30, AI), `task_nudge` (hourly 09–21, coalesced, no AI),
`day_end_summary` (21:00, AI), `budget_watch` (09:00, no AI), `journal_nudge` (20:30, no AI,
**default off**), and `retention_sweep` (03:15, no AI).

### C. The AI writes the words; the job owns the facts

Most jobs use **no model at all** — "which tasks are overdue" is a query, not a question. The
two digest jobs gather a brief deterministically in SQL and hand the model *only that dict*
plus `SOUL.md`, with an instruction to phrase it. The model never queries the database and
never decides what is true, which is what makes an unsupervised message safe to send while
you are asleep. A full agent loop on a timer is **explicitly rejected** (design Decision 5).

Generated summaries are **never** fed to the memory extractor — Acero must not learn facts
from its own output.

### D. Notifications are stored first and delivered second

A notification is a **database row**; push is one way of delivering it. The row is written
before any push is attempted, so the record survives a denied permission, a closed laptop, a
dead subscription or a failed send. This yields a **notification centre** — a bell with an
unread count — instead of an OS toast that is gone the moment it is dismissed.

Digests are longer than a notification, so they land in `generated_reviews` (a table
migration 001 created for exactly this and which has never held a row) and surface as a
**"Briefings" tab inside Journal**: your entries on one tab, Acero's on the other.

### E. Web push and an installable app

VAPID keys, payloads encrypted with aes128gcm, a hand-written service worker, `410 Gone` handling
that deletes dead subscriptions, `pushsubscriptionchange` re-subscription, and a **"Send test
notification"** button in Settings — because push involves five parties, four of them someone
else's, and it is the hardest thing here to debug without one.

The manifest makes Acero installable with home-screen shortcuts. **⚠ On iOS, web push
requires the app to be installed first** — Apple's rule, stated in the UI rather than left
for the user to discover.

### F. **BREAKING** — the Telegram channel is removed

`app/channels/` is deleted along with its tests, its poller, its config, its capability spec,
and its mentions across nine documentation files. `users.telegram_chat_id` is dropped.

**Existing Telegram conversations are preserved exactly as they are.** The
`chat_sessions.channel` CHECK still permits `'telegram'`, because rewriting those rows to
`'web'` would make the record lie about where the conversations happened.

### G. Everything that describes the system is updated with it

Two new plain-language docs (`docs/JOBS.md`, `docs/NOTIFICATIONS.md`), the architecture
diagram redrawn, two new lifecycle walkthroughs, and — in the product itself — a **third
Learn diagram, "How Acero speaks first"**, with new concept cards for cron and idempotence,
web push, service workers, and PWA install.

## Non-goals (this change)

- **No agentic jobs.** No job calls `handle_message` or runs a tool loop. Rejected on cost,
  runtime and risk class (design Decision 5).
- **No offline message queue.** The shell loads offline and views say so honestly. Background
  sync with an optimistic outbox is a real feature, not a freebie.
- **No weekly review.** `generated_reviews.kind='weekly'` already permits it and the registry
  makes it roughly one file. Deliberately out of scope so this change does not sprawl.
- **No email or SMS fallback.** Push is the only new delivery channel.
- **No alerting on system health.** A disk-usage job is tempting on a 10 GB VM with no
  backup and is named in `ROADMAP.md`, not built here.
- **No re-litigating the database backup decision**, which remains a priced, deliberate
  deferral.
- **No memory recall inside digests.** One model call per digest, no embedding.

## Capabilities

**New Capabilities**

- `scheduled-jobs` — recurring work that runs on time, at most once, and cannot damage the
  application when it fails
- `notifications` — the system tells the user something, durably, through whatever channels
  are available
- `pwa` — installable, offline-tolerant, and the delivery surface push requires

**Modified Capabilities**

- `observability` — trace retention moves from opportunistic to scheduled; the
  secrets-in-logs requirement survives Telegram's removal
- `assistant-tools` — "identical across channels (web and Telegram)" no longer describes
  reality
- `tasks` — same channel wording, plus tasks becoming a source of proactive nudges
- `learnings` — the stated minimum coverage gains "how the system acts on its own"

**Removed Capabilities**

- `telegram` — all five requirements removed; see the delta for reason and migration

## Impact

| Area | Change |
|---|---|
| **New dependency** | `pywebpush` (brings `py-vapid`, `http-ece`; `cryptography` is already in `uv.lock`). **Approved by Narendra on 2026-08-24.** The alternative was hand-writing aes128gcm and VAPID signing — ~120 lines of cryptography that should not be hand-rolled. No new frontend dependencies. |
| **Migration 011** | +`job_runs`, +`notifications`, +`push_subscriptions`, +`user_job_prefs`; `users` +`quiet_hours_start`/`quiet_hours_end`, −`telegram_chat_id` |
| **Backend** | +`app/jobs/` (registry, runner, six jobs), +`app/services/notifications.py`, +`app/core/push.py`, +`app/api/notifications.py`, +`app/scripts/generate_vapid.py`; −`app/channels/` |
| **Frontend** | +`public/sw.js`, +`public/manifest.webmanifest`, +`vercel.json`, +notification bell, +Briefings tab, +Settings→Notifications, +third Learn diagram; −template `favicon.svg` and `icons.svg` |
| **Config** | +`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `VITE_VAPID_PUBLIC_KEY`; −`TELEGRAM_BOT_TOKEN` |
| **Ops** | 🔒 The Telegram bot token must be **revoked with @BotFather** once this ships — it is a live credential that will no longer be used, and it is the one that leaked into the startup logs |
| **Risk** | Push cannot be verified in CI. Live verification on a Pixel/Chrome is a required task, not an optional one. |
