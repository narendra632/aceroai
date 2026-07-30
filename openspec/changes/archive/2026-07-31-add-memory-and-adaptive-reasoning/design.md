## Context

The one brain (`handle_message`) persists a user turn, builds context via
`composer.build_context(db, session_id)`, streams from `llm.stream_chat`, then
persists the assistant turn. `profile_facts` already exists in the schema
(`fact`, `category`, `confidence`, `source` stated/inferred, `status`
active/superseded/rejected, `superseded_by`, `valid_from`) but nothing uses it,
and the `vector` extension is already enabled (migration 001) though no column
uses it. `llm.stream_chat` talks to any OpenAI-compatible endpoint (Gemini by
default), which accepts the standard `reasoning_effort` parameter and exposes an
`/embeddings` endpoint. This change is backend-only; it adds one migration and
one dependency.

## Goals / Non-Goals

**Goals:**
- Acero remembers durable facts about the user across sessions and channels.
- Memory retrieval is **semantic** (pgvector): the most *relevant* facts are
  recalled per message, not just "all of them" — the real vector-search pipeline,
  end to end (embed → store → HNSW search).
- Memory-building never adds latency to a reply and never breaks a reply if it
  fails (best-effort, off the hot path).
- Normal chat replies start streaming sooner by spending little time "thinking".
- Provider-swap stays intact (embeddings + reasoning both go through the existing
  OpenAI-compatible client).

**Non-Goals:**
- Embedding journals/tasks/old message history — this change embeds *facts* only;
  extending vectors to other tables comes with those features.
- Conflict resolution / superseding of contradicting facts — v1 adds new facts and
  can mark duplicates; a fuller supersede flow is a later increment.
- A UI to view/curate memory — that's the future "knowledge visualization" page.

## Decisions

