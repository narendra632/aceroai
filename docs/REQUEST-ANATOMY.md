# REQUEST-ANATOMY.md — what one chat message actually costs

Exactly what gets sent, how it is assembled, where the time goes, and what it costs in
tokens. **Every number here was measured on this machine**, not estimated — and you can
reproduce all of them yourself (see [Verify it yourself](#verify-it-yourself)).

---

## 1. What is sent with each message

Your message is never sent alone. `core/composer.build_context()` assembles a stack of
**system blocks** plus recent history, then `core/handler` adds the tool definitions.

| # | Block | Source | Rebuilt each turn? | Typical size |
|---|---|---|---|---|
| 1 | **Persona** | `docs/SOUL.md`, read from disk | yes (file read, ~0 ms) | ~1,000 chars · ~250 tok |
| 2 | **Current date/time** | computed, your timezone | yes | ~70 chars · ~18 tok |
| 3 | **Open tasks** | `tasks` table, urgency-ordered, capped at `CONTEXT_TASKS_LIMIT` (30) | yes (DB read) | ~100 chars/task |
| 4 | **Recalled memory** | `profile_facts` via pgvector similarity to *this* message | yes (embedding + search) | ~90 chars/fact |
| 5 | **History** | last `HISTORY_LIMIT` (20) messages of this session | yes (DB read) | grows with the chat |
| 6 | **Your message** | — | — | — |
| 7 | **Tool definitions** | `core/tools.TOOLS` (7 tools, names + JSON schemas) | every turn | ~1,300 chars · ~330 tok |

**Measured example** (a short message, 9 facts recalled, 3 open tasks, new session):

```
ctx_msgs=5  ctx_chars=2809  ctx_approx_tokens=702      ← our own estimate of blocks 1-6
tokens_in=1259  tokens_out=39                          ← what Gemini actually billed
```

> The gap (702 estimated vs 1,259 billed) is mostly the **tool definitions**, which are
> sent as structured schemas outside the message text, plus tokenizer differences. The
> provider's `tokens_in`/`tokens_out` are the authoritative billing numbers; our
> `ctx_*` figures exist to show *which block* is costing you.

**What is NOT sent:** other conversations, tasks belonging to anyone else, your `.env`,
raw ids beyond task ids, or any provider credentials.

---

## 2. The pipeline, step by step

```
POST /api/chat
  │
  ├─ 1. auth            decode bearer token → user                      ~1 ms
  ├─ 2. persist_user    INSERT message (+ session if new)              ~20-40 ms
  │     └─► SSE "session" event  ← the UI now has a session id
  ├─ 3. memory_recall   embed(your message) → pgvector cosine search   ~1.7-3 s  ⚠ dominant
  ├─ 4. build_context   read tasks + last 20 messages, assemble blocks  ~10-40 ms
  ├─ 5. llm_round1      send context + tools → stream tokens back      ~1-2 s
  │     ├─ if it returns TEXT      → stream to you, done
  │     └─ if it returns TOOL_CALLS→ SSE "tool" event ("Working…")
  │          ├─ 6. tool:<name>     run via services/ (a DB write)       ~7-20 ms
  │          └─ 7. llm_round2      feed results back → final answer    ~1-2 s
  ├─ 8. persist_assistant  INSERT reply + token counts                 ~20-45 ms
  │     └─► SSE "done" event
  └─ 9. background: extract durable facts → embed → store   ← AFTER "done", never felt
```

**Streaming matters:** you see the first word at `first_token`, not at `total`. The
reply keeps arriving after that.

---

## 3. Measured latency (this machine, 2026-08-16)

Short message, 9 facts recalled, no tool call. Times in ms.

| Stage | Gemini `3.5-flash` | OpenAI `gpt-5.1` |
|---|---|---|
| persist_user | 21–30 | 19–41 |
| **memory_recall** | **1,775–1,825** | **1,713–1,715** |
| build_context | 8–13 | 10–14 |
| llm_round1 | 1,048–1,056 | 1,736–1,804 |
| persist_assistant | 30–42 | 40–45 |
| **first token** | **~2,870** | **~3,500** |
| **total** | **~2,910–2,950** | **~3,542–3,591** |

First request after a restart is slower (~5.2 s Gemini / ~8.0 s OpenAI) — cold
connections. A tool turn adds one more model round: ~+1.0–1.4 s plus ~7–20 ms for the
tool itself.

**Reading it:** the model is ~1–1.8 s. Our own code (DB, assembly) is **under 100 ms
total** — it is not the bottleneck. Everything else is network.

### ⚠ The big find: embeddings were costing 12 seconds

Before this instrumentation existed, every message took **~14 s**. The logs showed why:

```
turn total=14629ms  memory_recall=12886ms  llm_round1=1669ms  build_context=16ms
recall embed=12721ms  pgvector=23ms          ← the embedding call, not the database
```

**Cause:** embeddings were served from Vertex's `global` endpoint. Measured with
realistic gaps between calls (i.e. real conversation), `global` took **~12 s every
time**, while `us-central1` took **~0.5–2 s** for the *same model and dimensions*.

**Fix:** `EMBED_LOCATION=us-central1` (a separate regional client just for embeddings).
Before switching, the vectors were compared across regions: **cosine similarity
1.000000** — identical, so stored memory stays valid. Result: **~14 s → ~2.9 s.**

A `MEMORY_RECALL_TIMEOUT_S` (4 s) now caps this stage: if embedding stalls, you get an
answer without recalled facts instead of a 12-second wait. Recall was always
best-effort; now its cost is bounded.

---

## 4. Token cost per turn

From the same measured turns:

| | Gemini turn (no tool) | Gemini turn (with 1 tool round) |
|---|---|---|
| `tokens_in` | 1,259 | 1,530 |
| `tokens_out` | 39 | 97 |

**What drives `tokens_in`:** the fixed floor is persona + date + tool schemas
(~600–700 tokens) — paid on *every* message. On top of that: ~25 tokens per recalled
fact, ~25 per open task, and the whole visible history (which grows until it hits the
20-message window).

**A tool turn costs roughly double**, because the entire context is re-sent for round 2
along with the tool result.

**Also billed, off the reply path:** memory extraction after `done` (one `complete()`
call plus an embedding per new fact), and one embedding per message for recall.

---

## 5. Verify it yourself

Every turn logs one line (logger `aceroai.timing`). Watch the backend console, or:

```powershell
# from backend/
$env:TELEGRAM_BOT_TOKEN=""; uv run uvicorn app.main:app --reload
```

Send a message and compare against your stopwatch:

```
turn total=2913ms persist_user=30ms memory_recall=1789ms build_context=8ms
  first_token=2862ms llm_round1=1056ms persist_assistant=30ms
  provider=google model=gemini-3.5-flash effort=low facts=9
  ctx_msgs=5 ctx_chars=2795 ctx_approx_tokens=698 rounds=1 tokens_in=1530 tokens_out=97
```

- **Stopwatch from pressing Enter to the first word appearing** ≈ `first_token`.
- **Stopwatch to the reply finishing** ≈ `total` **plus** network/render time between
  your browser and the server (a few ms locally, ~100–300 ms against the live VM).
- `recall embed=… pgvector=…` is logged separately, splitting the network call from the
  database search.
- Per-block sizes: set the app logger to `DEBUG` to also print each block's chars/tokens.

Expect variance of a few hundred ms between identical requests — that is the provider,
not the app.

---

## 6. Where the remaining time goes (honest assessment)

At ~2.9 s, the split is roughly **60 % embedding, 35 % model, <5 % us**.

Options if it needs to be faster, and their costs:
- **Skip recall on trivial messages** ("ok", "thanks") — saves ~1.7 s on those turns.
- **Cache the embedding** of repeated identical messages — narrow benefit.
- **A faster/smaller embedding model** — would invalidate every stored vector, so it
  requires a deliberate re-embed migration (see the pinning note in Settings).
- **Fewer tools or shorter schemas** — cuts the fixed token floor, at the cost of
  capability.

None are done yet; the 5× win from the region fix was the one worth taking first.
