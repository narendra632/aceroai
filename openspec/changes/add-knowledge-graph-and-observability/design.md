# Design

Ten decisions. Each records what was **rejected** and why — per `openspec/config.yaml`,
the rejected path is usually the more useful half of the record.

---

## Decision 1 — Traces live in our own Postgres, shaped like OpenTelemetry GenAI

**Chosen:** two tables, `turns` and `spans`, with column names mapped to the
OpenTelemetry **GenAI semantic conventions** (`gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.operation.name`).

The industry has converged on the **trace** as the primitive for LLM apps: one user turn is
a root span, with child spans for retrieval, each model round, and each tool call. That is
what Langfuse, LangSmith, Phoenix and Braintrust all model. **`core/telemetry.Timeline`
already produces exactly that shape** — ordered named stages with durations, plus notes and
provider usage — and then throws it away into a log line. The work is not "build tracing";
it is "stop discarding the trace, and add the two dimensions it lacks (cost, and the calls
that bypass it)."

Our tree is one level deep, which is all `Timeline` records. Modelling it as a general
recursive span tree would be speculative generality; a `turn` with ordered `spans` is honest
about the data we actually have and trivially widens later (`spans.parent_id` is additive).

**Rejected — a hosted platform (Langfuse Cloud, LangSmith, Helicone, Braintrust).**
Turnkey and genuinely excellent. But every turn's metadata — models, timings, token counts,
tool names — would leave the box to a third party, for a single-user personal assistant
whose entire premise is that it holds private life data. It also adds a paid dependency and
an availability coupling to the reply path if instrumented synchronously.

**Rejected — self-hosting Langfuse or Grafana + Prometheus on the VM.** The production
host is an always-free `e2-micro`: **1 GB RAM**, already running Caddy + api + Postgres.
Langfuse needs Postgres *and* ClickHouse. Grafana alone is ~200 MB resident. Neither fits,
and finding that out in production is the expensive way to learn it.

**Rejected — emit OTLP to a collector now.** Same hosting problem, plus it makes the data
unqueryable from our own app, which is the entire point of the Insights page. Shaping the
columns to the convention keeps a future exporter a ~50-line formatter.

**Rejected — keep it in logs and grep.** That is the status quo. It found the 12 s
embedding stall exactly once, because someone happened to be reading. Percentiles, cost
totals and trends are not reachable by grep.

---

## Decision 2 — Cost is computed once, at write time, and frozen

`cost_usd` is calculated when the turn row is written and **stored**, alongside
`pricing_version` — the identifier of the catalog entry that produced it.

Prices change. If cost were computed at read time from a current price table, opening the
Insights page after a price change would silently rewrite last month's spend. Every real
billing system freezes the rate at the moment of the transaction, for exactly this reason.
Storing `pricing_version` means any number on screen can be traced back to the rate that
produced it.

The catalog is **code, with effective dates** — `PRICING: dict[str, list[PriceRow]]`, each
row carrying `valid_from`, `input_per_mtok`, `output_per_mtok`, `cached_input_per_mtok`.

**Rejected — a `model_pricing` DB table.** Editable without a deploy, which sounds like an
advantage until you notice it needs an admin UI, a migration, and a seeding story, for data
that changes a few times a year in a single-user app. Code review is a better change-control
mechanism for prices than a form.

**Rejected — computing cost at read time.** Simpler, one less column, and wrong: history
becomes non-reproducible.

**Rejected — presenting cost as authoritative.** Google's Agent Platform bills through
Cloud Billing; we never see the invoice. Every figure is labelled an **estimate**. Showing
an estimate styled as a bill is the kind of small dishonesty that destroys trust in a
dashboard the first time it disagrees with reality.

---

## Decision 3 — Usage accumulates; the provider contract learns to report it

`usage` becomes an **accumulator**. Providers add to it rather than assigning, and
`complete()` / `embed()` gain the same `usage: dict | None` parameter
`stream_with_tools()` already has.

This is the fix for defects **B** and **C** together, and they are one root cause: the
contract in `providers/base.py` only allows *streaming* calls to report usage, so the two
non-streaming call sites had nowhere to put a number and were never asked for one.

Google additionally reports `thoughts_token_count` separately from
`candidates_token_count` — defect **A**. Thinking tokens are billed as output. The turn row
stores `tokens_thinking` as its own column rather than silently folding it into
`tokens_out`: it is a real, separately controllable cost (via the thinking budget), and
making it visible is what lets the effort setting be evaluated rather than guessed at.

**Rejected — summing tokens per round into a list on the turn.** More faithful, and it
would let a waterfall show tokens per round. But it needs a JSONB column and a UI nobody
asked for. `spans` already carries per-round durations; per-round tokens go into
`spans.meta` where they cost nothing extra.

**Rejected — leaving `messages.tokens_in/out` as the only store.** That column is per
*message*; the unit of cost is a *turn*, which may contain several model rounds plus
background calls that produce no message at all. The two are kept: `messages` stays as-is
for the visible reply, `turns` becomes the accounting record.

