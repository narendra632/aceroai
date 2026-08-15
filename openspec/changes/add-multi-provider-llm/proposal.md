## Why

Two problems converge on the same fix.

**1. The assistant is blocked.** The Gemini Developer API bills from a **prepaid balance
sitting at ₹0** (₹1,000 minimum top-up), so every request is rejected with a `429` that
our UI misreports as a rate limit. Meanwhile a **~₹956/month Google Cloud credit** is
available but can *only* offset **Cloud Billing** — which is what **Agent Platform
(Vertex)** uses for the very same Gemini models.

**2. Narendra wants to choose his provider and model from the app** — Google *and*
OpenAI (he has a key) — switchable from a settings screen, not a redeploy.

The tempting shortcut was to point our existing `openai` SDK at Vertex's
OpenAI-compatible endpoint (one code path, both providers). **Research says no.** That
shim is officially **beta**, Google itself recommends the native API if you aren't
already committed to OpenAI libraries, it **silently ignores unsupported parameters**,
and — decisively — it **cannot round-trip Gemini 3's `thought_signature`**, which
**breaks multi-turn tool calls** ([openai/codex#7519](https://github.com/openai/codex/issues/7519)).
Our assistant's tool loop *is* multi-turn tool calling on Gemini 3.x models, so the shim
would quietly cap the capability of the feature we just shipped.

So we build the thing properly: **each provider through its own native SDK, behind one
internal interface.** Google's native SDK also reaches **Agent Platform with ADC**
(`GOOGLE_GENAI_USE_ENTERPRISE`), so we get the Cloud-Billing credit **and** full Gemini
capability — no trade.

## What Changes

- **Provider abstraction** (`core/providers/`): one internal interface —
  `stream_with_tools`, `complete`, `embed` — emitting the **same `("delta"|"tool_calls")`
  events the handler already consumes. The tool loop, memory, composer, and channels are
  **untouched**.
  - **`GoogleProvider`** — native **`google-genai`**, authenticated via **ADC** against
    **Agent Platform** (billing → Cloud Billing → the credit). Handles Gemini-native
    tool calling **including `thought_signature` round-tripping**, and native thinking
    config for our "think harder" mode.
  - **`OpenAIProvider`** — the **`openai`** SDK against OpenAI proper, using Narendra's
    key.
- **`core/llm.py` becomes a thin facade** that resolves the active provider per request
  and keeps today's retry/backoff behavior.
- **Per-user selection persisted** (migration `003`): `users` gains `llm_provider`,
  `model_chat`, `model_deep` (it already carries per-user config like `timezone`).
  Requests resolve **user preference → config default**. Because it lives in the one
  brain, **Telegram automatically honors the same choice**.
- **Settings API + UI**: `GET/PATCH /api/settings` and a **Settings screen** (a fourth
  nav entry) to pick provider and models for normal vs "think harder" chat. Only
  providers whose **credentials are actually configured** are offered — **API keys stay
  in `.env`, never entered or displayed in the UI**.
- **Honest provider errors**: a billing/quota rejection must stop masquerading as a
  rate limit (this exact confusion cost real debugging time today).
- **New dependency: `google-genai`** (Google's official SDK) — **ask Narendra before
  adding**. `openai` is already present.

## Capabilities

### New Capabilities
- `llm-provider`: the app talks to multiple model providers through one internal
  interface; each provider uses its native SDK so no provider's capability is degraded;
  the user selects provider and model from the app; embeddings stay pinned so stored
  memory remains valid; provider failures are reported honestly.

### Modified Capabilities
<!-- None. web-chat, memory, tasks, journal and assistant-tools keep their existing
     requirements — streaming, semantic recall and multi-turn tool calling must behave
     identically (or better) on every provider. That is verified, not re-specified. -->

## Impact

- **Backend:** new `core/providers/{base,google,openai_provider}.py`; `core/llm.py`
  reduced to a facade; `config.py` gains provider defaults + credentials presence;
  `core/handler.py` resolves the user's provider/model and maps errors honestly; new
  `api/settings.py`; `db/models.py` + **migration 003** (three nullable columns on
  `users`).
- **Frontend:** a **Settings** view (provider + model pickers, saved via the API) and a
  fourth nav entry; `lib/api.ts` gains settings methods.
- **⚠ Embeddings are pinned, deliberately:** cross-session memory vectors are only
  comparable if they come from one embedding model. Switching the **chat** provider MUST
  NOT switch the **embedding** provider/model, and `EMBED_DIM` stays **768** — otherwise
  every stored `profile_facts` vector becomes meaningless. Embeddings get their own
  fixed setting.
- **Infra:** enable the Agent Platform API on the `Aceroai` project; grant the VM's
  service account `roles/aiplatform.user`. Production authenticates via the **GCE
  metadata server — no key file, no new secret in `.env`**; locally
  `gcloud auth application-default login`.
- **Cost:** Gemini usage moves onto Cloud Billing (offset by the credit); OpenAI usage
  bills to Narendra's OpenAI account. Set a **budget alert** so credit exhaustion
  surfaces early instead of as errors.
- **Testing:** provider-interface conformance tests with fakes (no network in CI) —
  both providers must produce identical event streams; per-user resolution; settings API
  scoping; error mapping. Then a **live** check of streaming, **multi-turn** tool calls,
  and memory recall on each provider.

## Non-goals (this change)

- Per-message or per-session model overrides (selection is per user for now), automatic
  fallback/routing between providers, or streaming cost/usage dashboards.
- Provider-specific extras beyond current features (context caching, Google Search
  grounding, custom safety tuning) — the native SDKs make these *possible later*; none
  are wired up here.
- Entering API keys through the UI (deliberately rejected — keys stay in `.env`).
