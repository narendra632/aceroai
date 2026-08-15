## Context

`core/llm.py` owns one lazily-built `AsyncOpenAI` and exposes `stream_chat`,
`stream_with_tools`, `complete`, `embed`. `handle_message` consumes
`stream_with_tools` as `("delta", text)` / `("tool_calls", [...])` events and runs the
bounded tool loop; `memory` calls `embed`. Everything above `llm.py` is already
provider-agnostic — **the seam we need exists**, it just has one hard-coded
implementation behind it.

Research (see proposal) rules out the OpenAI-compat shim for Gemini: beta status,
silently-dropped parameters, and no way to round-trip Gemini 3's `thought_signature`,
which breaks the multi-turn tool calls our assistant depends on.

## Goals / Non-Goals

**Goals:** native, uncompromised access to each provider; provider + model chosen by the
user from the app and honored on every channel; Gemini billed through Cloud Billing so
the credit applies; stored memory stays valid; zero behavioral regression in chat,
tools, or memory.

**Non-Goals:** per-message overrides, auto-failover between providers, provider-specific
extras (caching/grounding/safety tuning), API keys in the UI.

## Decisions

**1. A narrow provider interface, native SDK per implementation.**
`core/providers/base.py` defines the contract every provider satisfies:

```
stream_with_tools(messages, tools, model, reasoning_effort, usage) -> AsyncIterator[("delta", str) | ("tool_calls", list)]
complete(messages, model, reasoning_effort) -> str
embed(texts) -> list[list[float]]
```

The event shape is **exactly what `handle_message` already consumes**, so the handler,
tool loop, composer, memory, and channels change not at all. Each implementation
translates its SDK's native shapes into that contract. *Alternative rejected:* the
OpenAI-compat endpoint for both (one code path, but caps Gemini at beta-shim capability
and breaks multi-turn tools).

**2. `GoogleProvider` uses `google-genai` against Agent Platform via ADC.**
Configured with `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` /
`GOOGLE_GENAI_USE_ENTERPRISE=True`, so requests bill to **Cloud Billing** (the credit
applies) while using the **native** API surface. Two things this buys that the shim
cannot: **`thought_signature` is preserved across tool turns** (multi-turn tool calling
actually works on Gemini 3.x), and thinking/reasoning is configured natively rather than
through a lossy `reasoning_effort` mapping. **Credentials:** ADC — in production the
**GCE metadata server** supplies the VM's service-account identity (no key file, no
secret in `.env`, nothing to rotate — strictly better than today's static key); locally
`gcloud auth application-default login`. The SDK handles token refresh, so we do **not**
hand-roll a token provider. *Alternative rejected:* a mounted service-account JSON key —
reintroduces a long-lived on-disk secret; keep documented only for non-GCE hosting.

**3. `OpenAIProvider` keeps the `openai` SDK, pointed at OpenAI proper.**
Our existing streaming + tool-call accumulation logic moves here largely intact (it was
written against this SDK). Authenticated with `OPENAI_API_KEY` from `.env`.

**4. Selection is per-user data, resolved per request.**
Migration `003` adds nullable `llm_provider`, `model_chat`, `model_deep` to `users`
(which already stores per-user config like `timezone`) — no new table for three fields.
Resolution order is **user value → config default**, so an unset user behaves exactly as
today. `handle_message` resolves this once per turn and picks `model_deep` when the turn
is "think harder". Because it lives in the one brain, **Telegram honors the same
preference for free**. *Alternative rejected:* a separate `user_settings` table — extra
join and migration weight for three columns; revisit if settings grow.

**5. ⚠ Embeddings are pinned and never follow the chat provider.**
`profile_facts` vectors are only comparable when produced by **one** embedding model.
If switching chat provider also switched embeddings, every stored vector would silently
become meaningless and memory recall would return nonsense. So embeddings have their
**own fixed provider/model setting**, independent of the user's chat choice, and
`EMBED_DIM` stays **768** to match the existing column and HNSW index. Changing the
embedding model later is a **deliberate re-embed migration**, never a side effect of a
UI toggle. This constraint is called out in the spec so it can't be dropped by accident.

**6. Only credentialed providers are offered; keys never touch the UI.**
The settings endpoint reports which providers are *available* (their credentials are
configured server-side). The UI renders only those. Users pick a provider — they never
type, see, or store an API key in the app. Selecting an unavailable provider is rejected
by the API. Models come from a small **config-driven catalog** per provider (model names
churn; hard-coding them in the frontend would rot), with free-text allowed so a brand-new
model can be used before we update the list.

**7. Errors are reported by cause, not by status code.**
Google returns `429` for billing/quota exhaustion *and* for genuine rate limits; mapping
every `429` to "rate limit" is what sent us chasing a phantom limit today. The handler
distinguishes them and says which is which, still without leaking raw provider text.

## Risks / Trade-offs

- **Two code paths to keep correct.** That's the real cost of not degrading Gemini.
  Mitigated by **conformance tests**: one shared test suite both providers must pass,
  so their event streams are provably identical.
- **`google-genai` tool-call/stream shapes differ from OpenAI's** — the translation in
  `GoogleProvider` (especially accumulating streamed function calls and echoing
  `thought_signature` back) is the fiddliest part, and is exactly where a bug would
  surface as "the assistant stopped doing things". Covered by dedicated multi-turn tests
  plus a live check.
- **Reasoning/thinking semantics aren't identical across providers** — we map our
  low/high intent onto each provider's native control rather than pretending one knob
  fits both; behavior may differ subtly in depth (acceptable and documented).
- **Model availability drifts** (which `gemini-3.x` IDs exist, `global` vs regional
  location, which OpenAI models the key can access) — hence the config-driven catalog
  and a verification step before cutover.
- **Cost visibility splits** across two billing accounts; a budget alert covers the
  Google side, and OpenAI usage is Narendra's own key.
- **VM service-account permissions** may be missing/narrow by default — explicit runbook
  step, verified with a live call from inside the container.

## Migration Plan

Additive and reversible. Migration `003` adds three **nullable** columns — existing rows
keep working with config defaults, and the old behavior is the default until someone
changes a setting. Providers land behind the interface with tests before any production
change; then enable the API, grant the VM role, and deploy. **Rollback** = point the
default provider back and restart (or `git revert`); no data migration to undo, and
`profile_facts` is untouched because embeddings are pinned.

## Open Questions

- **Exact model IDs** available to this project (`gemini-3.5-flash` / `3.1-pro-preview`
  on Agent Platform) and **`global` vs a regional location** — verified in task 0.
- **Which OpenAI models** Narendra's key can access, for the catalog defaults.
- **Adding `google-genai`** — needs Narendra's OK per the project's dependency rule.
- **Embedding provider going forward:** keep `gemini-embedding-001` (768) as the pinned
  default — confirm it's reachable via Agent Platform, else keep embeddings on the
  Developer API until a deliberate re-embed.
