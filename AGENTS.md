# AGENTS.md — mylife-agent

## What this is
A single-user personal AI assistant (chat + journaling + tasks + scheduled
reviews, later: memory, habits, investments). Web frontend + Telegram bot,
one FastAPI backend. Long-term evolving project — optimize for clarity and
incremental change.

## Stack
- Backend: FastAPI, **sync** SQLAlchemy 2.0 (typed `Mapped[]` style),
  Postgres 17 + pgvector, Alembic, APScheduler, openai SDK with base_url swap (Gemini default, OpenAI swappable), sse-starlette.
- Frontend: React + Vite + Tailwind v4 (shadcn/ui later).
- Tooling: uv, ruff, pytest, pre-commit, OpenSpec, Docker Compose.

## Golden rules
1. **One brain.** All conversational logic flows through
   `core/handler.handle_message()`. Channels (web SSE route, Telegram
   poller) are thin adapters. Never put chat logic in a channel file.
2. **Derived values are computed, never stored.** Task urgency is derived
   from `due_at` + `priority` at read time.
3. **Time is sacred.** All DB timestamps are `DateTime(timezone=True)`.
   Render user-facing times in `users.timezone`.
4. Schema changes only via Alembic migrations. Never edit an applied
   migration; write a new one.
5. Secrets live only in `.env`. Never hardcode keys. gitleaks runs
   pre-commit.
6. Dependencies via `uv add` only — never pip. Run things with `uv run`.
7. Prefer `Text` + CHECK constraints over Postgres enums.
8. Every non-trivial feature starts as an OpenSpec proposal
   (`/opsx:propose`) that gets reviewed before code is written.
9. Small diffs. After edits run `uv run ruff format .` and `uv run pytest`
   from `backend/`.
10. When unsure about a product decision, ask — don't assume.

## Commands (run from backend/ unless noted)
- DB up (from root):        docker compose up db -d
- API dev server:           uv run uvicorn app.main:app --reload
- New migration:            uv run alembic revision --autogenerate -m "msg"
- Apply migrations:         uv run alembic upgrade head
- Tests:                    uv run pytest
- Lint + format:            uv run ruff check . && uv run ruff format .

## Layout
- backend/app/core/     llm.py, composer.py (context
                        builder), handler.py (the one brain), security.py
- backend/app/api/      HTTP routes (auth, chat SSE, tasks, journal)
- backend/app/channels/ telegram.py long-poller
- backend/app/jobs/     scheduler + review jobs
- backend/app/db/       models.py, session.py
- frontend/             Vite SPA
- docs/SOUL.md          assistant persona (read by composer)
- openspec/             specs (source of truth) + changes

## Current status
Features 1 & 2, cross-session memory & adaptive reasoning, and hosting are complete.
Feature 1 (2026-07-26): LLM wrapper + one-brain handle_message + JWT-cookie auth +
SSE web chat, multi-session React + shadcn/ui UI. Feature 2 (2026-07-28): thin
channels/telegram.py long-poller routed through the same handle_message (allowlist
via users.telegram_chat_id, /start linking). Memory & reasoning (2026-07-31):
durable facts extracted, embedded (pgvector/HNSW, migration 002), and semantically
recalled into context; adaptive reasoning (per-request effort: web "think harder"
toggle + Telegram /think + a task-routing hook); plus retry/backoff, error
hygiene, and an input cap. Specs archived under
openspec/specs/{auth,web-chat,telegram,memory}.

Hosting (2026-08-03): backend live on a Google Cloud always-free e2-micro
(Docker: Caddy auto-HTTPS + api + Postgres/pgvector, DuckDNS), frontend on Vercel;
CI/CD auto-deploys on push to main (tests → build image → GHCR → SSH pull on the
VM). Cross-site cookie was blocked by browser privacy protections, so auth uses a
Bearer token in localStorage (Authorization header). See docs/DEPLOY.md.

Roadmap in docs/ROADMAP.md. Next up (agreed): the UI feature set (journal/tasks,
investments, knowledge visualization), then MCP-powered capabilities. (The day-end
summary job can land now that hosting is live.)

Architecture reference: docs/ARCHITECTURE.md