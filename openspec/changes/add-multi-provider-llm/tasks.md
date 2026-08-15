## 0. Verify before building (de-risk first — no production code yet)

- [ ] 0.1 Enable the **Agent Platform / Vertex AI API** on the `Aceroai` project; confirm the ~₹956 Cloud credit is active on its billing account
- [ ] 0.2 Locally: `gcloud auth application-default login`; confirm ADC resolves
- [ ] 0.3 Get Narendra's OK to add **`google-genai`**; then `uv add google-genai`
- [ ] 0.4 **Spike (throwaway, not committed):** via `google-genai` + ADC + `GOOGLE_GENAI_USE_ENTERPRISE`, confirm (a) streaming, (b) **multi-turn** tool calling with `thought_signature` round-trip, (c) embeddings (`gemini-embedding-001`, 768), (d) which `gemini-3.x` model IDs exist, (e) `global` vs regional location, (f) native thinking/reasoning control
- [ ] 0.5 Confirm which **OpenAI** models Narendra's key can access (catalog defaults)
- [ ] 0.6 Record findings in `design.md` (resolves Open Questions); if embeddings aren't served on Agent Platform, pin them to the Developer API and note the deliberate re-embed path

## 1. Provider interface

- [ ] 1.1 `core/providers/base.py`: the contract — `stream_with_tools` yielding `("delta", str) | ("tool_calls", list)`, plus `complete` and `embed`; documented so a new provider can be added without touching callers
- [ ] 1.2 Shared retry/backoff + a provider-agnostic error taxonomy (transient · rate-limit · billing/quota · other)
- [ ] 1.3 `core/llm.py` reduced to a facade: resolve the provider, keep today's public functions working

## 2. GoogleProvider (native `google-genai`)

