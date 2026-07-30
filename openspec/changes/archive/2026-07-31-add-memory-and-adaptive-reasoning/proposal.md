## Why

Today Acero forgets Narendra between chats: `composer.build_context` only reads
the current session's last 20 messages, and the `profile_facts` table — the seat
built for durable memory — is never read or written. So every new conversation
starts blank. This change adds the first **cognition** layer: Acero extracts
durable facts about Narendra from conversations, embeds them, and **semantically
recalls the most relevant ones** into every future session — turning "a chatbot
with a personality" into "an assistant that knows me." This is also where
**pgvector finally does real work** instead of sitting installed-but-unused.

At the same time, chat feels slow (5–7s before the first token) because the chat
model is a *reasoning* model that silently "thinks" before replying — wasteful for
ordinary chat. We add **adaptive reasoning**: a per-request thinking budget so
normal chat replies fast, while heavy jobs (future reviews) can still think deeply.

These ship together because they're both small, both touch the same core path
(`llm` → `handler` → `composer`), and both are pure quality-of-life wins on the
existing one brain.

## What Changes

- **Adaptive reasoning.** `core/llm.stream_chat` gains an optional
  `reasoning_effort` argument, passed straight through to the OpenAI-compatible
  endpoint. `handle_message` gains a `reasoning_effort` parameter (the routing
  hook) and defaults chat to `REASONING_EFFORT_CHAT` (`low`) — fast first token.
  The effort is chosen **per request**, two ways: **explicit user control** (a web
  "think harder" toggle sending `deep: true`; a Telegram `/think` prefix) routes a
  turn to `REASONING_EFFORT_DEEP` (`high`); and **task routing** lets any caller
  (e.g. a future daily-review job) pass its own effort. (A fully-automatic router
  model is deferred until billing — it costs an extra call per message.)
- **Fact extraction (background).** After the assistant turn is persisted,
  `handle_message` schedules a fire-and-forget task that asks a cheap model to pull
  *durable* facts about the user from the exchange (given the already-known facts,
  so it only proposes new ones), and stores them in `profile_facts`. This runs off
  the reply path — it never adds latency and never breaks a reply if it fails.
- **Embeddings + pgvector (the real semantic memory).** Every stored fact is
  embedded (Gemini embeddings via the same OpenAI-compatible client) and saved to a
  new `embedding vector(768)` column with an **HNSW index** for fast cosine search.
- **Semantic recall / injection.** For each incoming message, `composer.build_context`
  embeds the query, runs a **vector similarity search** over the user's active
  facts, and injects the top-K most relevant ones as a system block right after the
  SOUL.md persona — so the most pertinent knowledge, learned in any earlier session,
  is present in every later one, on any channel.
- **Migration 002** adds the `embedding` column + HNSW index to `profile_facts`
  (the `vector` extension is already enabled by migration 001).
- **One new dependency:** the `pgvector` Python package (the SQLAlchemy `Vector`
  column type). Flagged for approval per project rule; it is the standard, official
  pgvector binding.
- **Robustness (folded-in audit fixes).** `stream_chat`/`complete` retry transient
  provider errors (timeout/connection/rate-limit) with backoff, only before the
  first token; the handler logs full errors but returns a **friendly** message
  (never raw provider text) and a clear rate-limit message on quota; over-long
  messages are rejected before persistence; and recall is best-effort so a quota
  hit never breaks chat.
- Docs: `backend/README.md` gains a "Memory" section (extract → embed → store →
  semantic recall) and notes the reasoning setting; `.env.example` gains the new
  settings.

## Capabilities

### New Capabilities
- `memory`: extract durable facts about the user from conversations, embed and
  store them in `profile_facts` (pgvector), and **semantically recall** the most
  relevant active facts into every session's context — cross-session, cross-channel
  memory backed by vector search.

### Modified Capabilities
- `web-chat`: context is now persona + **semantically-recalled profile facts** +
  recent history (was persona + recent history); chat generation uses an
  **adaptive reasoning effort** — fast by default, deeper on an explicit "think
  harder" or when a caller routes it.
- `telegram`: a `/think` prefix routes that message to deeper reasoning.

## Impact

- **Code:** new `core/memory.py` (extract / embed / store / semantic recall);
  `core/llm.py` gains `embed()` + `complete()`, retry/backoff, and forwards
  `reasoning_effort`; `core/composer.py` injects recalled facts (signature grows a
  `facts` list, computed by the handler); `core/handler.py` recalls facts,
  schedules background extraction, and resolves the reasoning effort;
  `api/chat.py` + `api/schemas.py` add the `deep` flag; `channels/telegram.py`
  adds `/think`; `db/models.py` gains the `embedding` column; `config.py` gains
  the reasoning/memory/robustness settings. Frontend: a "think harder" toggle in
  the composer, threaded through `streamChat`.
- **Schema:** Alembic **migration 002** — `profile_facts.embedding vector(768)` +
  HNSW index (`vector_cosine_ops`).
- **Dependencies:** adds `pgvector` (Python) — **needs your OK** (project rule:
  ask before adding a dependency).
- **Config:** `REASONING_EFFORT_CHAT` (default `low`), `EMBED_MODEL`
  (`gemini-embedding-001`), `EMBED_DIM` (`768`), `MEMORY_RECALL_K` (top-K facts),
  `MODEL_MEMORY` (default = chat model), extraction on/off switch.
- **API budget (important):** recall now costs **1 embedding call per message** and
  extraction **1 model + N embedding calls per turn** — off the reply path, but
  this multiplies request count. On the current **free tier (~20 requests/day)**
  that is only enough for light testing; **real daily use needs billing → Tier 1**
  (pennies/day for one user). See design "API budget".
- **Testing:** unit tests for semantic recall (top-K active-only injection, faked
  embeddings), extraction (stores + embeds new facts, skips duplicates, failure is
  swallowed), migration applies, and that `reasoning_effort` is threaded to the LLM
  — all with faked model/embeddings, no live provider in CI.
