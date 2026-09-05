# Acero — a briefing for planning the Investments feature

> **Who this is for.** You are being asked to help plan an **Investments page** for an
> existing, live application called Acero. This document tells you what Acero is, how it is
> built, and — most importantly — **the conventions any new feature must obey**, so your plan
> fits the system instead of fighting it.
>
> Written on 2026-09-03, after 15 shipped changes. Everything described as built is built and
> running in production.

---

## 1. What Acero is

A **single-user personal AI assistant**. One human uses it: Narendra. There is no multi-tenant
concern, no sign-up flow, no other user to design around.

It is not a chatbot wrapper. It is a system that:

- **Holds a conversation** and remembers facts about him across sessions
- **Keeps his tasks and journal**, and can read and write them during a conversation
- **Speaks first** — scheduled jobs send him a morning brief, a day-end summary, and nudges
  about overdue tasks, delivered to his phone as push notifications
- **Watches itself** — tracks what every AI call cost, how long it took, and the server's
  own disk/memory/load

He is building it primarily **to learn how software is really built** — architecture,
trade-offs, operations — not just to have the tool. That matters for how you plan: he wants
the **correct, complete implementation**, with trade-offs surfaced explicitly. He has said
plainly he does not want simplified versions "for now".

---

## 2. The stack

| Layer | What |
|---|---|
| Backend | **FastAPI**, Python 3.12, **synchronous SQLAlchemy 2.0** |
| Database | **Postgres 17 + pgvector**, migrations via **Alembic** (currently at 013) |
| Frontend | **React 19 + Vite + Tailwind v4 + shadcn/ui** (Radix), TypeScript |
| AI | Multi-provider — Google Gemini (native SDK) and OpenAI-compatible. Swappable in Settings |
| Hosting | Frontend on **Vercel**. Backend on a **Google Cloud e2-micro** behind Caddy, at a DuckDNS domain |
| CI/CD | GitHub Actions. Push to `main` → tests → build image → SSH deploy. **Deploy is gated on tests passing.** |

⚠ **The server is a 1 GB e2-micro with a ~10 GB disk, currently 77% full.** This is a real
constraint. Anything that stores a lot of data, runs heavy computation, or adds a large
dependency has to be weighed against it.

---

## 3. Architecture — the shape you must fit into

```
                    ┌──────────────────────────┐
   Browser ───────▶ │  api/  (thin HTTP routes)│
   (React SPA)      └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
   Scheduled  ────▶ │  services/               │ ◀──── AI tool calls
   jobs             │  THE SINGLE SOURCE OF    │       (the assistant
                    │  TRUTH FOR ALL RULES     │        acting on its own)
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  db/ models + Postgres   │
                    └──────────────────────────┘
```

**The rule that shapes everything: a business rule is written once, in `services/`, and both
the REST API and the AI's tools call it.** If a rule exists in only one of those two places,
the feature is wrong. This is the project's most load-bearing convention.

### Key directories

```
backend/app/
  core/
    handler.py      THE ONE BRAIN — all conversation flows through handle_message()
    composer.py     builds the prompt each turn (persona, date, tasks, recalled facts)
    recall.py       hybrid memory search: pgvector + Postgres full-text, fused by RRF
    memory.py       fact extraction and embedding
    llm.py          provider facade
    pricing.py      dated price list; cost is frozen at write time
    telemetry.py    traces every turn and span
    tools/          ONE MODULE PER DOMAIN (tasks.py, journal.py, memory.py).
                    Each exports its schemas AND handlers together.
                    Adding a domain = adding a file, never editing a shared list.
    providers/      google.py, openai_provider.py, behind one contract
  services/         tasks · journal · memory · insights · budget · notifications ·
                    retention · vitals · job_prefs · user_settings
  api/              auth · chat (SSE) · tasks · journal · memory · insights ·
                    settings · notifications · jobs · learn
  jobs/             registry · runner · scheduler + 7 scheduled jobs
  db/models.py      14 tables

frontend/src/
  components/       the SPA's screens
  hooks/            includes useOptimisticList (the shared list-mutation pattern)
  lib/api.ts        every backend call
  lib/learn/        the Learn page's content as TYPED DATA, not prose in components
```

### The 14 tables

`users` · `chat_sessions` · `messages` · `tasks` · `journal_entries` · `profile_facts` ·
`generated_reviews` · `turns` · `spans` · `daily_usage` · `job_runs` · `notifications` ·
`push_subscriptions` · `user_job_prefs`

---

## 4. Non-negotiable conventions

