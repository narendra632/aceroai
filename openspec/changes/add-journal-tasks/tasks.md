## 1. Service layer (single source of truth)

- [ ] 1.1 `services/tasks.py`: `create`, `list_for_user` (ordered by derived urgency), `get` (user-scoped), `update`, `complete`, `snooze`, `delete` — all take the authenticated user; validation + status-transition rules live here
- [ ] 1.2 `services/journal.py`: `add`, `list_for_user` (recent first, optional date range), `get`, `update`, `delete` — user-scoped; mood 1–5 validation; records `channel`
- [ ] 1.3 Derived-urgency helper (overdue > due-soon > priority; snoozed sinks until `snoozed_until`) — never stored; unit-covered

## 2. REST API (thin wrappers over the services)

- [ ] 2.1 `api/tasks.py`: `POST /api/tasks`, `GET /api/tasks`, `PATCH /api/tasks/{id}`, `POST /api/tasks/{id}/complete`, `DELETE /api/tasks/{id}` — all `Depends(get_current_user)`
- [ ] 2.2 `api/journal.py`: `POST /api/journal`, `GET /api/journal`, `PATCH /api/journal/{id}`, `DELETE /api/journal/{id}` — all auth-guarded
- [ ] 2.3 `api/schemas.py`: request/response models (TaskIn/Out, JournalIn/Out); register routers in `main.py`

## 3. Assistant tools + the tool-use loop (the one brain)

- [ ] 3.1 `core/tools.py`: tool definitions (name + description + JSON schema) for `create_task`, `list_tasks`, `update_task`, `complete_task`, `add_journal_entry`, `list_journal`; each closes over the user and calls the services (no `user_id` from the model)
- [ ] 3.2 `core/llm.py`: a tool-aware call path (pass `tools`/`tool_choice`; expose returned `tool_calls`) reusing the existing retry/backoff
- [ ] 3.3 `core/handler.py`: bounded loop in `handle_message` — give the model tools, stream normal text as today; on `tool_calls`, emit a `tool` ("working…") event, execute via `core/tools`, append tool results, loop up to `tools_max_iters`; then stream the final answer. Verify Gemini streams tool-calls; else non-streamed tool rounds + streamed final (design decision 3)
- [ ] 3.4 Guardrails: validate tool args (Pydantic); unknown/foreign id or service error → structured error back to the model; iteration cap enforced; per-user scoping asserted
- [ ] 3.5 Confirmation policy for destructive/bulk tools (delete / clear-many) — the assistant confirms before executing

## 4. Config & persona

- [ ] 4.1 `config.py`: `tools_max_iters` (default ~5) and any tool model/flag; `.env.example` note
- [ ] 4.2 `SOUL.md`: action policy — act on clear requests, offer on vague ones, confirm destructive/bulk; be concise about what it did

## 5. Frontend (mobile-first, great UX)

- [ ] 5.1 Nav shell: switch between **Chat / Tasks / Journal**; collapses cleanly on phones; keeps chat as default
- [ ] 5.2 `lib/api.ts`: task + journal client methods (auth header already handled)
- [ ] 5.3 Tasks view: list grouped/sorted by derived urgency, one-tap complete, quick-add, edit sheet (priority, due, notes, snooze); empty state
- [ ] 5.4 Journal view: dated timeline + composer (content, mood 1–5, tags); empty state
- [ ] 5.5 Chat: render the `tool`/"working…" state during a tool turn; keep streaming smooth for normal turns
- [ ] 5.6 Responsive + a11y pass: phone→desktop, tap targets ≥44px, no horizontal overflow, light/dark

## 6. Tests

- [ ] 6.1 Services: task CRUD + status transitions + urgency ordering + snooze; journal CRUD + mood validation; user-scoping (foreign id refused)
- [ ] 6.2 API: auth required; CRUD happy paths; cross-user access blocked
- [ ] 6.3 Tool loop (fake LLM emitting tool calls): create/list/complete a task and add/list journal end-to-end; bounded iterations; a malformed/failed tool call recovers; per-user scoping
- [ ] 6.4 `ruff format` + `ruff check` + `pytest` green (backend); CI stays green

## 7. Docs

- [ ] 7.1 `backend/README.md`: services + tools + the tool-use loop (how the assistant acts); new endpoints
- [ ] 7.2 `frontend/README.md`: the nav shell + Tasks/Journal pages
- [ ] 7.3 `docs/ARCHITECTURE.md` + `AGENTS.md`: record the assistant-tools capability and status; note PWA/push + semantic-journal as deferred follow-ups
