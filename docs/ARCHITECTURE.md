# ARCHITECTURE.md — aceroai

> Written at the close of Phase 0 (2026-07-20). Describes the repo as it
> actually exists; parts not yet built are explicitly marked
> `(planned — Feature N)`.

## 1. Overview

aceroai is a **single-user** personal AI assistant for Narendra: chat,
journaling, tasks, and scheduled reviews now; memory, habits, and investments
in later phases. One FastAPI backend serves two thin channels — a React SPA
and (later) a Telegram bot. All intelligence flows through one handler
("one brain"), backed by Postgres 17 + pgvector and an LLM reached through
the openai SDK pointed at any OpenAI-compatible endpoint (Gemini today).
Phase 0 delivered the scaffold: schema, config, security primitives, health
checks, tooling, and this document.

## 2. System diagram

```
  browser SPA (frontend/, Vite+React, :5173)      Telegram user
      │  GET /health  (today)                          │
      │  POST /api/chat over SSE (planned — Feature 1) │ long-poll (planned — Feature 2)
      ▼                                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI app — backend/app/main.py (:8000)                        │
│   api/    HTTP routes: auth, chat SSE, tasks, journal            │
│           (planned — Feature 1)                                  │
│   channels/telegram.py  thin poller  (planned — Feature 2)       │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
   core/handler.handle_message  — the one brain (planned — Feature 1)
                │
   core/composer — context builder, reads docs/SOUL.md (planned — Feature 1)
                │
   core/llm — thin AsyncOpenAI wrapper (planned — Feature 1)
                ▼
   Gemini via OpenAI-compatible endpoint  (base_url + key + model from .env)
────────────────────────────────────────────────────────────────────
   db/session.py + db/models.py  (sync SQLAlchemy 2.0)
                ▼
   Postgres 17 + pgvector  (docker compose service "db", loopback only)
────────────────────────────────────────────────────────────────────
   jobs/ — APScheduler started in app lifespan; day-end/weekly review
           jobs write generated_reviews  (planned — Feature 3)
```

## 3. Directory guide

### Root
| File | Role |
|---|---|
| `AGENTS.md` | Source of truth for stack, conventions, golden rules |
| `CLAUDE.md` | Claude Code entrypoint — defers to AGENTS.md, mandates OpenSpec flow |
| `README.md` | Short pointer readme |
| `PLAN.md` → `docs/plans/phase0-completion.md` | Archived Phase 0 execution plan |
| `.env.example` | Template documenting every env var (real values live only in `.env`) |
| `.gitignore` | Ignores `.env`, venvs, caches, `node_modules/`, `dist/` |
| `.pre-commit-config.yaml` | ruff (--fix), ruff-format, gitleaks secret scan |
| `docker-compose.yml` | `db` (pgvector:pg17, loopback-only, healthcheck) + `api` (prod image, DATABASE_URL host override to `db`) |
| `docs/SOUL.md` | Assistant persona ("Acero") — read by core/composer at every context build (planned — Feature 1) |
| `docs/ARCHITECTURE.md` | This file |
| `.github/copilot-instructions.md` | Points GitHub Copilot at AGENTS.md |
| `.github/workflows/ci.yml` | CI: uv sync → ruff check → ruff format --check → pytest |
| `.github/prompts/opsx-*.prompt.md` | Copilot slash commands for the six OpenSpec stages |
| `.github/skills/openspec-*/SKILL.md` | Agent skills for the six OpenSpec stages (Claude Code) |
| `.vscode/settings.json` | Interpreter path + ruff format-on-save |
| `.vscode/extensions.json` | Recommends ruff + python extensions |
| `openspec/config.yaml` | OpenSpec config (spec-driven schema; project context TBD) |

