## Context

`core/llm.py` builds one module-level `AsyncOpenAI(base_url=settings.llm_base_url,
api_key=settings.llm_api_key)` lazily and reuses it for `stream_chat`,
`stream_with_tools`, `complete`, and `embed`. That works because the Gemini Developer
API uses a **static** key. Agent Platform instead authenticates with a **short-lived
OAuth access token** (~1 hour) obtained from **Application Default Credentials**, so a
process that runs for days cannot hold one token for its lifetime. Everything above
`llm.py` (composer, memory, the tool loop, channels) is provider-agnostic and must not
change.

## Goals / Non-Goals

**Goals:** move LLM billing onto Google Cloud Billing (so the monthly credit pays for
it); keep the `openai` SDK and today's streaming + tool-calling behavior byte-for-byte;
require **no static secret in production**; make provider errors honest; keep an
instant fallback to the old provider.

**Non-Goals:** the native `google-genai` SDK, runtime multi-provider routing, or any
prompt/feature change.

## Decisions

**1. Keep the `openai` SDK against Agent Platform's OpenAI-compatible endpoint.**
Confirmed shape:
```python
base_url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/endpoints/openapi"
client   = openai.OpenAI(base_url=base_url, api_key=credentials.token)  # token, not a key
model    = "google/gemini-2.5-flash"                                    # google/ prefix required
```
Streaming and function-calling are supported here, so `stream_with_tools` and the whole
tool loop carry over unchanged. *Alternative rejected:* rewriting on `google-genai` —
it would mean re-implementing our streaming + tool-call accumulation for no gain.

**2. A `_token_provider()` that refreshes before expiry; the client is built per
credential, not once forever.**
`google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])` gives
a credentials object; we refresh it when `credentials.expired` or when expiry is within
a small **skew window (~5 min)**, then use `credentials.token`. Because the `openai`
client stores `api_key` at construction, we set the client's key from the current token
on each call (cheap, in-process) — a long-lived server therefore never sends a stale
token. Refresh is guarded so concurrent requests don't stampede.
*Alternative rejected:* rebuilding the whole `AsyncOpenAI` per request (wasteful — it
would drop connection pooling).

**3. ADC everywhere — no key file, no new secret.**
Production runs on a **GCE VM**, where ADC resolves through the **metadata server**
using the VM's attached service account: no credential file to ship, nothing new in
`.env`, nothing to rotate. It needs `roles/aiplatform.user` and the cloud-platform
scope. Locally, `gcloud auth application-default login` provides the same interface.
This is strictly *better* security than the static key we have today.
*Alternative rejected:* a service-account **JSON key file** mounted into the container —
portable, but it reintroduces a long-lived secret on disk; keep it documented only as a
fallback for non-GCE hosting.

**4. `llm_provider` switch (`agent_platform` | `developer_api`), default kept
switchable.**
One setting picks credential-based auth + prefixed models, or the old static-key path.
This is the escape hatch: if anything on Vertex misbehaves in production, flipping one
env var and restarting restores the previous provider without a code change or
redeploy of new images.

**5. Provider errors must be reported honestly.**
Today any `429` maps to "I've hit the model's rate limit". Google returns `429` for
**billing/quota exhaustion** too, which sent us chasing a non-existent rate limit. New
wording distinguishes a genuine rate limit from a provider rejection that needs
billing/quota attention, without leaking provider internals to the client.

## Risks / Trade-offs

- **⚠ Embeddings are the biggest unknown.** Cross-session memory calls
  `client.embeddings.create(model=settings.embed_model, dimensions=768)`. Whether the
  `endpoints/openapi` surface serves `/embeddings` (and honors `dimensions`) must be
  **verified before we cut over**. Mitigation, in order: (a) if supported, prefix the
  model and continue; (b) if not, call Vertex's native embeddings endpoint for `embed`
  only; (c) worst case, keep **embeddings on the Developer API** while chat moves to
  Agent Platform — memory recall is already best-effort and degrades gracefully, so
  chat is never blocked either way. **Existing `profile_facts` embeddings must stay
  comparable — do not change `EMBED_DIM` (768) or vectors already stored become
  meaningless.**
- **Model availability/naming differs** between the two surfaces (e.g. which
  `gemini-3.x` IDs exist, and `global` vs a regional location). Verify the exact IDs
  against the project before switching, and keep `MODEL_CHAT`/`MODEL_HEAVY` in config.
- **`reasoning_effort` support** on the compat endpoint is unconfirmed; our
  `_reasoning_kwargs()` already omits the param when empty, so worst case we clear it
  and lose only the "think harder" depth, not correctness.
- **Token refresh in async code**: `google-auth`'s refresh is blocking, so it must run
  off the event loop (threadpool) or be short enough to be negligible; guard with a
  lock to avoid a refresh stampede.
- **VM service-account permissions** may be missing/narrow by default — an explicit
  runbook step, verified with a live call from the VM.
- **Credit exhaustion** would return to hard failures; a **budget alert** makes that
  visible before users feel it.

## Migration Plan

Additive and reversible. Add settings + the token provider behind `llm_provider`;
verify locally against Agent Platform (streaming → tool loop → embeddings) **before**
touching production. Then enable the API + grant the VM role, update the prod `.env`,
redeploy. **Rollback** = set `LLM_PROVIDER=developer_api` (with the old key) and
restart — no code revert needed. No DB or schema change; stored embeddings are
untouched as long as the embedding model/dimension is unchanged.

## Open Questions

- **Embeddings over the compat endpoint** — decides whether `embed` needs its own path
  (risk 1). Verify first.
- **`global` vs a regional location** (e.g. `us-central1`) — affects the base URL and
  possibly model availability; pick during apply.
- **Exact model IDs** available to this project (`google/gemini-2.5-flash` vs a 3.x id).
- **Adding `google-auth`** — needs Narendra's OK per the project's dependency rule.
