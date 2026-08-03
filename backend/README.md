# backend — aceroai API

FastAPI backend for aceroai: authentication, the "one brain" chat handler, the
LLM wrapper, and the database layer. Sync SQLAlchemy 2.0 on Postgres 17 +
pgvector; the LLM is reached through the openai SDK pointed at any
OpenAI-compatible endpoint (Gemini by default).

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
POST /api/chat  ->  get_current_user (cookie -> user)
                ->  core/handler.handle_message   <- the one brain
                     |- persist user message        (db, via threadpool)
                     |- core/memory.recall          (embed msg -> pgvector search)
                     |- core/composer.build_context (SOUL.md + recalled facts + history)
                     |- core/llm.stream_chat        (AsyncOpenAI -> Gemini, reasoning=low|high)
                     |- persist assistant message    (db, via threadpool)
                     |- schedule core/memory.extract_and_store  (background, off-path)
                ->  route wraps yielded deltas as SSE  ->  browser
```

The route is pure transport; all conversation logic lives in the handler so a
future Telegram channel reuses the exact same brain.

## File guide

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app: CORS, router includes, `/health`, lifespan hook |
| `app/config.py` | `Settings` — every env-driven knob (DB, JWT, LLM, timezone) |
| `app/core/llm.py` | Thin `AsyncOpenAI` streaming wrapper (`stream_chat`) |
| `app/core/composer.py` | Builds model context: `SOUL.md` persona + recalled facts + recent messages |
| `app/core/handler.py` | `handle_message` — the one brain; yields SSE events |
| `app/core/memory.py` | Cross-session memory: extract → embed → store facts (pgvector) → semantic recall |
| `app/core/security.py` | bcrypt hashing + JWT create/decode (HS256, 30-day) |
| `app/api/deps.py` | `get_current_user` — auth guard reading the cookie |
| `app/api/auth.py` | `POST /api/auth/login` · `/logout` · `GET /api/auth/me` |
| `app/api/chat.py` | `POST /api/chat` (SSE) · session list · history (owner-checked) |
| `app/api/schemas.py` | Pydantic request/response models |
| `app/db/session.py` | Engine, `SessionLocal`, `Base`, `get_db` dependency |
| `app/db/models.py` | The 7 ORM tables (typed `Mapped[]` style) |
| `app/scripts/create_user.py` | One-time interactive user seeding |
| `app/scripts/verify_llm.py` | End-to-end provider smoke test (never prints the key) |
| `app/channels/telegram.py` | Telegram long-poll adapter → `handle_message` (built, Feature 2) |
| `app/jobs/` | *(planned — Feature 3)* APScheduler + review jobs |
| `alembic/` | Migrations; `…_001_core_tables.py` = schema + pgvector; `…_002_fact_embeddings.py` = `profile_facts.embedding` + HNSW |
| `tests/` | `conftest.py` (fake LLM/embeddings + scoped data), `test_auth.py`, `test_chat.py`, `test_memory.py`, `test_telegram.py` |
| `Dockerfile` | Production image (`uv sync --frozen --no-dev`) |

## Config & secrets

Runtime settings load from the repo-root `.env` (see `../.env.example`).
Secrets never live in code and never leave `.env`. Key vars:

- `DATABASE_URL` — **use host `127.0.0.1`, not `localhost`** on Windows (see
  `../.env.example` note; `localhost` can resolve to IPv6 and stall connects).
- `JWT_SECRET` — signs the auth cookie.
- `LLM_BASE_URL` / `LLM_API_KEY` / `MODEL_CHAT` / `MODEL_HEAVY` — the provider
  swap: change these four, no code changes.
- `REASONING_EFFORT_CHAT` — thinking budget for chat (`low` = fast first token;
  empty = don't send the param). See the "Memory & reasoning" section.
- `EMBED_MODEL` / `EMBED_DIM` / `MEMORY_RECALL_K` — semantic memory knobs.
  `EMBED_DIM` must match the `profile_facts.embedding` column (768, migration 002).

## Auth in one paragraph

`POST /api/auth/login` verifies the password (bcrypt) and sets a **JWT in an
httpOnly cookie** (`samesite=lax`, 30-day). Protected routes depend on
`get_current_user`, which decodes that cookie and 401s if it is missing or
invalid. `logout` clears the cookie; `me` returns the current email. The cookie
is httpOnly so browser JavaScript can never read the token.

## Memory & reasoning

Acero remembers you **across sessions**. It's the first cognition layer, and it's
where pgvector does real work.

- **Extract** — after each reply is delivered, `handle_message` schedules a
  *background* task (`memory.extract_and_store`) that asks a cheap model for
  durable facts about you (preferences, goals, work, health…) and skips anything
  already known. It runs **off the reply path** in its own DB session and swallows
  every error, so it never slows or breaks a reply.
- **Embed & store** — each new fact is embedded (`EMBED_MODEL`, `EMBED_DIM`) and
  written to `profile_facts.embedding` (a `vector(768)` column with an HNSW index,
  migration 002). Semantic duplicates are skipped.
- **Recall** — for every incoming message, `memory.recall` embeds the message and
  runs a vector-similarity search (`embedding <=> query`) for the top
  `MEMORY_RECALL_K` **active** facts, which `composer.build_context` injects right
  after the SOUL.md persona. Recall is best-effort: a quota/network failure just
  means no facts this turn, never a broken chat.

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

**Cost note:** each message now makes several provider calls (chat + a recall
embedding + background extraction/embeddings). The Gemini **free tier is ~20
requests/day**, enough only for light testing — enable **billing → Tier 1** for
real daily use (pennies/day for one user).

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
Prod env vars: `APP_ENV=prod`, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none`,
`SOUL_PATH=/docs/SOUL.md`, `SITE_ADDRESS`, `FRONTEND_ORIGIN`. Full runbook:
[`../docs/DEPLOY.md`](../docs/DEPLOY.md).