### Backend (`backend/`)
| File | Role |
|---|---|
| `pyproject.toml` | Runtime + dev deps; ruff config (line 100, py312, E/F/I/UP/B; `alembic/` excluded) |
| `uv.lock`, `.python-version` | Locked dependency graph; Python 3.12 pin |
| `README.md` | Empty uv-init placeholder |
| `Dockerfile` | python:3.12-slim + `uv sync --frozen --no-dev` production image |
| `alembic.ini` | Alembic config — `sqlalchemy.url` is overridden at runtime by env.py |
| `alembic/env.py` | Wires Alembic to `settings.database_url` and `Base.metadata` |
| `alembic/script.py.mako`, `alembic/README` | Migration template / boilerplate |
| `alembic/versions/f6eaae243cfc_001_core_tables.py` | Migration 001: `CREATE EXTENSION vector` + the 7 core tables |
| `app/config.py` | `Settings(BaseSettings)` — every runtime knob, loaded from `.env` |
| `app/main.py` | FastAPI app: CORS for the SPA origin, `/health`, lifespan hook (telegram poller + scheduler start here in Features 2/3) |
| `app/core/security.py` | bcrypt hash/verify + JWT create/decode (HS256, 30-day TTL) |
| `app/core/` (rest) | `llm.py`, `composer.py`, `handler.py` (planned — Feature 1) |
| `app/db/session.py` | Engine (`pool_pre_ping`), `SessionLocal`, `Base`, `get_db` dependency |
| `app/db/models.py` | The 7 ORM models (typed `Mapped[]` style) |
| `app/api/` | Empty package — HTTP routes land here (planned — Feature 1) |
| `app/channels/` | Empty package — telegram long-poller (planned — Feature 2) |
| `app/jobs/` | Empty package — APScheduler + review jobs (planned — Feature 3) |
| `app/scripts/create_user.py` | One-time interactive CLI to seed the single user |
| `app/scripts/verify_llm.py` | End-to-end provider wiring smoke test (never prints the key) |
| `tests/test_health.py` | TestClient check of `/health` |
| `app/**/__init__.py`, `tests/__init__.py` | Package markers (all empty) |

### Frontend (`frontend/`)
| File | Role |
|---|---|
| `vite.config.ts` | Vite with react + tailwindcss v4 plugins |
| `.env.development` | `VITE_API_URL=http://localhost:8000` (no secrets) |
| `index.html` | SPA shell |
| `package.json`, `package-lock.json` | Dependencies (react, vite, tailwind v4) |
| `tsconfig*.json` | TypeScript project configs (app / node split) |
| `.oxlintrc.json`, `.gitignore`, `README.md` | Vite template tooling files |
| `src/main.tsx` | React entry — mounts `<App/>` in StrictMode, imports index.css |
| `src/App.tsx` | Health-check page: fetches `/health`, renders green/amber/red dot |
| `src/index.css` | Single line: `@import "tailwindcss"` |
| `src/assets/`, `public/` | Template images/icons (unused; replaced when real UI lands) |

## 4. Lifecycle walkthroughs (design contract for upcoming features)

These describe what **will** happen — they are the contract Features 1–3 must
implement, not current behavior.

### (a) A chat message arrives (Feature 1)

1. SPA POSTs to `/api/chat` with the JWT httpOnly cookie; the route dependency
   (`get_db` + auth via `core/security.decode_access_token`) resolves the user.
2. The route is a **thin adapter**: it immediately calls
   `core/handler.handle_message(user, text, channel="web", session_id)`.
3. `handler` loads or creates the `chat_sessions` row, persists the incoming
   `messages` row (role `user`), and asks `core/composer` for context.
4. `composer` builds the prompt: `docs/SOUL.md` persona first, then recent
   session messages, later active `profile_facts` and urgent `tasks`.
5. `core/llm.stream_chat` (AsyncOpenAI on `settings.model_chat`) streams
   tokens; the route forwards them to the browser over SSE (sse-starlette).
6. `handler` persists the assistant `messages` row (content, model, token
   counts) and bumps `chat_sessions.last_active_at`.
7. The same message from Telegram enters via `channels/telegram.py` and calls
   the **same** `handle_message` with `channel="telegram"` — golden rule 1:
   channels contain zero conversational logic.

### (b) 9:45 pm — day-end summary (Feature 3)

1. APScheduler (started in the app lifespan, cron in the user's
   `users.timezone`) fires the daily review job in `app/jobs/`.
2. The job gathers the day: `journal_entries` for today, `tasks` completed /
   due / overdue, notable `messages`.
3. `composer` assembles a review prompt (persona + gathered day) and
   `core/llm` runs it on `settings.model_heavy`.
4. The result is written to `generated_reviews` (kind `daily`,
   `period_start`/`period_end` bounding the local day, `delivered_to`
   recording channels).