**1. Adaptive reasoning via the standard `reasoning_effort` parameter.**
`stream_chat(messages, ..., reasoning_effort: str | None = None)` forwards the
value to the endpoint only when set (falsy → omit it, so providers/models that
don't support it are unaffected). `reasoning_effort` is the portable OpenAI-standard
knob — it keeps the provider-swap promise, unlike Gemini-specific `thinking_config`
(which stays an escape hatch for exact budgets). *Note:* on Gemini 3 models thinking
can be turned **down** (`low`) but not fully off; `low` still removes most of the
first-token delay.

The effort is chosen **per request** — that's what makes it *adaptive*, not just
configurable:
- `handle_message(..., reasoning_effort=None)` — the **task-routing hook**. A
  caller may pass an explicit effort; otherwise it defaults to
  `settings.reasoning_effort_chat` (`low`). Future tasks (the daily review) pass
  `high`; chat stays fast.
- **Explicit user control** lives in the thin transport layer: the web route maps
  `deep: true` → `reasoning_effort_deep`; the Telegram channel maps a `/think`
  prefix → `reasoning_effort_deep`. Channels stay logic-free — they only translate
  a user affordance into the handler parameter.

*Alternatives:* a hard-coded single budget (not adaptive — the thing we're
correcting); a **router model** that classifies each message and picks the effort
(the fully-automatic version — deferred: it adds an API call per message, which is
untenable on the ~5 req/min free tier; revisit once billing is enabled).

**2. Real semantic memory with pgvector — implemented now, not deferred.**
Facts are embedded and retrieved by vector similarity, not bulk-injected. Concretely:
- **Column:** migration 002 adds `profile_facts.embedding vector(768)` and an
  **HNSW** index using `vector_cosine_ops`. HNSW gives fast approximate nearest-
  neighbour search and is the right default over IVFFlat for a small, incrementally
  -grown set.
- **Embedding model:** `gemini-embedding-001` via the OpenAI-compatible
  `/embeddings` endpoint, output **768 dims** (set via the `dimensions` param; the
  model is Matryoshka-trained so 768 keeps strong quality at a small index size).
  Dimension is a config constant so the column and calls never drift.
- **Store:** on each new fact, `store_facts` embeds it and writes the vector with
  the row.
- **Recall:** `recall_facts(db, user, query_text, k)` embeds `query_text` (the
  incoming user message) and runs `ORDER BY embedding <=> :q LIMIT k` over the
  user's **active** facts, returning the top-K most relevant. `MEMORY_RECALL_K`
  (default e.g. 12) bounds context size regardless of how large memory grows.
*Rationale:* this is the actual craft Narendra wants to learn, it scales as memory
grows, and it makes pgvector real so the future "watch my knowledge grow"
visualization has genuine vector data to show. *Alternative rejected:* inject all
active facts (simpler, but doesn't scale, teaches nothing about retrieval, and
leaves pgvector unused).

**3. Fact extraction runs in the background, after the reply, with its own DB
session.** After `_persist_assistant_turn`, `handle_message` schedules
`asyncio.create_task(memory.extract_and_store(user_id, user_text, reply_text))`
and holds a reference (so it isn't GC'd) until it finishes. The task opens a
**fresh `SessionLocal`** — never reusing the request's session across the
background boundary. It calls `model_memory` (default = Flash chat model) with
`reasoning_effort="low"`, passing the exchange **and the user's current active
facts**, and asks for only *new* durable facts as JSON; it embeds and stores them.
All errors are logged and swallowed. Works identically for web and Telegram (same
loop). *Alternatives rejected:* inline extraction (adds latency to every reply);
FastAPI `BackgroundTasks` (request-scoped, and the handler is channel-agnostic).

**4. Conservative extraction prompt.** The extractor captures only *stable,
personal, useful* facts (categories matching the CHECK: preference / health / work
/ finance / relationship / other), skips ephemera, and skips anything already
known. Stored with `source="inferred"`, a confidence, `status="active"`. This is
the main defense against memory clutter; provenance stays visible for a future
curate/reject UI.

**5. Composer signature grows a `user`.** `build_context(db, user, session_id)` so
recall can scope to the user and embed the latest user message as the query.
`handle_message` already has `user`. Recall stays synchronous except the single
embedding call; to keep composer simple, the query embedding is done via a small
sync wrapper (the embed call runs inside the existing `run_in_threadpool` context
that already wraps `build_context`).

## API budget (must-know)

Every message now triggers, beyond the 1 chat completion: **1 query-embedding**
(recall) and, in the background, **1 extraction completion + up to N
fact-embeddings**. That's ~3–5 API calls per turn. The current **free tier is
~20 requests/day** (confirmed on Narendra's AI Studio Rate Limit page — not the
1,500/day that blogs claim), so free tier suffices only for a few test turns.
**Real use requires enabling billing → Tier 1** (instant; removes the RPD cap;
~150–300 RPM; pennies/day for one user). This change is built so that's a billing
switch, not a code change. Embeddings and extraction can also be throttled later
if needed; not doing so now (per "build it properly").

## Risks / Trade-offs

- **Bad/embarrassing inferred facts.** Conservative prompt + `source="inferred"`
  + `status` give provenance and a future reject path. v1 accepts some noise.
- **Duplicate facts.** Dedup by passing known facts to the extractor plus a
  vector-similarity check before insert (skip if too close to an existing active
  fact) — semantic dedup, better than string match.
- **Contradictions accumulate** (old + new city). v1 adds; superseding is a named
  follow-up.
- **Extra API calls / cost.** See API budget — off the hot path, trivial cost on
  Tier 1; the free tier is the real constraint, addressed by enabling billing.
- **Embedding dimension lock-in.** Changing `EMBED_DIM` later means a re-embed +
  migration; 768 is a deliberate, documented choice to avoid churn.
- **Background task on shutdown** may be cancelled mid-extraction — fine, memory is
  best-effort; the next turn re-observes.
- **HNSW build/recall correctness in tests** — tests use small deterministic fake
  embeddings so vector ordering is assertable without a live model.

## Migration Plan

Additive: `core/memory.py`, edits to `composer`/`handler`/`llm`/`config`/`models`,
env vars, and **migration 002** (add `embedding` column + HNSW index; downgrade
drops them). Add the `pgvector` dependency (`uv add pgvector`). Rollback = revert
code + `alembic downgrade` one step; existing fact rows remain, just unembedded.
To disable memory without reverting: turn the extraction switch off and set
`MEMORY_RECALL_K=0` so nothing is injected.

## Open Questions

- **`pgvector` dependency** — OK to add? (Standard official binding; required for
  the `Vector` column type.) Assuming yes per your "implement pgvector now".
- **Embedding dimension** — 768 (recommended balance) vs 1536/3072 (higher quality,
  bigger index). Defaulting to 768; easy to raise before we accumulate data.
- **Recall K** — default ~12 relevant facts injected per message; tune to taste.
