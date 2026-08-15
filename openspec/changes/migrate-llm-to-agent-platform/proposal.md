## Why

The app is currently blocked: the **Gemini Developer API** (AI Studio) is billed from a
**prepaid credit balance** that sits at ₹0, so every request is rejected with a `429`
that our UI misreports as a rate limit. Topping it up requires a **₹1,000 minimum**.

Meanwhile Narendra holds a **Google Cloud credit (~₹956/month, Developer Program
premium benefit)** that **cannot** be spent on the Developer API — it only offsets
**Google Cloud Billing**. **Vertex AI / Agent Platform serves the same Gemini models
but bills through Cloud Billing**, so moving the provider there makes that credit pay
for our LLM usage — likely covering this app's entire cost each month.

This is a **provider swap**, exactly what the architecture was built for: the code
keeps using the `openai` SDK, because Agent Platform exposes an
**OpenAI-compatible endpoint** that supports streaming *and* function-calling (which
the assistant's tool loop depends on).

## What Changes

- **Endpoint**: `llm_base_url` becomes the Agent Platform OpenAI-compatible URL,
  `https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/endpoints/openapi`
  (built from new `gcp_project` / `gcp_location` settings).
- **Auth becomes credential-based, not a static key.** Agent Platform takes a
  **short-lived OAuth access token** (≈1 h) in the OpenAI client's `api_key` field, via
  **Application Default Credentials (ADC)**. So `core/llm.py` gains a small token
  provider that fetches and **refreshes before expiry** — a long-running server cannot
  hold one token forever. **BREAKING for config** (not for behavior): a valid ADC
  identity replaces `LLM_API_KEY`.
  - **Production**: the backend already runs on a **GCE VM**, whose attached service
    account supplies ADC through the metadata server — **no key file, no new secret in
    `.env`**. It needs the `roles/aiplatform.user` role (and cloud-platform scope).
  - **Local dev**: `gcloud auth application-default login`.
- **Model IDs gain the `google/` prefix** (e.g. `google/gemini-2.5-flash`) — a config
  change in `.env`, not code.
- **Provider selection stays switchable**: an `llm_provider` setting (`agent_platform`
  | `developer_api`) keeps the old static-key path working, so we can fall back
  instantly if anything on the Vertex side misbehaves.
- **Fix the misleading error**: a billing/quota rejection must not read as
  "rate limit" — it should say the provider rejected the request (check billing/quota).
  This exact confusion cost real debugging time.
- **New dependency**: `google-auth` (Google's official credential library) — **ask
  Narendra before adding**.

## Capabilities

### New Capabilities
- `llm-provider`: how the app authenticates to and reaches the model provider —
  credential-based auth that refreshes automatically, a switchable provider, no static
  key required in production, and truthful provider-error reporting.

### Modified Capabilities
<!-- None. Chat, memory, tasks/journal and assistant-tools keep their existing
     requirements: streaming, semantic recall, and tool-calling must behave
     identically after the swap. That is verified, not re-specified. -->

## Impact

- **Code:** `core/llm.py` (token provider + per-request credential refresh; client
  construction), `config.py` (`llm_provider`, `gcp_project`, `gcp_location`),
  `core/handler.py` (error mapping wording). Everything above `llm.py` — the tool
  loop, memory, composer, channels — is untouched.
- **Config:** `.env.example` gains the Agent Platform block; prod `.env` drops
  `LLM_API_KEY` and sets project/location + `google/`-prefixed models.
- **Infra:** enable the Agent Platform (Vertex AI) API on the `Aceroai` project; grant
  the VM's service account `roles/aiplatform.user`; `gcloud auth
  application-default login` locally. Docs updated in `DEPLOY.md`.
- **Cost:** LLM usage moves onto Cloud Billing, offset by the ~₹956/mo credit.
  **Set a budget alert** so an exhausted credit surfaces early rather than as errors.
- **Testing:** unit tests for token refresh + base-URL/model construction + error
  mapping (all with fakes — no network in CI); then a **live smoke test** of streaming,
  the tool loop, and embeddings.
- **Risk to verify first:** whether **embeddings** (`gemini-embedding-001`, used by
  cross-session memory) are served over this same OpenAI-compatible endpoint. If not,
  embeddings need their own Vertex path or must stay on the Developer API — see design.

## Non-goals (this change)

- Migrating to Google's native `google-genai` SDK (we keep the `openai` SDK and our
  existing streaming/tool code).
- Multi-provider routing/fallback at runtime, or any change to prompts, memory,
  tasks/journal, or the UI.
