## 1. Adaptive reasoning

- [ ] 1.1 `core/llm.py`: add `reasoning_effort: str | None = None` to `stream_chat`; include it in the `create(...)` call **only when truthy** (so unsupported providers/models are unaffected)
- [ ] 1.2 `config.py`: add `reasoning_effort_chat: str = "low"`; `.env.example`: add `REASONING_EFFORT_CHAT=low` with a one-line comment
- [ ] 1.3 `core/handler.py`: pass `settings.reasoning_effort_chat` into `stream_chat`
- [ ] 1.4 Manual: confirm first-token latency drops noticeably on the live model (chat still replies correctly)

## 2. Dependency + schema (pgvector)

- [ ] 2.1 `uv add pgvector` (needs approval); confirm it imports and `uv.lock` updates
- [ ] 2.2 `db/models.py`: add `embedding: Mapped[list[float] | None]` via `pgvector.sqlalchemy.Vector(EMBED_DIM)` on `ProfileFact`
- [ ] 2.3 Alembic **migration 002**: add `profile_facts.embedding vector(768)`; create an **HNSW** index `... using hnsw (embedding vector_cosine_ops)`; downgrade drops index + column
- [ ] 2.4 `uv run alembic upgrade head` on the dev DB; verify column + index exist

## 3. Embeddings in the LLM wrapper

- [ ] 3.1 `core/llm.py`: add `async def embed(texts: list[str]) -> list[list[float]]` using the same lazy client's `/embeddings` (`EMBED_MODEL`, `dimensions=EMBED_DIM`); return vectors in input order
- [ ] 3.2 `config.py`: add `embed_model="gemini-embedding-001"`, `embed_dim=768`, `memory_recall_k=12`, `model_memory` (default = `model_chat`), `memory_extraction_enabled=True`; `.env.example` entries with comments

## 4. Memory core (`core/memory.py`)

- [ ] 4.1 `recall_facts(db, user, query_text, k)`: embed `query_text`; vector-search active facts with `ORDER BY embedding <=> :q LIMIT k` (skip rows with NULL embedding); return fact strings, most-relevant first
- [ ] 4.2 `store_facts(db, user, facts)`: embed each fact; **semantic dedup** (skip if cosine-close to an existing active fact); insert as `profile_facts` (`source="inferred"`, `status="active"`, category, confidence, embedding)
- [ ] 4.3 `extract_and_store(user_id, user_text, reply_text)`: fresh `SessionLocal`; load active facts; call `model_memory` (`reasoning_effort="low"`) with a conservative JSON-returning prompt; parse defensively; `store_facts`; wrap so **all errors are logged and swallowed**

## 5. Wire into the one brain

- [ ] 5.1 `core/composer.py`: `build_context(db, user, session_id)` — after the SOUL.md system message, inject a system block of `recall_facts(...)` results (omit when empty); then recent history as before
- [ ] 5.2 `core/handler.py`: pass `user` into `build_context`; after persisting the assistant turn, if extraction is enabled, `asyncio.create_task(...)` the extraction and hold a reference until done (guard GC)
- [ ] 5.3 Confirm both channels benefit (web + Telegram call the same handler; no channel edits)

## 6. Tests

- [ ] 6.1 Fakes: extend the test LLM fake with a deterministic `embed()` (stable vectors per text) so vector ordering is assertable without a live provider
- [ ] 6.2 `recall_facts`: returns only **active** facts (superseded/rejected excluded), ordered by similarity, capped at `k`
- [ ] 6.3 `store_facts`: inserts + embeds new facts; skips a near-duplicate of an existing active fact
- [ ] 6.4 `extract_and_store`: with a faked model stores the returned facts; a raising model/embed call does **not** propagate (reply path unaffected)
- [ ] 6.5 `composer.build_context`: injects the recalled-facts block after the persona when facts exist; omits it when none
- [ ] 6.6 `reasoning_effort` is forwarded to `stream_chat` from the handler (and omitted when unset)
- [ ] 6.7 CI: migration 002 applies against the Postgres service before pytest; `ruff format`/`check` + `pytest` all green

## 7. Robustness (folded-in audit fixes)

- [ ] 7a.1 **Retry/backoff** (`core/llm.py`): retry the stream/complete request on transient provider errors (timeout, connection, rate-limit) with short backoff, up to `LLM_MAX_RETRIES`; only retry when **no token has been yielded yet** (never duplicate output)
- [ ] 7a.2 **Error hygiene** (`core/handler.py`): log the full exception server-side; surface a **friendly generic** message to the client (a specific "rate limit / quota" message for `RateLimitError`), never the raw provider string
- [ ] 7a.3 **Input cap** (`core/handler.py`): reject an over-long message (`MAX_INPUT_CHARS`) with a clear `error` event **before** persisting anything
- [ ] 7a.4 **Recall is best-effort**: a failure to embed or search (e.g. quota) MUST NOT fail the chat — recall returns no facts and the reply proceeds
- [ ] 7a.5 Tests for the three fixes (retry retried-then-succeeds and not-duplicated; over-long input rejected & not persisted; provider error yields a friendly message, not the raw text)

## 9. Docs

- [ ] 9.1 `backend/README.md`: "Memory" section (extract → embed → store in `profile_facts` → semantic recall via pgvector/HNSW; best-effort/background) + `REASONING_EFFORT_CHAT` note
- [ ] 9.2 Update the `app/` file-guide table: `core/memory.py` built; `profile_facts` + `embedding` now in use; note migration 002

## 10. Manual verify (end-to-end)

- [ ] 10.1 Tell Acero a durable fact in one session; start a **new** session and confirm it recalls/uses that fact
- [ ] 10.2 Inspect `profile_facts`: the fact is stored with `source="inferred"`, `status="active"`, and a non-NULL `embedding`
- [ ] 10.3 Confirm ordinary replies feel faster (reasoning `low`)
- [ ] 10.4 (If still on free tier) note the ~20 req/day cap during testing; confirm the plan to enable billing for real use
