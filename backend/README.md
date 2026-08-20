# backend — aceroai API

FastAPI backend for aceroai: authentication, the "one brain" chat handler, the
provider layer, and the database. Sync SQLAlchemy 2.0 on Postgres 17 + pgvector.
Models are reached through `core/providers/`, where **each provider uses its own
native SDK** — deliberately *not* an OpenAI-compatibility shim (see
[Model providers](#model-providers) for why that would break tool calling).

> For the *why* behind the architecture (one brain, computed-not-stored,
> timestamptz, provider swap), see [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
> This README is the *what & where*.

## Run it

All commands from `backend/` unless noted. Uses `uv` (never pip).

| Task | Command |
|---|---|
| Start Postgres (repo root) | `docker compose up db -d` |
| Apply migrations | `uv run alembic upgrade head` |
| Seed the single user | `uv run python -m app.scripts.create_user` |
| Dev API server | `uv run uvicorn app.main:app --reload` |
| Prove LLM wiring | `uv run python -m app.scripts.verify_llm` |
| Tests | `uv run pytest` |
| Lint + format | `uv run ruff check .` · `uv run ruff format .` |
| New migration | `uv run alembic revision --autogenerate -m "msg"` |

The API serves at `http://localhost:8000` (`/health`, `/docs` for the
interactive API explorer).

## Request lifecycle (chat)

```
POST /api/chat  ->  get_current_user (Bearer token -> user)
                ->  core/handler.handle_message   <- the one brain
                     |- persist user message        (db, via threadpool)
                     |- core/memory.recall          (embed msg -> pgvector; 4s cap)
                     |- core/composer.build_context (SOUL.md + now + open tasks
                     |                               + recalled facts + history)
                     |- core/llm.stream_with_tools  (provider, effort=low|high)
                     |    `- tool calls? run via services/, loop (see below)
                     |- persist assistant message    (db, via threadpool)
                     |- core/telemetry               (one timing line per turn)
                     |- schedule core/memory.extract_and_store  (background, off-path)
                ->  route wraps yielded deltas as SSE  ->  browser
```

The route is pure transport; all conversation logic lives in the handler, so the
Telegram channel reuses the exact same brain. Every stage is timed under logger
`aceroai.timing` — measured numbers in
[`../docs/REQUEST-ANATOMY.md`](../docs/REQUEST-ANATOMY.md).

## Tasks, journal & assistant tools

Tasks and journal entries have both a **REST API** (for the UI) and **assistant
tools** (for chat) — and both go through **one service layer** (`app/services/`),
so a task created by tapping "＋" and one created by the assistant are identical
and validated the same way.

**How the assistant acts.** Each chat turn hands the model a set of tools
(`app/core/tools/`, one module per domain — tasks, journal, memory). If it answers with text, that streams as before. If it
returns a **tool call**, `handle_message` runs it via the services, feeds the
result back, and loops — until the model gives a final answer:

```
message ─► handle_message ─► llm.stream_with_tools (messages + tool defs)
             ▲                        │
             │              text? ────┴──► stream to client (done)
             │              tool_calls? ─► emit `tool` (UI: "working…")
             └── append result ◄── tools.execute(db, user.id, name, args)
```

**Context awareness.** The user's **open tasks are injected into every turn** (with
ids, due/overdue and priority, capped by `CONTEXT_TASKS_LIMIT`), so the assistant
isn't blind: it refuses to duplicate work it can already see, acts on a task by id
in a single step instead of looking it up first, and can surface what's due without
being asked. As a deterministic backstop, `services/tasks.create_task` refuses an
equivalent **open** task (case/punctuation-insensitive) and returns the existing one
— `409` over REST, and a structured `existing` payload to the assistant. Pass
`allow_duplicate=True` when a second copy is genuinely wanted.

Guardrails: the loop is capped at `TOOLS_MAX_ITERS` (then a forced text answer);
tools are **user-scoped by construction** (the model never supplies a user id, and
any record id is verified to belong to the caller); and `tools.execute` never
raises — a bad id/args/error returns a structured result the model recovers from.
The action policy (act on clear requests, offer on vague ones, confirm destructive
ones) lives in `../docs/SOUL.md`.

Endpoints: `GET/POST /api/tasks`, `PATCH/DELETE /api/tasks/{id}`,
`POST /api/tasks/{id}/complete`, `POST /api/tasks/{id}/restore`;
`GET/POST /api/journal` (`?q=` search, `limit`/`offset`),
`PATCH/DELETE /api/journal/{id}`, `POST /api/journal/{id}/restore`;
`GET/PATCH/DELETE /api/chat/sessions/{id}` (rename via PATCH),
`POST /api/chat/sessions/{id}/restore`, `POST /api/chat/sessions/{id}/regenerate`.
All are owner-scoped; service-layer domain errors map to `404` / `400` in `main.py`.

## Deleting is reversible

`DELETE` on a task, journal entry, or conversation **soft-deletes** it (migration
004 adds `deleted_at`), so the UI can offer Undo instead of a confirmation dialog.
`POST …/restore` clears it.

**The exclusion filter lives only in the `services/` query builders.** That is the
whole safety argument: the REST API, the assistant's tools, and
`composer.build_context`'s injected task block all read through that one layer, so
none of them can forget it. The composer path is the one that matters most — a leak
there would put a deleted task into the model's context, where Acero would act on
something the user believes is gone. `tests/test_soft_delete.py` checks each reader
separately.

Deleting a conversation **keeps its messages**, or a restore would hand back an
empty conversation. `services/sessions.py` exists for the same reason the other
services do: before it, `api/chat.py` queried `ChatSession` directly in its routes,
which would have put this filter in two places.

## Model providers

`core/llm.py` is a **facade**; the real work is in `core/providers/`, where each
provider is used through its **own native SDK** — not a compatibility shim, so no
provider's capabilities are degraded. They all satisfy one small contract
(`base.py`) that emits the events the handler already consumes:

```
("delta", str)        a chunk of visible text
("tool_calls", list)  tools to run, once at the end of the turn
```

| Provider | SDK | Auth | Billing |
|---|---|---|---|
| `google` | `google-genai` → **Agent Platform (Vertex)** | **ADC** — no API key | Google **Cloud Billing** (Cloud credits apply) |
| `openai` | `openai` | `OPENAI_API_KEY` | OpenAI account |

**Why native for Google:** Gemini attaches a `thought_signature` to every function
call that must be returned on the next turn. The OpenAI-compatible schema has
nowhere to carry it, so it is dropped and **multi-turn tool calls fail** — exactly
what our assistant does. The provider echoes the model's own turn back
(`_provider_raw`), and disables the SDK's *automatic* function calling so our own
bounded, user-scoped tool loop stays in charge.

**Credentials (Google):** `gcloud auth application-default login` locally; in
production the GCE VM's attached service account supplies ADC through the metadata
server — **no key file, no secret in `.env`**. It needs `roles/aiplatform.user`.

**Choosing provider + model:** per user, stored on `users` (migration 003) and
edited in the app's **Settings** screen. `services/user_settings.resolve()` is the
single source of truth (user value → configured default), and because the handler
calls it, **Telegram honors the same choice with no channel code**.

**Embeddings are pinned** (`EMBED_PROVIDER`/`EMBED_MODEL`/`EMBED_DIM`) and never
follow the chat provider: every stored `profile_facts` vector came from one model,
and vectors from a different model are not comparable — recall would silently
return nonsense. Changing them is a deliberate re-embed migration.

**Errors** are classified by cause (`TransientError`, `RateLimitError`,
`BillingError`), so an unpaid balance is never reported as a "rate limit".

Adding a provider = implement `base.Provider`, register it in
`providers/__init__.py`, add it to `MODEL_CATALOG`. Nothing above `llm.py` changes,
and the conformance suite in `tests/test_providers.py` holds it to the contract.

## File guide

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app: CORS, router includes, `/health`, lifespan hook |
| `app/config.py` | `Settings` — every env-driven knob (DB, JWT, LLM, timezone) |
| `app/core/llm.py` | Facade over the providers: `stream_with_tools`, `complete`, `embed` + shared retry/backoff |
| `app/core/providers/` | One contract (`base.py`), two **native** implementations: `google.py` (google-genai / Agent Platform) and `openai_provider.py` (openai SDK on the **Responses** API — Chat Completions rejects tools + reasoning together on gpt-5.4+) |
| `app/core/composer.py` | Builds model context: `SOUL.md` persona + current date/time + recalled facts + recent messages |
| `app/core/handler.py` | `handle_message` — the one brain; the bounded tool-use loop; yields SSE events |
| `app/core/tools/` | Assistant tools, one module per domain: `tasks.py` (create/list/update/complete/delete), `journal.py` (add/list), `memory.py` (remember/correct/forget). `__init__.py` assembles `TOOLS` + fault-tolerant dispatch and refuses to start if a schema and handler disagree |
| `app/core/memory.py` | Cross-session memory: extract → embed → store through the one writer; orchestrates recall |
| `app/core/recall.py` | Hybrid retrieval — vector ranker + keyword ranker, fused by RRF, with the selection rule |
| `app/core/security.py` | bcrypt hashing + JWT create/decode (HS256, 30-day) |
| `app/services/` | Single source of truth for `tasks`, `journal`, `memory` (fact rules + the kNN graph), `insights` (trace aggregates), `retention` (rollup + prune), `budget` (the monthly spend ceiling), and `user_settings` — used by the API *and* the tools/handler |
| `app/core/pricing.py` | Dated price list per provider/model. Cost is computed once, at write time, and frozen with its `pricing_version`, so a price change today cannot rewrite last month's spend. An unknown model costs `None`, never `0` |
| `app/api/deps.py` | `get_current_user` — auth guard (Bearer header or cookie) |
| `app/api/auth.py` | `POST /api/auth/login` · `/logout` · `GET /api/auth/me` |
| `app/api/chat.py` | `POST /api/chat` (SSE) · session list · history (owner-checked) |
| `app/api/tasks.py` | `/api/tasks` CRUD + `/{id}/complete` (owner-scoped) |
| `app/api/journal.py` | `/api/journal` CRUD (owner-scoped) |
| `app/api/settings.py` | `GET/PATCH /api/settings` — provider + model selection + the monthly spend limit; `GET /api/settings/budget` for the lightweight state the chat screen polls |
| `app/api/memory.py` | `/api/memory/facts` list/search/detail/edit/confirm/forget/restore/not-duplicate · `/api/memory/graph` · `/api/memory/stats` (owner-scoped) |
| `app/api/insights.py` | `/api/insights/overview` · `/turns` · `/turns/{id}` — **read-only**; no route here mutates anything |
| `app/api/schemas.py` | Pydantic request/response models |
| `app/db/session.py` | Engine, `SessionLocal`, `Base`, `get_db` dependency |
| `app/db/models.py` | The 10 ORM tables (typed `Mapped[]` style) — including `turns`, `spans` and `daily_usage` |
| `app/core/telemetry.py` | `Timeline` — per-turn stage timings and context description; `record()` persists a trace **after** the reply and guarantees a failure there can never reach it |
| `app/scripts/create_user.py` | One-time interactive user seeding |
| `app/scripts/verify_llm.py` | **Legacy** smoke test against the Gemini *Developer* API — does not exercise `core/providers/` |
| `app/channels/telegram.py` | Telegram long-poll adapter → `handle_message` |
| `app/jobs/` | **Empty package.** APScheduler is a dependency; no job is implemented yet. Retention currently sweeps opportunistically from `telemetry.record` instead — see the TODO in `services/retention.py` |
| `alembic/` | `…_001_core_tables.py` schema + pgvector · `…_002_fact_embeddings.py` `profile_facts.embedding` + HNSW · `…_003_user_model_prefs.py` per-user provider/models |
| `tests/` | 13 modules: `conftest.py` (fake LLM/embeddings + scoped data), `test_auth`, `test_chat`, `test_memory`, `test_telegram`, `test_providers`, `test_tools_loop`, `test_context_awareness`, `test_services_{tasks,journal}`, `test_api_{journal_tasks,settings}`, `test_prod_config`, `test_health` |
| `Dockerfile` | Production image (`uv sync --frozen --no-dev`) |

## Config & secrets

Runtime settings load from the repo-root `.env` (see `../.env.example`).
Secrets never live in code and never leave `.env`. Key vars:

- `DATABASE_URL` — **use host `127.0.0.1`, not `localhost`** on Windows (see
  `../.env.example` note; `localhost` can resolve to IPv6 and stall connects).
- `JWT_SECRET` — signs the auth token.
- `LLM_PROVIDER` / `MODEL_CHAT` / `MODEL_HEAVY` — **defaults only**. The active
  provider and models are a **per-user** setting stored on `users` (migration 003)
  and chosen in the Settings screen; `services/user_settings.resolve()` resolves
  user value → default.
- `GOOGLE_CLOUD_PROJECT` (ADC, no key) · `OPENAI_API_KEY` — which providers are
  offered depends on which credentials exist server-side.
- `REASONING_EFFORT_CHAT` — thinking budget for chat (`low` = fast first token;
  empty = don't send the param). See the "Memory & reasoning" section.
- `EMBED_MODEL` / `EMBED_DIM` / `MEMORY_RECALL_K` — semantic memory knobs.
  `EMBED_DIM` must match the `profile_facts.embedding` column (768, migration 002).
- `EMBED_LOCATION` — **latency only**, vectors are identical across regions. Pick
  the region nearest the *server*: `us-central1` from the Oregon VM, `asia-south1`
  when developing from India. The `global` endpoint measured **~12 s per call**.
- `MEMORY_RECALL_TIMEOUT_S` · `TOOLS_MAX_ITERS` · `CONTEXT_TASKS_LIMIT` — the
  bounds that keep a turn predictable.

> **Legacy:** `LLM_BASE_URL` / `LLM_API_KEY` target the Gemini *Developer* API and
> are read by **nothing but `app/scripts/verify_llm.py`**. They are not a provider
> swap — that mechanism no longer exists. Dead config for the running app.

## Auth in one paragraph

`POST /api/auth/login` verifies the password (bcrypt) and returns a **JWT** (HS256,
30-day). The SPA stores it in `localStorage` and sends it as
`Authorization: Bearer …`. Protected routes depend on `get_current_user`, which
accepts that header (and still falls back to a cookie), 401-ing if it is missing or
invalid. `me` returns the current email.

**Why a bearer token and not an httpOnly cookie:** the frontend (Vercel) and the
backend (DuckDNS) are different sites, so the login cookie is third-party and is
**blocked** by Brave and increasingly Chrome — login appeared to work and every
following request 401'd. **The trade-off is real and accepted:** a `localStorage`
token *is* readable by JavaScript, so an XSS bug could exfiltrate it, where an
httpOnly cookie could not. Fine for a single-user app. If this ever goes
multi-user, serve the UI and API from **one origin** and the first-party httpOnly
cookie becomes available again.

## Re-deriving the numbers

Two scripts keep the measured claims in the docs checkable rather than trusted:

| Command | What it answers |
|---|---|
| `uv run python -m app.scripts.measure_recall` | What recall returns for real queries against the real memory, and which ranker found each fact. Costs one embedding per query; writes nothing |
| `uv run python -m app.scripts.measure_recall_scale` | What hybrid recall costs at 200 / 1,000 / 5,000 facts. Inserts synthetic rows inside a transaction and **rolls back**, so the real memory is untouched |

Every recall number in `docs/ARCHITECTURE.md` and `docs/REQUEST-ANATOMY.md` comes from
these. If behaviour drifts, they are what catches it.

## Memory & reasoning

Acero remembers you **across sessions**. It's the first cognition layer, and it's
where pgvector does real work.

**One writer.** Every path that creates, changes or removes a fact — the three
assistant tools and the background extractor alike — goes through
`services/memory.remember()`. Validation, the duplicate judgement, supersession and
provenance are implemented once, so a fact you asked for by name and a fact learned
in the background obey the same rules.

- **Write, on purpose** — `remember_fact`, `correct_fact` and `forget_fact` let the
  assistant act when you *tell* it to. Facts written this way are recorded as
  `stated` (you said it) rather than `inferred`. A failed write comes back as a
  failure: the model cannot report a change it did not make.
- **Extract, in the background** — after each reply is delivered, `handle_message`
  schedules a task (`memory.extract_and_store`) that asks a cheap model for durable
  facts about you. It runs **off the reply path** in its own DB session and swallows
  every error. It may add and supersede but **never delete**.
- **Embed & store** — each new fact is embedded (`EMBED_MODEL`, `EMBED_DIM`) and
  written to `profile_facts.embedding` (a `vector(768)` column with an HNSW index,
  migration 002).
- **Nothing is discarded.** A proposed fact that sits close to an existing one is
  stored *and* linked via `possible_duplicate_of` (migration 010), not deleted.
  Measured, `AI-901` and `AI-103` are **0.098** apart — inside the 0.12 dedup
  threshold — while two phrasings of the same family fact are **0.216** apart,
  outside it. Closeness measures subject matter, not identity, so a near-duplicate
  is surfaced on the Knowledge page as a question rather than resolved by deletion.
- **Recall — two searches, fused.** `memory.recall` embeds the message, then runs
  a vector search *and* a Postgres full-text search (GIN index, migration 010) and
  fuses their **positions** with Reciprocal Rank Fusion. A fact both searches found
  is kept; a fact only one found must clear that search's own bar (distance ≤ 0.52
  for the vector side, a rare word for the keyword side). `MEMORY_RECALL_K` (16) is
  a **ceiling, not a quota** — a message about nothing stored recalls nothing.
  Recall is best-effort *and* **time-bounded** (`MEMORY_RECALL_TIMEOUT_S`, 4 s): a
  quota failure, a network error, or a stall just means no facts this turn.
- **Visible.** The facts used for a reply are streamed to the browser as a `recall`
  SSE event and shown behind the third control under each reply. Their ids also go
  into the `memory_recall` span, so the Insights waterfall can explain any past turn.
  Ids are identifiers, not content, so traces still record no message text.

**⚠ Embeddings are pinned on purpose.** They do not follow the user's chat-provider
choice. Every stored vector came from one model, and vectors from different models
are not comparable — same length, different coordinate space. Switching would not
raise an error; recall would quietly return nonsense. Changing `EMBED_MODEL` or
`EMBED_DIM` means re-embedding every stored fact in one deliberate migration.

**Adaptive reasoning:** the chat model is a *thinking* model, so `reasoning_effort`
is a per-request dial (`REASONING_EFFORT_CHAT=low` for fast chat,
`REASONING_EFFORT_DEEP=high` when more thought is wanted; empty = don't send it,
provider-swap safe). It's *adaptive* because the effort is chosen per turn, two ways:

- **Explicit user control** — the web composer has a "think harder" (🧠) toggle
  that sends `deep: true`; on Telegram, prefix a message with **`/think`**. Either
  routes that turn to `REASONING_EFFORT_DEEP`.
- **Task routing** — `handle_message(..., reasoning_effort=...)` lets any caller
  set the effort. Channels use it for the controls above; **future tasks** (e.g.
  the daily review) will pass `high` for deep work while chat stays fast. This is
  the hook new task types plug into over time.

*(A fully automatic router — a model that classifies each message and picks the
effort — is deferred until billing is enabled, since it adds an API call per
message and the free tier is tiny.)*

**Cost note:** each message makes several provider calls (chat + a recall embedding
+ background extraction/embeddings). Google usage runs on **Agent Platform (Vertex)
billed through Google Cloud Billing**, so Google Cloud credits offset it — this is
precisely why the provider layer targets Agent Platform rather than the Gemini
Developer API, whose separate **prepaid balance** the credits cannot pay for.
OpenAI usage bills to the OpenAI account. Set a **budget alert** so credit
exhaustion surfaces as a warning rather than as errors.

## Telegram channel

`channels/telegram.py` long-polls the Telegram Bot API (`getUpdates`) and routes
each authorized message through the **same** `handle_message` — the channel is a
thin adapter with no chat logic (golden rule 1). It replies with `sendMessage`
(one complete message, not token-streamed). The poller starts in the app
lifespan **only when `TELEGRAM_BOT_TOKEN` is set**, so runs without it are
unaffected. Long-polling is outbound, so **no hosting is needed** to test — run
the backend locally and message the bot from your phone.

Setup: get a token from **@BotFather**, put it in `.env` as `TELEGRAM_BOT_TOKEN`,
restart the backend, then send **`/start`** to the bot once — the first `/start`
links your chat to your account (trust-on-first-use); afterward only that chat is
served.

## Deploying

Production runs under Docker (`docker-compose.prod.yml`: Caddy auto-HTTPS + api +
Postgres/pgvector) on a Google Cloud e2-micro, fronted by a DuckDNS subdomain. A
push to `main` that passes CI auto-deploys (build → GHCR → SSH pull on the VM).
Prod env vars: `APP_ENV=prod`, `SOUL_PATH=/docs/SOUL.md`, `SITE_ADDRESS`,
`FRONTEND_ORIGIN`, `EMBED_LOCATION=us-central1` (nearest the Oregon VM).
`COOKIE_SECURE` / `COOKIE_SAMESITE` remain settable but are vestigial — auth is a
bearer token.

Google auth in production is the VM's own service account via ADC. Note that
`roles/aiplatform.user` alone is **not enough**: the VM also needs the
`cloud-platform` **access scope**, a separate gate that requires stopping the
instance to change. Full runbook: [`../docs/DEPLOY.md`](../docs/DEPLOY.md).