These are enforced by tests, CI, and review. **A plan that violates one of these will be
rejected.**

1. **One brain.** All conversational logic goes through `core/handler.handle_message()`.
   Channels are thin adapters with no chat logic in them.
2. **`services/` is the single source of truth** for both the API and the AI's tools. Never
   implement a rule in only one.
3. **Derived values are computed, never stored.** Task urgency is derived from `due_at` +
   `priority` at read time. *(This one will matter a lot for Investments — see §8.)*
4. **All timestamps are `timestamptz`.** Rendered in the user's timezone (Asia/Kolkata).
5. **Schema changes only via a new Alembic migration.** Never edit an applied one.
6. **Soft delete, with undo.** Everything the user can delete gets a `deleted_at` column, an
   undo toast for a short window, and readers that filter it. This is a UI standard, not an
   optional nicety.
7. **Secrets live only in `.env`.** Never in the UI, never in code. gitleaks runs pre-commit.
8. **Dependencies via `uv add` only, and ASK before adding any.** Every new dependency is a
   deliberate decision on a 1 GB machine.
9. **Prefer `Text` + CHECK constraints over Postgres enums.**
10. **Docs and diagrams are updated by the change that alters the behaviour**, never
    afterwards. `ARCHITECTURE.md` describes only what is built; anything planned goes in
    `ROADMAP.md`.
11. **No shortcuts on UI/UX.** The bar is a finished product — no raw native controls where a
    themed one belongs, no destructive action without confirmation, no silent success.
12. **Scheduled work is idempotent and records its runs.** A job resolves to an occurrence
    that is unique in `job_runs`; the scheduler is only a ticker.
13. **Notifications are stored, then delivered.** The row is written before any push is
    attempted, so it survives a refused permission or a dead device.

---

## 5. How work gets done — OpenSpec

**Every non-trivial feature is planned before it is coded.** The workflow is:

```
propose  →  Narendra reviews  →  apply  →  archive
```

A proposal is four artifacts in `openspec/changes/<name>/`:

| File | Contents |
|---|---|
| `proposal.md` | **Why** this is needed, **What Changes**, which capabilities are added or modified, **Impact**, and an explicit **Non-goals** section |
| `design.md` | **Decisions with alternatives considered and rejected**, risks and trade-offs, migration plan, open questions |
| `specs/<capability>/spec.md` | The behavioural requirements in `SHALL` language, each with `WHEN/THEN` scenarios |
| `tasks.md` | A numbered checklist, granular enough to verify each item |

There are 17 "capabilities" — named behavioural areas that specs attach to: `assistant-tools`,
`auth`, `deployment`, `documentation`, `journal`, `knowledge-graph`, `learnings`,
`llm-provider`, `memory`, `notifications`, `observability`, `pwa`, `scheduled-jobs`, `tasks`,
`telegram`, `ui-standards`, `web-chat`.

**Investments will likely need a new capability**, plus modifications to `assistant-tools` and
possibly `scheduled-jobs`.

> **What this means for your plan:** produce something that maps cleanly onto those four
> artifacts. Reasoning about *why*, with alternatives named and rejected, is valued more than
> code sketches. State non-goals explicitly.

---

## 6. What already exists that Investments can build on

Do not reinvent these. They are built, tested, and live.

| Capability | What you get for free |
|---|---|
| **Tasks** | CRUD, due dates, priority, snooze, soft delete + undo, AI tool access |
| **Journal** | Dated entries, mood, tags, soft delete, AI tool access |
| **Memory** | Facts about the user, hybrid search (vector + keyword), one-writer discipline |
| **Knowledge graph** | Visual map of stored facts |
| **Scheduled jobs** | Add a job with a decorator. You get idempotence, failure isolation, run recording, a Settings toggle, quiet hours, and budget checks — **all for free** |
| **Notifications** | Store-then-deliver, web push to his phone, quiet hours, undo-able removal |
| **Insights** | Cost per AI call, latency percentiles, failure rates, spend chart, monthly ceiling |
| **Learn page** | Explains the system to him; **content is typed data with `{placeholders}` resolved from a live endpoint — a lint check fails if a reference goes stale** |
| **AI tools** | `core/tools/<domain>.py` — add a file, get a new capability the assistant can use in conversation |
| **Settings** | Model choice, budget, quiet hours, per-job toggles |

### The scheduled-jobs registry (very relevant)

Adding recurring work is one decorator:

```python
@job("name", "0 9 * * *", description="What the user reads in Settings.",
     catch_up=dt.timedelta(hours=4), uses_ai=False)
def my_job(db, user) -> JobResult:
    ...
```

