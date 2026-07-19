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
Phase 0 complete (2026-07-20). Next features in order:
1. Feature 1 — LLM wrapper + handle_message + auth + web chat (SSE)
2. Feature 2 — Telegram channel (long-poll, chat-id allowlist)
3. Feature 3 — Day-end summary job → generated_reviews → Telegram

Architecture reference: docs/ARCHITECTURE.md