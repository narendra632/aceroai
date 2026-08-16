# AGENTS.md — mylife-agent

## What this is
A single-user personal AI assistant (chat + journaling + tasks + scheduled
reviews, later: memory, habits, investments). Web frontend + Telegram bot,
one FastAPI backend. Long-term evolving project — optimize for clarity and
incremental change.

## Stack
- Backend: FastAPI, **sync** SQLAlchemy 2.0 (typed `Mapped[]` style),
  Postgres 17 + pgvector, Alembic, sse-starlette. Models are reached through
  `core/providers/`, each on its **native** SDK — `google-genai` (Agent Platform
  via ADC) and `openai`. APScheduler is a dependency but no job exists yet.
- Frontend: React 19 + Vite + Tailwind v4 + shadcn/ui (Radix) + lucide icons.
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
11. **Docs and diagrams are updated by the change that alters the behavior**,
    never afterwards. Every OpenSpec `tasks.md` ends with that item, checked
    like tests. `ARCHITECTURE.md` describes only what is built; anything
    planned goes in `ROADMAP.md`. Never annotate a doc `(planned — Feature N)`:
    each one becomes a lie on ship, and nothing forces a revisit.
12. **No shortcuts on UI/UX.** The bar is a finished product, not "it works" —
    no raw native controls where a themed one is needed, no destructive action
    without confirmation, no silent success. Known gaps: `docs/UI-AUDIT.md`.

## Commands (run from backend/ unless noted)
- DB up (from root):        docker compose up db -d
- API dev server:           uv run uvicorn app.main:app --reload
- New migration:            uv run alembic revision --autogenerate -m "msg"
- Apply migrations:         uv run alembic upgrade head
- Tests:                    uv run pytest
- Lint + format:            uv run ruff check . && uv run ruff format .

## Layout
- backend/app/core/     handler.py (the one brain), composer.py (context builder),
                        llm.py (provider facade), tools.py (assistant tools),
                        memory.py (extract/embed/recall), telemetry.py, security.py
- backend/app/core/providers/  base.py (contract + error taxonomy),
                        google.py (native google-genai), openai_provider.py
- backend/app/services/ tasks.py, journal.py, user_settings.py, errors.py —
                        the single source of truth for the API *and* the tools
- backend/app/api/      HTTP routes (auth, chat SSE, tasks, journal, settings)
- backend/app/channels/ telegram.py long-poller
- backend/app/jobs/     empty package — no scheduled job built yet
- backend/app/db/       models.py (7 tables), session.py
- frontend/src/         Vite SPA — components/ (14), hooks/, lib/api.ts
- docs/SOUL.md          assistant persona (read by composer every turn)
- openspec/             specs (source of truth) + changes

## Current status

**Built and live:** web chat (SSE) · Telegram channel · cross-session memory
(pgvector/HNSW) · adaptive reasoning · tasks + journal with assistant tool-use ·
multi-provider LLM + Settings · hosting with auto-deploy on push to `main`.

**Not built yet:** anything in `app/jobs/` (no scheduled job), PWA/push, journal
semantic search, database backups.

Status detail and what comes next live in **`docs/ROADMAP.md`** — the one place
that owns it. Do not restate progress here; this file owns *conventions*.

## Key references
- **`docs/ARCHITECTURE.md`** — how the system works (diagrams, data model, config)
- **`docs/ROADMAP.md`** — what is done, what is next, standing risks
- **`docs/REQUEST-ANATOMY.md`** — measured latency and token cost per turn
- **`docs/DEPLOY.md`** — production runbook
- **`docs/UI-AUDIT.md`** — known UI/UX gaps and the standard being applied
- **`openspec/specs/`** — capability specs (source of truth for behavior)