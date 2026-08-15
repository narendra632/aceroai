## 0. Verify before building (de-risk first)

- [ ] 0.1 Enable the **Agent Platform / Vertex AI API** on the `Aceroai` project; confirm the ~₹956 Cloud credit is active on its billing account
- [ ] 0.2 Locally: `gcloud auth application-default login`; confirm ADC works
- [ ] 0.3 **Spike (throwaway script, not committed):** call the OpenAI-compat endpoint with an ADC token — confirm (a) chat **streaming**, (b) **tool/function calling**, (c) **embeddings** (`/embeddings` + `dimensions=768`), (d) which `google/…` model IDs exist, (e) `global` vs regional location, (f) whether `reasoning_effort` is accepted
- [ ] 0.4 Record the findings in `design.md` (resolves the Open Questions); if embeddings are unsupported, pick fallback (b) or (c) from the design **before** writing code
- [ ] 0.5 Get Narendra's OK to add **`google-auth`**; then `uv add google-auth`

## 1. Config

- [ ] 1.1 `config.py`: `llm_provider` (`agent_platform` | `developer_api`), `gcp_project`, `gcp_location`; keep `llm_api_key` for the fallback path
- [ ] 1.2 Derive the Agent Platform `base_url` from project/location (single helper, unit-tested — no hand-typed URLs in `.env`)
- [ ] 1.3 `.env.example`: Agent Platform block (provider, project, location, `google/`-prefixed models) + a note that ADC replaces `LLM_API_KEY` in prod

## 2. Credentials & client (`core/llm.py`)

- [ ] 2.1 Token provider: `google.auth.default(scopes=[cloud-platform])`, refresh when expired or within the ~5-min skew window; run the blocking refresh off the event loop; guard with a lock so concurrent requests don't stampede
- [ ] 2.2 Apply the current token to the client per request (keep one client for connection pooling); static-key path unchanged when `llm_provider=developer_api`
- [ ] 2.3 `stream_chat` / `stream_with_tools` / `complete` / `embed` work unchanged through the new auth — no signature changes
- [ ] 2.4 Embeddings per the 0.3 finding: prefixed model on the same endpoint, or the chosen fallback path — **do not change `EMBED_DIM` (768)**, so stored `profile_facts` vectors stay valid

## 3. Honest provider errors

- [ ] 3.1 `core/handler._user_error`: distinguish a genuine rate limit from a billing/quota rejection; never leak raw provider text (full detail still logged)

## 4. Tests (no network in CI)

- [ ] 4.1 Token provider: refreshes when expired / near expiry; reuses a valid token; concurrent calls refresh once
- [ ] 4.2 Base-URL + model-id construction for both providers (prefix applied only for Agent Platform)
- [ ] 4.3 Error mapping: rate-limit vs billing/quota wording; no raw provider text in the user message
- [ ] 4.4 Existing suite stays green (`ruff format` + `ruff check` + `pytest`); CI green

## 5. Local end-to-end verification

- [ ] 5.1 Normal chat **streams** smoothly (no regression in first-token latency)
- [ ] 5.2 **Tool loop**: "add a task to pay rent Friday" creates it; "what's on my list?" reads real tasks; journal add/read — on the real provider *(this also completes the live tool-loop check deferred from the tasks/journal change)*
- [ ] 5.3 **Memory**: a fact is recalled across sessions (embeddings path works end-to-end)
- [ ] 5.4 Confirm usage/charges appear under **Cloud Billing** and draw down the credit

## 6. Production cutover

- [ ] 6.1 Grant the VM's service account `roles/aiplatform.user` (+ cloud-platform scope); verify ADC from inside the container on the VM
- [ ] 6.2 Update the prod `.env` (provider, project, location, prefixed models; `LLM_API_KEY` no longer needed) — Narendra edits it; never touched by the assistant
- [ ] 6.3 Deploy (push to `main` → CI/CD); verify `/health`, then a real chat + a tool action + Telegram
- [ ] 6.4 Set a **budget alert** on the billing account so credit exhaustion is visible early
- [ ] 6.5 Confirm rollback works: `LLM_PROVIDER=developer_api` + restart (document it)

## 7. Docs

- [ ] 7.1 `backend/README.md`: provider config + ADC (local vs GCE metadata), model prefix, rollback switch
- [ ] 7.2 `docs/DEPLOY.md`: enable the API, grant the role, prod env vars, budget alert
- [ ] 7.3 `docs/ARCHITECTURE.md` + `AGENTS.md`: record the `llm-provider` capability and the billing rationale