`catch_up` declares how stale the output may be. It governs both whether a missed run executes
late **and** how long a push notification stays valid. `uses_ai=True` routes it through the
budget check and cost tracing automatically.

The seven existing jobs: `morning_brief`, `day_end_summary`, `task_nudge`, `journal_nudge`,
`budget_watch`, `disk_watch`, `retention_sweep`.

---

## 7. Known problems — things a plan should be aware of

| ⚠ | Problem | Relevance to Investments |
|---|---|---|
| 1 | **No database backup exists.** | **Highest.** Investments means financial data. Narendra's own stated rule was "back up when Investments ships". This should probably be part of, or immediately precede, the Investments work. |
| 2 | **Disk is at 77% of 10 GB.** Alerts at 80%. | Anything storing price history or documents must be sized deliberately. |
| 3 | A warning raised during quiet hours can go a day without buzzing. | Only matters if Investments raises alerts at night. |
| 4 | Five memory tests fail at random in CI, blocking deploys unpredictably. | Will interrupt shipping at a random moment. |
| 5 | Keyboard-only navigation has never been tested on any screen. | If Investments has forms or tables, this is the moment to not add more debt. |

---

## 8. Questions worth answering in the Investments plan

Not prescriptive — these are the places where this system's conventions will push back
hardest, so a plan is stronger for having answered them.

1. **What is stored versus computed?** Convention 3 says derived values are never stored.
   Current value, gain/loss, allocation percentages, XIRR — these look like derived values.
   But a *price on a date* is a fact. Where does the line fall, and why?

2. **Where does market data come from — and does it come at all?** Every external dependency
   costs money, a rate limit, and a failure mode on a 1 GB box. Is this a **manual-entry
   ledger** (no external calls, always correct, more typing) or a **live-price tracker** (an
   API, a scheduled fetch job, staleness handling)? This is the single biggest fork in the
   design and Narendra's research files should settle it.

3. **Does the assistant get tools for this?** Convention 2 says a rule lives in `services/`
   and both the API and the tools call it. Should he be able to say *"add 10 shares of X at
   ₹1,400"* in chat? If yes, that is a `core/tools/investments.py` file and the service must
   be designed for both callers from the start.

4. **Is there scheduled work?** A daily price refresh, a portfolio summary in the morning
   brief, an alert when something moves sharply. Each is cheap given the registry — but each
   is also another interruption, and Narendra is deliberate about notification volume.

5. **What does the money model look like?** Currency (₹ INR), decimal precision, whether
   multiple currencies exist, how buys/sells/dividends/splits are represented. Use
   `Numeric`, never floats.

6. **What is the historical record?** If a holding is sold, is the row deleted, soft-deleted,
   or does it become a closed position? Convention 6 says soft delete with undo — but a sale
   is not a deletion, it is an event. Does this need a transactions table rather than a
   holdings table?

7. **What does the page actually show, and in what order of importance?** The UI bar here is
   high, and charts have their own standards in this project (accessible categorical
   palettes, no dual-axis charts, direct labels).

8. **What are the non-goals?** Explicitly. Tax reporting? Broker sync? Multi-portfolio?
   Saying no is part of the proposal format.

---

## 9. Style notes that will make the plan land well

- **Name alternatives you rejected, and why.** This project's design documents are full of
  "considered X, rejected because Y". That is the expected shape.
- **Quantify claims.** "Measured: 5619 ms without the index, 170 ms with it" beats "faster".
- **Say what you do not know.** Open questions are a section in the design doc, not a
  weakness.
- **Prefer the correct implementation over the quick one**, and if the correct one is
  expensive, price it explicitly rather than silently choosing the cheap one.
- **Explain in both technical and plain language.** Narendra is learning; a plan that teaches
  is worth more than one that only instructs.

---

## 10. One-paragraph summary, if you read nothing else

> Acero is a single-user personal AI assistant — FastAPI + Postgres/pgvector + React — running
> on a small 1 GB server, built by one person to learn how real software is made. Its central
> discipline is that **every business rule lives once in `services/`, and both the HTTP API and
> the AI's own tools call it**. Features are planned as written specifications before any code
> is written, with alternatives considered and non-goals stated. It already has tasks, a
> journal, cross-session memory, scheduled jobs, phone notifications, and cost observability —
> all of which the Investments page can build on. The two things to weigh most carefully are
> that **there is no database backup yet** and **the disk is 77% full**, and the biggest open
> design question is whether Investments is a manual ledger or a live-price tracker.
