## Why

Phase 0 left the `core/` brain, the `api/` routes, and the real UI as empty
seats — today the app only serves `/health`. Feature 1 delivers the first
genuinely usable slice: Narendra logs in and holds a real, streaming
conversation that is persisted to Postgres. It is also the foundation every
later feature (Telegram, day-end reviews, memory) plugs into, so getting the
"one brain" boundary right now pays off across the whole roadmap.

## What Changes

- New LLM wrapper `core/llm.py`: a thin `AsyncOpenAI` client (base_url + key +
  model from settings) exposing a streaming `stream_chat` function.
- New context builder `core/composer.py`: assembles the model's input from
  `docs/SOUL.md` (persona) plus the recent messages of a session.
- New orchestrator `core/handler.py`: `handle_message(...)` — the single brain
  that persists the user message, builds context, streams the reply, and
  persists the assistant message. Channels/routes stay pure transport.
- New auth surface: `POST /api/auth/login` (JWT in an httpOnly cookie),
  `POST /api/auth/logout`, `GET /api/auth/me`, and a `get_current_user`
  dependency guarding protected routes.
- New chat surface: `POST /api/chat` streaming the reply over SSE,
  `GET /api/chat/sessions` (list past conversations), and
  `GET /api/chat/sessions/{id}/messages` (load history).
- New frontend: replace the scaffold health page with a Claude-inspired,
  mobile-responsive chat — login gate, session sidebar (off-canvas drawer on
  phones), streaming message list, composer.
- CI gains a `pgvector/pgvector:pg17` service so backend tests run against a
  real Postgres; `alembic upgrade head` runs before `pytest`.
- Living `backend/README.md` and `frontend/README.md` documenting file roles
  and how the pieces connect, cross-linking `docs/ARCHITECTURE.md`.
- No database schema change: the Phase 0 tables (`users`, `chat_sessions`,
  `messages`) already model everything Feature 1 needs.

## Capabilities

### New Capabilities
- `auth`: single-user email/password login issuing a JWT httpOnly cookie, a
  logout that clears it, a session-check endpoint, and a dependency that
  authorizes protected requests.
- `web-chat`: an authenticated, SSE-streamed chat that routes every message
  through the one-brain handler, persists user and assistant turns, and exposes
  session listing and history for a multi-conversation UI.

### Modified Capabilities
<!-- None — no existing spec-level behavior changes; openspec/specs/ is empty. -->

## Impact

- **Code:** fills `backend/app/core/{llm,composer,handler}.py`,
  `backend/app/api/{deps,auth,chat,schemas}.py`, wires routers in
  `backend/app/main.py`; rebuilds `frontend/src/**`.
- **Tests/CI:** new `backend/tests/{conftest,test_auth,test_chat}.py`; adds a
  Postgres service + migration step to `.github/workflows/ci.yml`.
- **Dependencies:** none new — `openai`, `pyjwt`, `bcrypt`, `sse-starlette`,
  `fastapi` are already installed.
- **Config/secrets:** unchanged; uses existing `.env` (`LLM_*`, `JWT_SECRET`,
  `FRONTEND_ORIGIN`). Cookie is `secure=False` for localhost dev.
- **Docs:** new per-folder READMEs; `docs/ARCHITECTURE.md` lifecycle §4a becomes
  live behavior.