5. Delivery: pushed to Telegram (once Feature 2 exists) and readable in the
   web UI; the row is the durable record either way.

## 5. Data model rationale

Seven tables: `users`, `chat_sessions`, `messages`, `tasks`,
`journal_entries`, `profile_facts`, `generated_reviews`.

- **`timestamptz` everywhere** — golden rule 3. Store unambiguous UTC
  instants; render in `users.timezone` at the edge. Naive timestamps rot the
  moment a timezone or DST boundary is crossed.
- **Urgency is computed, never stored** — it is fully derived from `due_at` +
  `priority` at read time. A stored urgency goes stale every minute; a
  computed one cannot (golden rule 2).
- **`Text` + CHECK constraints over Postgres enums** — changing an enum needs
  `ALTER TYPE` ceremony; swapping a CHECK is one cheap migration. Same
  integrity, less friction (golden rule 7).
- **`profile_facts` supersession** — facts are never updated in place. A new
  fact row supersedes the old one (`status='superseded'`, `superseded_by` →
  new row's id), preserving a full history with `valid_from` timelines.
  `source` (stated/inferred) + `confidence` let the composer weigh how firmly
  to assert a fact; `rejected` records facts the user explicitly denied so
  they are never re-inferred.
- **The vector column waits for Phase 2** — an embedding column's dimension is
  fixed by the chosen embedding model. Adding `embedding vector(N)` + HNSW
  index to `journal_entries` before that model is chosen would marry the
  schema to a guess. The `vector` extension is already installed (migration
  001), so Phase 2 is a small additive migration.

## 6. Config & secrets

- `app/config.py` defines `Settings(BaseSettings)`; pydantic-settings loads
  `.env` (repo root — `"../.env"` covers running natively from `backend/`,
  `".env"` covers docker/repo-root) with `extra="ignore"`. Each lowercase
  field maps to its UPPERCASE env var.
- **Provider swap recipe** (no code changes): set `LLM_BASE_URL`,
  `LLM_API_KEY`, `MODEL_CHAT`, `MODEL_HEAVY` in `.env`. Today: Gemini's
  OpenAI-compatible endpoint with `gemini-3.5-flash` (chat) and
  `gemini-3.1-pro-preview` (heavy). Note: `gemini-2.5-*` ids are gated for
  newer Google accounts and return 404.
- **Secrets never leave `.env`**: it is gitignored (verified never
  committed), gitleaks scans every commit, docker-compose injects
  `POSTGRES_PASSWORD` from it, and scripts print replies — never keys.

## 7. Development workflow

Every non-trivial feature follows the OpenSpec cycle:

| Stage | Command | Meaning |
|---|---|---|
| Propose | `/opsx:propose` | Write spec + tasks; human reviews before any code |
| Apply | `/opsx:apply` | Implement the approved change |
| Archive | `/opsx:archive` | Fold the change into `openspec/` specs |

Daily commands (from `backend/` unless noted):

| Action | Command |
|---|---|
| DB up (repo root) | `docker compose up db -d` |
| API dev server | `uv run uvicorn app.main:app --reload` |
| Frontend dev (frontend/) | `npm run dev` |
| New migration | `uv run alembic revision --autogenerate -m "msg"` |
| Apply migrations | `uv run alembic upgrade head` |
| Tests / lint / format | `uv run pytest` · `uv run ruff check .` · `uv run ruff format .` |

Golden rules recap (full text in AGENTS.md): one brain; derived values
computed; timestamptz everywhere; schema changes only via new migrations;
secrets only in `.env`; uv not pip; Text+CHECK; OpenSpec before code; small
diffs with ruff+pytest after; ask when unsure.

## 8. Status & next

**Phase 0 is complete** (2026-07-20): schema applied (7 tables + pgvector),
user seeded, `/health` green from the SPA, LLM round-trip proven
(`scaffold llm ok`), pre-commit + CI + OpenSpec in place. Queued next, in
order (per AGENTS.md):

1. **Feature 1** — `core/llm.py` + `core/handler.handle_message` + auth
   (JWT cookie login) + web chat over SSE.
2. **Feature 2** — Telegram channel: long-poller, chat-id allowlist.
3. **Feature 3** — Day-end summary job → `generated_reviews` → Telegram.

Later phases: semantic memory over journals (embeddings + pgvector), habits,
investments.
