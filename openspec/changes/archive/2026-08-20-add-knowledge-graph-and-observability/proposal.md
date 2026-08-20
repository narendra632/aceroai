## Why

Two things this app does constantly are **completely invisible to the person it does them
for**: what it has learned, and what it costs.

### 1. The memory has no way out

`profile_facts` is written by `core/memory.py` and read by exactly one query — the recall
that feeds the model. **No route in `api/` touches the table.** The assistant carries
inferred conclusions about Narendra into every conversation on every channel, forever, and
he cannot read them, correct them, or delete them.

Three columns were designed for this and were never wired up:

| Column | Intended meaning | Reality |
|---|---|---|
| `source_ref` | the `messages.id` the fact came from — provenance | never set; `extract_and_store` receives text, not ids |
| `source='stated'` | the user said or confirmed it, vs. an LLM guess | never written; `_store` hardcodes `source="inferred"` |
| `superseded_by` | this fact was replaced by a newer one | never set; nothing ever supersedes anything |

A fact you cannot see the origin of is a fact you cannot argue with. Since **every stored
fact is an LLM's inference**, and an inference can be wrong, an uninspectable memory is not
a feature — it is an accumulating liability.

The dead `superseded_by` column hides a real defect. `_too_similar()` is the only gate on
new facts, and it measures **cosine distance alone**. A fact that *changed* ("works at A" →
"works at B") is by construction *highly similar* to the fact it replaces. So:

- distance < `memory_dedup_distance` → the **new, true** fact is silently discarded
- distance ≥ `memory_dedup_distance` → both are stored `active`, and recall hands the model
  **two contradicting facts** with no signal about which is current

The gate cannot tell "said the same thing again" from "this changed". That is precisely
what `superseded_by` exists to express.

### 2. The cost has no meter, and three defects mean the numbers we do have are wrong

`core/telemetry.Timeline` **is already a trace** — ordered stages, notes, provider usage —
and then it is formatted into a log line and discarded. Nothing is queryable, nothing is
aggregated, and cost is never computed at all.

Worse, the token counts that *are* persisted are incorrect in three distinct ways:

**Defect A — thinking tokens are dropped.** `providers/google.py:205` records
`candidates_token_count`, which **excludes** `thoughts_token_count`. Every turn sets a
thinking budget (`THINKING_BUDGET_LOW`/`HIGH`), so billed output — the expensive side — is
systematically undercounted.

**Defect B — tool turns overwrite themselves.** One `usage` dict is created per turn
(`handler.py:199`) and passed into every round of the loop. Each round **assigns** into it
rather than accumulating. A three-round turn billed 7,300 in / 230 out records **2,900 /
120** — round 3 only. Every tool-using turn already in the database is understated, and the
missing rounds are unrecoverable.

**Defect C — background work is entirely unmetered.** One user message triggers up to
**four** provider calls:

| # | Call | Purpose | Recorded? |
|---|---|---|---|
| 1 | `llm.embed` | embed the message for recall | ❌ |
| 2 | `llm.stream_with_tools` | the reply | ⚠️ partially (A + B) |
| 3 | `llm.complete` | the fact extractor | ❌ |
| 4 | `llm.embed` | embed newly-found facts | ❌ |

Call 3 is a **second full LLM call on every single message**. The provider contract cannot
even express its cost: `complete()` and `embed()` take **no `usage` parameter at all**
(`providers/base.py:62-70`). There is nowhere to put the number.

The invisible fraction of spend is currently **unknown** — which is the point. Producing
that number honestly is the first thing this change does.

### 3. The extraction prompt grows without limit

`_load_active_facts()` selects **every active fact**, with no limit and no relevance
filter, and `_extract()` inlines all of them into the extractor's prompt on **every
message**.

| Facts stored | Extra prompt tokens, per message, forever |
|---|---|
| 50 | ~600 |
| 200 | ~2,400 |
| 500 | ~6,000 |

This is not a mistaken design — it buys a *soft* "don't repeat yourself" instruction. But
there are **two** dedup gates, and the soft one is the unreliable half:

| Gate | Mechanism | Guarantee |
|---|---|---|
| soft — the prompt block | asks the model not to repeat | none; models ignore instructions |
| **hard — `_too_similar()`** | cosine distance, checked against **all** facts in the DB | real, and independent of the prompt |

The hard gate already queries the whole table regardless of what the prompt contained. So
the unbounded block buys an unreliable check at a cost that **grows with how well the
memory works**. Success makes it more expensive. Nobody would have noticed without the
meter this change builds — which is the argument for building it.

---

## What Changes

### A. Memory becomes visible, correctable, and honest about change

- **`api/memory.py`** — the first HTTP surface for `profile_facts`: list with search and
  filters, a graph endpoint, edit, confirm, forget, restore.
- **Provenance is wired up.** The originating `messages.id` is threaded into
  `extract_and_store` and stored in `source_ref`, so every fact can name the conversation
  that produced it.
- **`source='stated'` gets a meaning.** Confirming a fact promotes it from `inferred` to
  `stated` at confidence 1.0. A confirmed fact outranks a contradicting guess.
- **`superseded_by` gets a meaning.** Editing a fact does not overwrite it: the old row
  becomes `status='superseded'` and links to its replacement. History is preserved; recall
  is unaffected because it already filters `status='active'`.
- **Contradiction is handled.** The dedup gate learns to distinguish *repeat* from
  *changed*, and supersedes instead of silently dropping the newer truth.
- **Forgetting is reversible**, matching the Undo pattern established in migration 004.