**Rejected — counting tokens locally with a tokenizer.** Requires a per-model tokenizer
dependency, and would still disagree with the provider. `telemetry.approx_tokens` stays
what it is — a labelled estimate for the per-block context breakdown, never for billing.

---

## Decision 4 — Traces are written after the response, never during

Trace persistence happens **after** the final SSE event, in its own DB session, wrapped so
that any failure is logged and swallowed.

This is the same discipline `memory.extract_and_store` already follows, and for the same
reason: an observability system that can slow down or break the thing it observes is worse
than no observability system. A test asserts that a trace-write failure does not affect the
reply.

**Rejected — writing spans incrementally as stages complete.** Would survive a crash
mid-turn, at the cost of ~8 DB round-trips interleaved with streaming, on a shared
connection, on a 1 GB VM. A crashed turn losing its trace is an acceptable trade; a slower
reply is not.

**Rejected — an in-memory queue with a background flusher.** Better throughput, real
complexity (loss on restart, ordering, backpressure), for a single-user app whose peak load
is one message at a time.

---

## Decision 5 — Retention: raw spans expire, daily rollups are forever

Raw `spans` are pruned after a window; `turns` are kept longer; a `daily_usage` rollup is
kept indefinitely.

This is ordinary hygiene for a table written on every turn, on a host with 10 GB of disk —
not a reaction to the backup question, which Narendra has deliberately deferred. At ~8
spans per turn, spans dominate row count while carrying the least long-term value: nobody
asks about the latency of one turn from eight months ago, but "what did I spend in March"
matters indefinitely. Rolling up rather than deleting keeps the answer to the second
question while discarding the data behind the first.

Pruning runs as a lightweight periodic sweep. When the scheduler lands (next change), it
moves to a proper job; until then it runs opportunistically and idempotently.

**Rejected — no retention, revisit when it hurts.** The point at which it hurts is a full
disk on a box with no backup.

**Rejected — Postgres partitioning by month.** The correct answer at volume, and vastly
overbuilt for one user. A `DELETE ... WHERE started_at < now() - interval` is sufficient
and obvious.

---

## Decision 6 — The knowledge map is a kNN force graph, not a projection

**Narendra's decision.** Nodes are facts; edges come from pgvector cosine-kNN; the browser
runs a force simulation to lay them out.

Beyond the visual preference, this wins on architecture. The server sends **nodes and edges
only** — a few tens of KB. The 768-dimensional vectors never leave the database, so the
distance maths happens where the data already is. And an edge is *explainable*: "these two
facts are semantically close" is a claim a person can check.

> **Corrected during task 1.4.** An earlier draft said the HNSW index from migration 002 is
> what makes neighbour lookup cheap. `EXPLAIN` disproves that: with `user_id`, `status` and
> `deleted_at` predicates present, Postgres uses the btree partial index plus a sort and
> **never touches HNSW** — correctly, since pgvector can only use HNSW when it drives the
> scan. What actually makes this cheap is **scale**: a few hundred vectors sort in
> microseconds. HNSW starts paying at thousands, and the query is already written so that
> it can be used then without a rewrite.

**Rejected — PCA projection (server-side).** Metrically more honest: screen distance would
approximate semantic distance. But it requires `numpy` — a new backend dependency — or
shipping ~600 KB of raw vectors to the browser for a client-side implementation. It is also
a *linear* projection of a 768-d space, so clusters overlap in ways that are misleading in
a different direction, and a PCA coordinate cannot be explained to the person reading it.

**Rejected — UMAP / t-SNE.** Best-looking cluster structure by a wide margin, and
completely impractical here: `umap-learn` pulls in `numba`, `scipy` and `scikit-learn` —
hundreds of MB on a 1 GB VM — to lay out a few hundred points.

**Rejected — PCA seeding the force layout (the "both" option).** Genuinely the best result
and offered as an option; not chosen. It still costs the `numpy` dependency and gives two
systems to reason about when a layout looks wrong.

**Rejected — landmark/pivot MDS in pure SQL** (coordinates as cosine distance to two
well-separated facts). Clever, no dependencies, and the quality is poor enough that it
would need explaining away rather than explaining.

### 6b — Category is a filter, not a node colour

An earlier draft of task 4.5 said "colour = category". **Measurement killed it.**

A force graph is a *scatter* form: any node can end up beside any other, so every pair of
category colours must be distinguishable — the all-pairs case, not the adjacent-pairs case
that bar and line charts get to use. Six categorical hues cannot clear that bar. Four
candidate six-hue palettes were run through the validator against this app's own surfaces
and every one failed, worst normal-vision ΔE **7.1–13.7** against a floor of 15 — i.e.
readers *with full colour vision* could not reliably tell two categories apart. This is not
a tuning problem: the reference palette this method ships validates only its **first three**
slots under all-pairs.

So the graph is **one series**:

| Channel | Carries |
|---|---|
| node fill | nothing — a single accent (`#c15f3c` light, `#d1704e` dark) |
| node radius | confidence |
| node ring | `stated` vs `inferred` — two states, not six |
| **category** | **a filter row above the canvas**, plus the text label in the detail panel and list |

