## 1. Backend core (the brain)

- [ ] 1.1 `core/llm.py`: module-level `AsyncOpenAI` from settings; `async def stream_chat(messages, model=None, max_tokens=...) -> AsyncIterator[str]` yielding content deltas, requesting `stream_options={"include_usage": True}` and exposing usage when present
- [ ] 1.2 `core/composer.py`: `build_context(db, session_id) -> list[dict]` reading `docs/SOUL.md` (path resolved from repo root) as system message + last ~20 session messages in order
- [ ] 1.3 `core/handler.py`: `async def handle_message(db, user, text, channel, session_id)` async generator — ensure/create session (title from first message), persist user message, build context, stream reply while accumulating, persist assistant message (model + token counts) and bump `last_active_at`; all DB calls via `run_in_threadpool`

## 2. Backend API

- [ ] 2.1 `api/schemas.py`: `LoginIn`, `MessageIn`, `SessionOut`, `MessageOut`
- [ ] 2.2 `api/deps.py`: `get_current_user(request, db=Depends(get_db)) -> User` reading/decoding the cookie, 401 on missing/invalid
- [ ] 2.3 `api/auth.py`: `POST /api/auth/login` (verify, set httpOnly cookie / 401), `POST /api/auth/logout` (clear cookie), `GET /api/auth/me`
- [ ] 2.4 `api/chat.py`: `POST /api/chat` (`EventSourceResponse` of `session`/`delta`/`done`/`error` events via the handler), `GET /api/chat/sessions`, `GET /api/chat/sessions/{id}/messages` (ownership-checked, 404 otherwise)
- [ ] 2.5 `main.py`: include the auth and chat routers under `/api`

## 3. Backend tests + CI

- [ ] 3.1 `tests/conftest.py`: test DB session fixture + fixture that monkeypatches `stream_chat` with a fake async generator + a logged-in TestClient
- [ ] 3.2 `tests/test_auth.py`: login success/wrong-password/unknown-email; protected route 401 without cookie; `me` and `logout`
- [ ] 3.3 `tests/test_chat.py`: chat persists user+assistant rows; SSE frames shaped right; session list + history; cross-user 404
- [ ] 3.4 `.github/workflows/ci.yml`: add `pgvector/pgvector:pg17` service, set `DATABASE_URL`, run `alembic upgrade head` before `pytest`

## 4. Frontend

- [ ] 4.1 `index.css`: Claude-inspired Tailwind v4 `@theme` (warm paper bg, clay accent, dark via `prefers-color-scheme`)
- [ ] 4.2 `lib/api.ts`: `login`/`logout`/`me`/`listSessions`/`getMessages` + `streamChat` (fetch reader SSE parser), all `credentials:"include"`
- [ ] 4.3 `components/LoginScreen.tsx`: centered card, email+password, error state
- [ ] 4.4 `components/{ChatLayout,Sidebar}.tsx`: sidebar with session list + active highlight + "New chat"; off-canvas drawer under `md`, docked at/above `md`
- [ ] 4.5 `components/{MessageList,MessageBubble,Composer}.tsx`: streaming message list (user right / assistant full-width), streaming cursor, auto-scroll; auto-grow composer with send; ≥44px tap targets
- [ ] 4.6 `App.tsx`: auth gate (LoginScreen vs ChatLayout) holding session/messages/streaming state; remove scaffold health page + unused template assets

## 5. Docs + verification

- [ ] 5.1 `backend/README.md`: overview, run commands, file-by-file table, request→brain→LLM→DB flow, env vars; cross-link `docs/ARCHITECTURE.md`
- [ ] 5.2 `frontend/README.md`: replace Vite template — overview, `npm run dev`, file-by-file table, streaming + cookie-auth explanation, theme notes, `VITE_API_URL`
- [ ] 5.3 Backend verify: `uv run ruff check .` + `uv run ruff format .` + `uv run pytest` green; manual `curl` login + SSE chat against a running server
- [ ] 5.4 Frontend/full-pipe verify: `npm run dev`, log in, stream a reply from Gemini, reload for persisted history, switch sessions, logout; check responsive at ~375px and desktop
- [ ] 5.5 Commit per logical chunk; push; confirm CI green; `/opsx:archive` the change
