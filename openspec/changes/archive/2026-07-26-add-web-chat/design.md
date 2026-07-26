## Context

Phase 0 shipped the schema, config, `core/security.py`, and a health-check SPA.
The `core/` brain, `api/` routes, and real UI are empty. The stack is
deliberately **sync** SQLAlchemy 2.0 (typed `Mapped[]`), Postgres 17 + pgvector,
FastAPI, the `openai` SDK pointed at Gemini's OpenAI-compatible endpoint, React
19 + Tailwind v4. Single user. Golden rules that bind this design: one brain
(rule 1), timestamptz everywhere (rule 3), secrets only in `.env` (rule 5),
small diffs with ruff+pytest (rule 9).

## Goals / Non-Goals

**Goals:**
- Log in and hold a real, streaming, persisted conversation end to end.
- Establish the one-brain boundary so Feature 2 (Telegram) is a thin adapter.
- A Claude-inspired, mobile-responsive UI that is product-ready, not a demo.
- Keep tests hermetic (no real LLM calls) and CI green.

**Non-Goals:**
- Profile facts, tasks, or journal context in the prompt (own features later).
- Semantic memory / embeddings (Phase 2).
- Multi-user, registration, password reset (single-user app; user is seeded).
- Message editing, regeneration, streaming cancellation UI (later polish).

## Decisions

**1. Async route + AsyncOpenAI, sync DB via threadpool.**
The chat endpoint must stream, so it is `async` and uses `AsyncOpenAI`. The DB
stays sync (rule/stack constraint). The DB is touched only *before* the stream
(persist user message, ensure session) and *after* it (persist assistant
message); those calls run inside `fastapi.concurrency.run_in_threadpool` so the
event loop is never blocked, and never mid-stream. *Alternative rejected:* going
fully async SQLAlchemy — contradicts the chosen stack and rewrites the DB layer
for no single-user benefit.

**2. Browser consumes the stream with `fetch`, not `EventSource`.**
`/api/chat` is a POST carrying the message body and the auth cookie.
`EventSource` is GET-only and cannot send a body, so the frontend uses
`fetch(..., {credentials:"include"})` and reads `response.body` via a reader,
parsing SSE frames client-side. The server still formats frames with
`sse-starlette` `EventSourceResponse`. *Alternative rejected:* GET + query
params + `EventSource` — leaks the message into the URL/logs and fights caching.

**3. JWT in an httpOnly cookie.**
Login verifies with `core/security.verify_password`, mints a token with
`create_access_token`, and sets it as an httpOnly, `samesite=lax` cookie
(`secure=False` for localhost). A `get_current_user` dependency decodes it and
loads the user. httpOnly keeps the token out of JS (XSS-resistant); the existing
CORS config already allows credentials from the SPA origin. *Alternative
rejected:* bearer token in `localStorage` — readable by any injected script.

**4. The handler yields; routes are transport.**
`handle_message(db, user, text, channel, session_id)` is an async generator that
yields text deltas. The route wraps those yields into SSE events and nothing
more. This is the physical enforcement of "one brain": Telegram will call the
same generator.

**5. Composer minimal but shaped for growth.**
`build_context` returns OpenAI-format messages: SOUL.md as system, then the last
~20 session messages. Later features add facts/tasks by extending this one
function — routes never change.

**6. Swappable LLM for hermetic tests.**
`stream_chat` is a module-level async function; tests monkeypatch it with a fake
async generator. Combined with a real Postgres test DB, this exercises the full
handler/persistence path without network or cost.

**7. CI gets a Postgres service.**
Models use Postgres-only types (ARRAY, Uuid, CHECK constraints), so SQLite can't
stand in. The CI backend job runs a `pgvector/pgvector:pg17` service, sets
`DATABASE_URL` to it, runs `alembic upgrade head`, then `pytest`.

**8. UI architecture.**
`lib/api.ts` centralizes all fetches (`credentials:"include"`), including a
`streamChat` async iterator. Components: `LoginScreen`, `ChatLayout`, `Sidebar`,
`MessageList`/`MessageBubble`, `Composer`. `App.tsx` is the auth gate. Mobile:
the sidebar is an off-canvas drawer under `md`, docked at/above `md`; ≥44px tap
targets; no horizontal overflow; composer fixed above the keyboard.

## Risks / Trade-offs

- **Gemini omits streamed token usage** → record `null` for token counts; don't
  block the flow on it.
- **`gemini-3.5-flash` is a thinking model** → set a sane `max_tokens` in the
  real chat call (as done in `verify_llm`) so replies aren't eaten by reasoning
  budget.
- **Sync DB in an async app** → confine every DB call to `run_in_threadpool`;
  code review guards against a stray direct call blocking the loop.
- **SSE buffering by proxies** → dev is direct (Vite → uvicorn), so not a
  concern now; note it for later deployment behind a proxy.
- **Two review gates** (Claude Code plan approval + this OpenSpec review) → by
  design; the user chose the spec-first workflow.

## Migration Plan

No DB migration — schema is sufficient. Deploy is additive (new files + router
includes). Rollback = revert the change branch; no data migration to undo. CI
change is isolated to the workflow file.

## Open Questions

- Session title: derive silently from the first message (chosen default) vs. an
  LLM-generated title later — deferred, cheap to add.
- Dark mode: ship `prefers-color-scheme` now; an explicit toggle can come later.
