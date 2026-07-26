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
                     |- core/composer.build_context (SOUL.md + recent history)
                     |- core/llm.stream_chat        (AsyncOpenAI -> Gemini)
                     |- persist assistant message    (db, via threadpool)
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
| `app/core/composer.py` | Builds model context: `SOUL.md` persona + recent messages |
| `app/core/handler.py` | `handle_message` — the one brain; yields SSE events |
| `app/core/security.py` | bcrypt hashing + JWT create/decode (HS256, 30-day) |
| `app/api/deps.py` | `get_current_user` — auth guard reading the cookie |
| `app/api/auth.py` | `POST /api/auth/login` · `/logout` · `GET /api/auth/me` |
| `app/api/chat.py` | `POST /api/chat` (SSE) · session list · history (owner-checked) |
| `app/api/schemas.py` | Pydantic request/response models |
| `app/db/session.py` | Engine, `SessionLocal`, `Base`, `get_db` dependency |
| `app/db/models.py` | The 7 ORM tables (typed `Mapped[]` style) |
| `app/scripts/create_user.py` | One-time interactive user seeding |
| `app/scripts/verify_llm.py` | End-to-end provider smoke test (never prints the key) |
| `app/channels/` | *(planned — Feature 2)* Telegram long-poller |
| `app/jobs/` | *(planned — Feature 3)* APScheduler + review jobs |
| `alembic/` | Migrations; `versions/…_001_core_tables.py` = schema + pgvector |
| `tests/` | `conftest.py` (fake LLM + scoped data), `test_auth.py`, `test_chat.py` |
| `Dockerfile` | Production image (`uv sync --frozen --no-dev`) |

## Config & secrets

Runtime settings load from the repo-root `.env` (see `../.env.example`).
Secrets never live in code and never leave `.env`. Key vars:

- `DATABASE_URL` — **use host `127.0.0.1`, not `localhost`** on Windows (see
  `../.env.example` note; `localhost` can resolve to IPv6 and stall connects).
- `JWT_SECRET` — signs the auth cookie.
- `LLM_BASE_URL` / `LLM_API_KEY` / `MODEL_CHAT` / `MODEL_HEAVY` — the provider
  swap: change these four, no code changes.

## Auth in one paragraph

`POST /api/auth/login` verifies the password (bcrypt) and sets a **JWT in an
httpOnly cookie** (`samesite=lax`, 30-day). Protected routes depend on
`get_current_user`, which decodes that cookie and 401s if it is missing or
invalid. `logout` clears the cookie; `me` returns the current email. The cookie
is httpOnly so browser JavaScript can never read the token.