- [ ] 2.1 Client via **ADC** + `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` / `GOOGLE_GENAI_USE_ENTERPRISE` (Agent Platform → Cloud Billing); no hand-rolled token refresh (the SDK owns it)
- [ ] 2.2 Translate our message list (incl. `system`, `tool` results) into Gemini `contents` + tool declarations
- [ ] 2.3 Streaming → `("delta", …)`; accumulate streamed function calls → `("tool_calls", …)`
- [ ] 2.4 **`thought_signature` round-trip** so multi-turn tool calls work on Gemini 3.x *(the reason we're going native)*
- [ ] 2.5 Map reasoning intent (chat vs "think harder") onto native thinking config
- [ ] 2.6 `embed` via the native embeddings API at **768 dims**

## 3. OpenAIProvider (native `openai`)

- [ ] 3.1 Move today's `openai`-SDK streaming + tool-call accumulation behind the interface, pointed at OpenAI proper (`OPENAI_API_KEY`)
- [ ] 3.2 Map reasoning intent to OpenAI's control; `complete` + `embed` implemented
- [ ] 3.3 Verify identical event shapes vs GoogleProvider (see conformance tests)

## 4. Per-user selection

- [ ] 4.1 `db/models.py` + **migration 003**: nullable `llm_provider`, `model_chat`, `model_deep` on `users`
- [ ] 4.2 `config.py`: default provider + models, **pinned embedding provider/model (`EMBED_DIM` stays 768)**, credential presence per provider, model catalog
- [ ] 4.3 Resolution helper: user value → config default; `handle_message` resolves once per turn and uses `model_deep` for "think harder"
- [ ] 4.4 Confirm Telegram inherits the preference with **no channel changes** (one brain)

## 5. Settings API

- [ ] 5.1 `api/settings.py`: `GET /api/settings` (current selection + **available** providers + model catalog) and `PATCH /api/settings`, auth-guarded and user-scoped
- [ ] 5.2 Reject selecting an unavailable/unknown provider; **never expose or accept API keys**
- [ ] 5.3 Schemas + router registration

## 6. Honest errors

- [ ] 6.1 Map the error taxonomy to user-facing text: rate limit vs **billing/quota** vs generic; no raw provider text to the client (full detail logged)

## 7. Frontend — Settings view

- [ ] 7.1 `lib/api.ts`: `getSettings` / `updateSettings` types + calls
- [ ] 7.2 **Settings** view: provider picker (available only), model pickers for chat and "think harder", save + saved-state feedback, error handling
- [ ] 7.3 Fourth nav entry in the sidebar (Chat / Tasks / Journal / Settings); mobile-first, matches the existing design system
- [ ] 7.4 Show the active provider/model subtly where it aids trust (e.g. in Settings), without cluttering chat
- [ ] 7.5 **Memory/embedding section (read-only)**: show the pinned embedding model + dimension, with a short plain-English note that it is fixed *on purpose* — changing it makes every stored memory unreadable, so it would require re-embedding all stored facts in one deliberate migration. Present as informational, **not** a picker

## 8. Tests (no network in CI)

- [ ] 8.1 **Conformance suite both providers must pass** with fakes: text streaming, single tool call, **multi-turn** tool calls, malformed args, `complete`, `embed` — identical event shapes
- [ ] 8.2 `thought_signature` is carried back on the Google path (fake asserts the round-trip)
- [ ] 8.3 Resolution: user preference wins; unset falls back to defaults; "think harder" picks `model_deep`
- [ ] 8.4 Settings API: auth required, user-scoped, unavailable provider rejected, no key ever returned
- [ ] 8.5 **Embedding pinning**: switching chat provider does not change the embedding model/dimension
- [ ] 8.6 Error mapping: rate-limit vs billing/quota wording; no raw provider text
- [ ] 8.7 Full suite + `ruff format` + `ruff check` green; CI green

## 9. Live verification (each provider)

- [ ] 9.1 Normal chat streams smoothly; no first-token latency regression
- [ ] 9.2 **Tool loop end-to-end**: "add a task to pay rent Friday" → appears in Tasks; "what's on my list?" reads real tasks; journal add/read *(also completes the live tool-loop check deferred from the tasks/journal change)*
- [ ] 9.3 **Memory**: a fact learned in one session is recalled in another (embeddings path intact)
- [ ] 9.4 Switch provider in Settings → next reply comes from the new provider; Telegram honors it too
- [ ] 9.5 Confirm Gemini usage appears under **Cloud Billing** and draws down the credit

## 10. Production cutover

- [ ] 10.1 Grant the VM's service account `roles/aiplatform.user`; verify ADC **from inside the container** on the VM
- [ ] 10.2 Prod `.env`: project/location/provider defaults (+ `OPENAI_API_KEY` if OpenAI is to be available) — **Narendra edits it; never touched by the assistant**
- [ ] 10.3 Deploy via push to `main`; verify `/health`, a real chat, a tool action, and Telegram
- [ ] 10.4 **Budget alert** on the billing account so credit exhaustion surfaces early
- [ ] 10.5 Document rollback (restore default provider + restart)

## 10b. Context awareness + duplicate prevention (folded in)

- [x] 10b.1 `composer`: inject the user's open tasks (ids, due/overdue, priority) into every turn, capped by `context_tasks_limit`; state explicitly when there are none
- [x] 10b.2 `handler`: pass the user through to `build_context` so awareness works on every channel
- [x] 10b.3 `services/tasks`: `find_duplicate` (case/punctuation-insensitive) + `create_task` refuses an equivalent **open** task, raising `Duplicate` with the existing row; `allow_duplicate` escape hatch
- [x] 10b.4 `core/tools`: return the existing task in the tool result so the assistant can point at it; `main.py` maps `Duplicate` → **409**
- [x] 10b.5 `SOUL.md`: use the visible list, never duplicate, act by id, surface due/overdue work
- [x] 10b.6 Tests (15): context contents, capping, per-user isolation, overdue flag, completed excluded; duplicate refused/allowed/forced, API 409, tool reports existing
- [x] 10b.7 Live-verified: "add pay rent" → *"You already have that…"* (no tool call); "hi" → proactively lists what's due tomorrow; "mark rent done" → single `complete_task`

## 11. Docs

- [ ] 11.1 `backend/README.md`: the provider interface, how to add a provider, ADC (local vs GCE metadata), per-user selection, embedding pinning
- [ ] 11.2 `frontend/README.md`: the Settings view
- [ ] 11.3 `docs/DEPLOY.md`: enable the API, grant the role, env vars, budget alert, rollback
- [ ] 11.4 `docs/ARCHITECTURE.md` + `AGENTS.md`: the `llm-provider` capability, why native SDKs over the compat shim, and the billing rationale