### B. The knowledge graph — you can see what it knows

A **Knowledge** page rendering facts as a semantic graph: nodes are facts, edges are
pgvector cosine-kNN neighbours, laid out by a force simulation in the browser.

Vectors never cross the wire — the server sends nodes and edges only. Category colouring,
confidence as node weight, a **timeline scrubber** replaying how the memory grew, a detail
panel with provenance and the edit/confirm/forget actions, full-text search, and a
**list ⇄ graph toggle** (list is the default on small screens and is the accessible
equivalent of the canvas).

### C. Traces, tokens and cost — you can see what it costs

- **Two new tables, `turns` and `spans`**, shaped along **OpenTelemetry GenAI semantic
  conventions** so a future export is a formatting change, not a redesign. `Timeline` stops
  being discarded and is persisted after the response is delivered.
- **All three accounting defects fixed**: thinking tokens captured; usage **accumulated**
  across tool rounds; `complete()` and `embed()` gain usage reporting in the provider
  contract, so background calls are metered and attributed.
- **A dated pricing catalog** with cost computed and **frozen at write time**, plus the
  catalog version that produced it — so a later price change never silently rewrites
  history.
- **An Insights page**: spend and volume over time, cost by model and by kind, latency
  percentiles, error taxonomy, and the hero artifact — a **per-turn waterfall** showing
  where the wall-clock time of one turn actually went. That view is what caught the 12 s
  embedding stall from raw logs; this makes it a click.
- **Retention**: raw spans are pruned after a window; daily rollups are kept forever.

### D. The extraction prompt is bounded — for free

The embedding of the user's message is **already computed** during recall, and the twelve
most relevant facts are **already retrieved**. Those are passed into extraction instead of
the entire table. Same soft check, bounded cost, **zero additional provider calls**. The
hard `_too_similar()` gate is untouched, so the duplicate guarantee does not change.

### E. Two smaller corrections carried by this change

- **`httpx` logs the Telegram bot token.** It logs full request URLs at INFO, and the
  Telegram API embeds the token in the path — so the secret is written to logs locally and
  in production. Raised to WARNING. Observability's own footgun belongs in the
  observability change.
- Retry counts and dedup rejections are currently logged and then lost; both become
  counted signals.

---

## Non-goals (this change)

- **No third-party observability platform.** Not Langfuse, LangSmith, Phoenix, Helicone or
  Grafana. Self-hosting any of them means Postgres + ClickHouse or a ~200 MB Grafana on a
  1 GB `e2-micro`; SaaS means conversation metadata leaves the box and costs money. The
  data model is shaped for OTel so this stays open.
- **No OTel exporter is built.** Designed for, deliberately not implemented.
- **No prompt or response text in traces.** Shapes, counts and durations only. `messages`
  already holds the content; duplicating it doubles both the disk footprint and the blast
  radius of a leak.
- **No historical backfill.** Narendra's decision: traces start clean from today. Defect B
  means past tool turns are unrecoverably wrong, so a backfilled chart could not be honest.
  The Insights page states its start date rather than implying it has always been watching.
- **No proactive budget notification.** A monthly budget and an in-app threshold warning
  are in scope; *Acero telling you unprompted* needs the scheduler, which is the next change.
- **No dimensionality reduction (PCA/UMAP/t-SNE).** Rejected with reasons in `design.md`.
- **No change to `EMBED_MODEL` / `EMBED_DIM`.** Every stored vector came from the current
  model; changing it is a deliberate re-embed migration, never a side effect.
- **No semantic journal search.** Related, separately scheduled.
- **Database backup is out of scope — Narendra's explicit decision.** The app is not in
  daily use yet, and losing its data today would cost him nothing he minds. He has accepted
  that risk deliberately and through the Investments feature. It stays listed in
  `ROADMAP.md` to be picked up when usage becomes real. This change does not address it,
  does not treat it as blocking, and should not re-argue it.

---

## Dependencies

**None. No package is added to either side.** ⚠️ Narendra approves any dependency, and this
change asks for none.

Two decisions he made deliberately keep it that way:

- **Charts are hand-rolled SVG**, not Recharts (~100 KB) — exact theme tokens in both
  modes, and the per-turn waterfall would have been custom regardless. Same approach as the
  Select and DatePicker primitives.
- **The graph is a kNN force simulation**, not a PCA projection — PCA would require `numpy`
  on the backend, or shipping 768-dimensional vectors to the browser.

## Risks

| Risk | Mitigation |
|---|---|
| Trace writes slow down replies | Persisted **after** the response completes, off the critical path, in its own session — the same discipline as memory extraction. Enforced by a test. |
| Trace tables grow without bound | Retention from day one: raw spans pruned after a window, daily rollups kept forever. Sized in `design.md`. Ordinary hygiene for a write-per-turn table — not a response to the backup question. |
| Computed cost is mistaken for a bill | Google bills via Cloud Billing on Agent Platform. Every cost figure is labelled an **estimate**, and the pricing-catalog version is stored per row so a number can always be explained. |
| A force graph is unusable on a phone | List view is the default under `sm`, and is a first-class view rather than a fallback. |
| A canvas graph is invisible to a screen reader | The list view is the accessible equivalent — same data, same actions, keyboard-reachable. |
| Bounding the extraction prompt causes duplicate facts | The hard vector gate is unchanged and independent of the prompt. A test asserts dedup still holds when the known-facts block is truncated. |
| Supersession hides facts that should still be active | Recall already filters `status='active'`; supersession is reversible from the UI, and §0 verifies the recall filter before any supersession is written. |