This is also a better visualisation. The graph's job is showing *what relates to what* — the
clustering is the information, and six competing hues fight it. Category is metadata, and
metadata belongs in a filter.

`#d1704e` rather than the app's `--primary` `#d97757` in dark mode: the latter measures
OKLCH L 0.672, just outside the 0.48–0.67 dark band. `#d1704e` is the nearest step that
passes, and both modes clear 3:1 against the card surface.

**Rejected — six hues plus a redundant shape channel.** Shape would fix colour-blind
readers, but the method is explicit that secondary encoding does not excuse a
normal-vision failure. Two categories that look the same to everyone are not rescued by
also being a square and a triangle.

**Rejected — faceting into six small-multiple graphs.** The standard escape for too many
series, and here it destroys the point: cross-category edges are the most interesting thing
in the picture, and faceting cuts exactly those.

---

## Decision 7 — Editing a fact supersedes it; it never overwrites

Editing writes a **new** `profile_facts` row and marks the old one
`status='superseded', superseded_by=<new id>`.

This finally uses the column the schema has carried since migration 001, and it is what
makes the dedup gate able to tell **"repeat"** from **"changed"**. Cosine distance alone
cannot: "works at Company A" and "works at Company B" are near-identical sentences, so a
changed fact looks exactly like a duplicate — today it is either silently dropped or stored
as a second contradicting `active` fact.

Recall is unaffected: it already filters `status='active'` (`memory.py:55`), so a superseded
fact stops reaching the model the moment it is superseded — no change to the recall query
is needed, which §0 verifies before anything is written.

The gain is a history view: *"you used to prefer X"* is a genuinely interesting thing to be
able to see, and it is free once the chain exists.

**Rejected — updating the row in place.** Simplest, and destroys the only record that the
belief ever changed. For a system whose value is remembering, forgetting *that* it changed
its mind is the wrong thing to optimise away.

**Rejected — an `audit_log` table for fact edits.** A second mechanism for what
`superseded_by` was designed to express, and it would not participate in recall filtering.

---

## Decision 8 — The extraction prompt reuses the recall it already paid for

`handle_message` already embeds the user's message and retrieves the top-`k` relevant facts
for recall. Those facts are passed to `extract_and_store` instead of it calling
`_load_active_facts()` and inlining the entire table.

**Zero additional provider calls** — the embedding and the kNN query have already happened
by the time extraction is scheduled. The prompt goes from unbounded to `k` facts.

The safety argument is that the "don't repeat yourself" instruction was never the real
guarantee. `_too_similar()` is, and it queries **the whole table by cosine distance**,
entirely independently of what the prompt contained. Narrowing the prompt narrows a soft
hint, not the guarantee. A test asserts dedup still holds when the known block is truncated.

**Rejected — capping at the N most recent facts.** Bounded, trivial, and recency is the
wrong axis: the fact most likely to be duplicated is the one most *similar* to what is being
discussed, which is exactly what the recall vector already selects for.

**Rejected — dropping the known-facts block entirely.** The hard gate would still prevent
duplicates, but the extractor would propose them constantly, wasting output tokens and
making the extraction logs unreadable.

**Rejected — leaving it unbounded and just measuring it.** Shipping the meter while
knowingly leaving the leak running. The fix is a signature change and a deleted function.

---

## Decision 9 — Charts are hand-written SVG

**Narendra's decision.** Four chart types — area, bar, waterfall, sparkline — written
directly as SVG, roughly 250 lines.

Colours are `var(--primary)`, `var(--muted-foreground)` and friends, so light and dark are
correct **by construction** rather than by override. This is the same trade the project
already made for `Select` and `DatePicker`: build the primitive, own the behaviour, keep
the dependency list at zero. The per-turn waterfall — the most valuable view on the page —
is custom work under any charting library anyway.

**Rejected — Recharts (~100 KB gzipped).** Solves axes, tooltips, legends and responsive
containers. It would also be the frontend's first runtime charting dependency, ships a
generic visual language needing per-component theme overrides, and does not do waterfalls.

**Rejected — a canvas charting library.** All of the above, minus text selection and
accessibility.

---

## Decision 10 — Insights and Knowledge are read-mostly pages behind the same auth

Both mount as new `View`s in `Sidebar.tsx` (`"knowledge"`, `"insights"`), behind the same
`get_current_user` dependency as every other route. No new auth concept, no admin role — a
single-user app where the only user is the owner of all of it.

Knowledge is **read-write** (edit, confirm, forget, restore). Insights is **strictly
read-only**: nothing on it mutates anything, which keeps it safe to open, safe to reload,
and safe to leave open.

**Rejected — putting Insights inside Settings.** Settings is for *choices*; Insights is for
*observation*. Burying a page you should look at weekly inside one you touch twice a year
guarantees it goes unread.

**Rejected — a separate admin app or a `/metrics` scrape endpoint.** A Prometheus endpoint
would be the right answer if something were scraping it. Nothing is, and adding a scraper
is Decision 1's rejected hosting problem again.
