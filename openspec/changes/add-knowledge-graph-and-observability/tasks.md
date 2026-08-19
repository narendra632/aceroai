> Two modules in one change, phased so each is independently shippable. **§4 is the
> knowledge cut line; §8 is the observability cut line** — either can ship without the
> other if this runs long.
>
> Defect letters **(A)**, **(B)**, **(C)** refer to `proposal.md`.

## 0. Verify before building

Everything here contradicts something a later task assumes. Verify first, correct the
artifacts if a premise is wrong, then build.

- [x] 0.1 ✅ **Holds.** `ProfileFact` is read in exactly one application module,
      `core/memory.py` (plus `tests/conftest.py`). All three of its queries filter
      `status == "active"` — `recall_facts` (:55), `_load_active_facts` (:108),
      `_too_similar` (:124). No route, tool or service reads it. **Decision 7 is safe:
      superseding removes a fact from context with no change to the recall query**
- [x] 0.2 ✅ **Confirmed dead schema.** `superseded_by`, `source_ref` and `'stated'` appear
      *only* in migration 001 and `db/models.py` — never assigned, never read, in any
      application code. All three are wired up by this change
- [x] 0.3 ✅ **Defect (B) reproduced** in `tests/test_usage_accounting.py`. A two-round turn
      billed 2,500 in / 130 out records **1,500 / 90** — round 2 only, losing **60% of
      input tokens**. Written as `xfail(strict=True)` so the suite stays green *and* an
      unexpected pass after the fix forces the marker's removal
- [x] 0.4 ✅ `thoughts_token_count` **is** present on `GenerateContentResponseUsageMetadata`,
      alongside `cached_content_token_count`, `tool_use_prompt_token_count` and
      `total_token_count` — so `tokens_cached` is populatable too.
      ⚠ **Unverified without a live call:** whether streaming chunks carry *cumulative* or
      *delta* usage. Current assign-on-every-chunk produces sane single-round numbers,
      which only holds if cumulative. **Implement as: last-write-wins within a round, sum
      across rounds** — and confirm against a real turn in 10.4 before trusting the totals
- [x] 0.5 ⚠ **This task's own premise was wrong.** OpenAI's `completion_tokens` **does**
      include reasoning (`completion_tokens_details.reasoning_tokens` is a subfield) — but
      that makes `tokens_thinking` **available on both providers, not Google-only**. To keep
      them comparable: Google `tokens_out = candidates_token_count` (already excludes
      thinking); OpenAI `tokens_out = completion_tokens − reasoning_tokens`. Both then mean
      *visible output*. 5.3's "Google-specific" note is void
- [x] 0.6 ✅ **Measured against the dev DB (11 active facts, mean 52 chars):** the
      `known_block` costs **144 tok/message today**, projecting to 1,311 at 100 facts,
      2,622 at 200, and **6,556 at 500**. Bounded to `memory_recall_k=12` it is **157 tok,
      constant**. ⚠ **Honest reading: this changes nothing today** — at 11 facts the cap is
      not even reached. Its entire value is converting a line that grows forever into a flat
      one. Do not present it as a present-day saving
- [x] 0.7 ✅ `radix-ui@1.6.7` exports all of `Popover`, `Tabs`, `Slider`, `ScrollArea`,
      `Dialog`, `Toast`, `Select`, `Tooltip`, `Separator`, `Toggle`, `ToggleGroup`.
      **No dependency needed**, as claimed
- [x] 0.8 ✅ `main.py:19` sets the **root** logger to INFO and `httpx` logs request URLs at
      `logger.info`. Telegram embeds the bot token in the URL path, so **the token is
      written to logs** locally and in production. Nothing we rely on logs at httpx INFO

## 1. Migration 005 — memory lifecycle

- [x] 1.1 ✅ `deleted_at` + partial index `WHERE deleted_at IS NULL AND status = 'active'` (matches the recall query's shape, or the index is unusable)
- [x] 1.2 ✅ `updated_at`, backfilled from `created_at` so no reader special-cases NULL
- [x] 1.3 ✅ both columns on `ProfileFact`, with the migration-004 'readers MUST filter' comment
- [x] 1.4 ⚠ **Finding: HNSW is not used by recall — and was not before this change.**
      `EXPLAIN` with `enable_seqscan=off` shows the planner choosing
      `ix_profile_facts_user_live` (btree) **+ Sort**, never `profile_facts_embedding_hnsw`.
      That is correct: pgvector can only use HNSW when it *drives* the scan, and three
      filter predicates (`user_id`, `status`, `deleted_at`) would risk post-filtering its
      results away. **No regression — before 005 there was no index on
      `profile_facts.user_id` at all, so this strictly improves the filter path.** Sorting a
      few hundred vectors is microseconds; HNSW only pays at thousands+. `design.md`
      Decision 6 corrected, since it claimed HNSW is what makes the graph query cheap

## 2. `services/memory.py` — the single home for every fact rule

- [x] 2.1 ✅ `services/memory.py` created; `core/memory.py` keeps extraction + recall
- [x] 2.2 ✅ `live()` is the single filter, **imported by `core.memory`** so recall and the API cannot disagree
- [x] 2.3 ✅ category / status / source / min_confidence / q (escaped ILIKE) / limit / offset
- [x] 2.4 ✅ owner-scoped; a forgotten fact 404s exactly like one that never existed
- [x] 2.5 ✅ `supersede_fact` re-embeds via a caller-supplied vector (the `recall_facts` convention — services stay sync)
- [x] 2.6 ✅ `confirm_fact` — the first write of `source='stated'` in the project's history
- [x] 2.7 ✅ `forget_fact` / `restore_fact`, idempotent, owner-scoped
- [x] 2.8 ✅ `neighbours()` — one lateral-join query, undirected + deduplicated, distance cutoff, **never returns vectors**
- [x] 2.9 ✅ `stats()` — counts by category/source/status + per-day growth
- [x] 2.10 ✅ 18 tests in `test_services_memory.py`; the recall-path assertion is the one that matters
- [x] 2.11 ✅ supersession is owner-scoped and leaves recall immediately

## 3. Memory correctness — provenance and contradiction

- [x] 3.1 ✅ `_persist_user_turn` now returns `(session_id, user_message_id)`
- [x] 3.2 ✅ `_store` writes `source_ref`; stays nullable for facts with no conversational origin
- [x] 3.3 ✅ **Solved without an extra provider call** — the extractor emits an optional `replaces` key naming the fact it supersedes. It is already reading both, so only it can judge; cosine distance provably cannot. Unmatched hints are ignored rather than guessed at
- [x] 3.4 ✅ `test_changed_fact_supersedes_instead_of_being_dropped` — old and new sit at the *same* vector, so this fails without `replaces`
- [x] 3.5 ✅ repeats still dedup and create no supersession chain

## 4. Knowledge page — ⛳ knowledge module ships here

- [x] 4.1 `api/memory.py` — `GET /api/memory/facts`, `GET /api/memory/graph`,
      `GET /api/memory/stats`, `PATCH /api/memory/facts/{id}`,
      `POST /api/memory/facts/{id}/confirm`, `DELETE /api/memory/facts/{id}`,
      `POST /api/memory/facts/{id}/restore`. Thin routes; all logic in `services/memory.py`
- [x] 4.2 Register the router in `main.py`; add schemas to `api/schemas.py`
- [x] 4.3 `lib/api.ts` client functions
- [x] 4.4 `ui/force-graph.tsx` — canvas renderer + a hand-written force simulation
      (repulsion, spring, centring), **deterministically seeded** so the layout is stable
      across reloads. Pan, pinch-zoom, click-to-select
- [x] 4.5 ⚠ **Rewritten — "colour = category" was measured and rejected.** A force graph is
      a scatter form, so all colour pairs must separate; four candidate six-hue palettes all
      failed against this app's surfaces (worst normal-vision ΔE 7.1–13.7 vs a floor of 15).
      **The graph is one series:** single accent fill, radius = confidence, ring = `stated`
      vs `inferred`, and **category becomes a filter** above the canvas *(design.md 6b)*.
      Legend explains radius and ring, because an unexplained encoding is decoration
- [x] 4.6 `KnowledgeView.tsx` — **list ⇄ graph toggle, list default under `sm`**
      *(Decision 6; the list is the accessible equivalent, not a fallback)*
- [x] 4.7 Fact detail panel in `ui/sheet.tsx`: text, category, confidence, source,
      **provenance** — "Learned 3 Aug, from this conversation" linking to the session — and
      Edit / Confirm / Forget
- [x] 4.8 Forget → optimistic removal + **Undo toast** via `useOptimisticList`, matching
      every other delete in the app
- [x] 4.9 Supersession history — a superseded fact is reachable from its replacement
      ("previously: …"), otherwise 2.5 preserves history nobody can see
- [x] 4.10 Timeline scrubber replaying memory growth by `valid_from`
- [x] 4.11 Search + category/source/status filters
- [x] 4.12 Loading skeleton, empty state, **error state**. Empty must read as "nothing
      learned yet", never as a failed request rendered as emptiness
- [x] 4.13 Sidebar entry (`View = "knowledge"`, Brain icon); mobile layout verified at
      375 px with no horizontal overflow
- [x] 4.15 ⚠ **Graph density was measured against real embeddings and the defaults were
      wrong.** Against 11 real facts every pair falls between **0.13 and 0.48** — real
      embeddings of one person cluster far tighter than the 0..1 range suggests — so the
      planned 0.55 cutoff excluded nothing (31 of a possible 55 edges: a hairball).
      Retuned to **k=3, max_distance=0.32** (~18 edges, clusters legible) and the control
      was surfaced in the UI, since the data proves it changes what you see. Calibration
      pairs: "uses VS Code" ↔ "uses the Claude Code extension" **0.130**, and
      "has sisters" ↔ "celebrates Rakshabandhan" **0.189** — *sharing no words at all*
- [x] 4.16 ⚠ **Growth rate corrected, and the ceiling raised to 800 on Narendra's call.**
      My "200 facts is ~2 years away" was wrong by an order of magnitude — the real rate is
      **11 facts in 2 days (~5/day)**, putting 200 about a *month* out. Split the single
      overloaded `LIST_LIMIT` into three constants governed by different things:
      `PAGE_SIZE=100` (a scrolling decision), `LIST_MAX=500` (request ceiling),
      `GRAPH_LIMIT=800` (a frame-budget measurement)
- [x] 4.17 ⚠ **The 800 ceiling exposed a server-side wall the browser benchmark had hidden.**
      The graph's kNN edge query is N x N *in Postgres*: measured **4.9 s at 800 facts** on a
      desktop, which would be far worse on the e2-micro. Root cause is the one task 1.4
      identified — no index matched the query's predicates, so HNSW was unusable.
      **Migration 006** adds `profile_facts_live_hnsw`, a partial HNSW index whose `WHERE`
      matches `deleted_at IS NULL AND status = 'active'`: **5619 ms -> 170 ms (33x)**, plan
      confirmed as `Index Scan`. The old full index from 002 is dropped — no query could use
      it, and two HNSW indexes double every insert's cost. **Recall gets the same speedup**,
      on every message
- [x] 4.18 ⚠ **Known: a planner-crossover hump between ~300 and ~700 facts.** Below the
      crossover Postgres picks `Seq Scan + top-N heapsort` (2 ms per lookup x N lookups);
      above it, `Index Scan` (0.66 ms). Measured 99 ms @100 -> 277 ms @200 -> **1111 ms @400**
      -> 243 ms @800 -> 227 ms @1200. It is a temporary hump that self-corrects, and
      `enable_seqscan=off` does **not** shift it (the HNSW cost estimate stays higher). Not
      worth fighting; the durable fix is precomputing edges on write, recorded in ROADMAP
- [x] 4.19 List pagination: 100 per page with **Load more**, applied **server-side** so it
      continues within the active category/search rather than paging everything and
      filtering the leftovers. Tests cover overlap, gaps, and category leakage
- [x] 4.20 The Barnes-Hut trigger is surfaced **in the UI** at 80% of the ceiling — before
      anything is hidden — because a note in a document gets read once and never re-read.
      `graph_warn_at()` is a function, not a constant: a threshold derived at import time
      silently goes stale when the limit changes (caught by a test)
- [x] 4.14 ✅ **Checkpoint — Narendra reviews the Knowledge page over HMR before §5 starts**

## 5. Trace capture — and the three accounting defects

- [x] 5.1 ✅ **Migration 006:** `turns` (id, user_id, session_id NULL, channel, kind, provider,
      model, effort, started_at, duration_ms, ttft_ms, rounds, tokens_in, tokens_out,
      **tokens_thinking**, tokens_cached, cost_usd, pricing_version, ok, error_type) and
      `spans` (id, turn_id, name, seq, duration_ms, meta JSONB). Index `turns(started_at)`,
      `turns(user_id, started_at)`, `spans(turn_id)`
- [x] 5.2 ✅ CHECK constraint on `turns.kind` (`'chat'`, `'memory_extract'`, `'embed'`,
      `'job'`) — `Text` + CHECK, never a Postgres enum (golden rule 7)
- [x] 5.3 ✅ **Fix (A) — and normalise it across providers** *(rewritten by 0.5; it is **not**
      Google-only)*. `tokens_out` must mean *visible output* on both:
      Google `tokens_out = candidates_token_count` (already excludes thinking),
      `tokens_thinking = thoughts_token_count`;
      OpenAI `tokens_thinking = completion_tokens_details.reasoning_tokens`,
      `tokens_out = completion_tokens − reasoning_tokens`.
      Also capture `tokens_cached` (`cached_content_token_count` /
      `prompt_tokens_details.cached_tokens`) — cached input bills at a lower rate
- [x] 5.4 ✅ **Fix (B):** usage accumulates across rounds. ⚠ **Per 0.4, the two levels differ:
      within one round take the last reported value (providers report cumulative totals per
      request); across rounds, sum.** Naively adding every chunk would wildly overcount.
      Then: delete the defect-pinning test and remove the `xfail` marker in
      `tests/test_usage_accounting.py`, so 0.3's expected total becomes a live assertion
- [x] 5.5 ✅ **Fix (C), part 1:** add `usage: dict | None` to `complete()` and `embed()` in
      `providers/base.py` and both implementations. *This is the contract gap that made the
      defect possible — there was nowhere to put the number*
- [x] 5.6 ✅ **Fix (C), part 2:** `core/memory.py` opens its own `turns` rows —
      `kind='memory_extract'` for the extractor call, `kind='embed'` for recall and
      fact-embedding — so background spend is attributed rather than merely counted
- [x] 5.7 ✅ `telemetry.Timeline` gains `persist(db, ...)` writing one `turns` row + one
      `spans` row per stage. **After the final SSE event, own session, failures swallowed
      and logged** *(Decision 4)*
- [x] 5.8 ✅ Wire into `handler.handle_message` — including the error path, so failed turns
      are recorded with `ok=false` and `error_type`. A dashboard that only shows successes
      hides the thing you most need to see
- [x] 5.9 ✅ Count what is currently logged and lost: `llm.py` retry attempts, and
      `_too_similar` dedup rejections → `spans.meta`
- [x] 5.10 ✅ **Test: a trace-write failure does not affect the reply** *(Decision 4 is only
      true if this passes)*
- [x] 5.11 ✅ Test: no prompt or response **text** is written to `turns` or `spans` — shapes
      and counts only *(a non-goal that needs enforcing, not just stating)*

## 6. Bound the extraction prompt

- [x] 6.1 ✅ handler passes the already-recalled facts into `extract_and_store`
- [x] 6.2 ✅ `_load_active_facts` deleted; a test asserts it cannot come back
- [x] 6.3 ✅ `test_dedup_holds_even_when_the_known_block_is_empty` — the extractor is shown nothing and still cannot duplicate
- [x] 6.4 ✅ **Re-measured 2026-08-19, recorded in `docs/REQUEST-ANATOMY.md`.** The block
      had already grown from 144 tok (11 facts, 16 Aug) to **275 tok (22 facts)** in three
      days of ordinary use — the growth was real, not theoretical. Bounded: **~150 tok,
      constant**. Still saves nothing today; its value is the shape of the line
- [x] 7.1 ✅ `core/pricing.py` — dated catalog: `{provider/model: [PriceRow(valid_from,
      input_per_mtok, output_per_mtok, cached_input_per_mtok)]}`, plus `PRICING_VERSION`
- [x] 7.2 ✅ `estimate_cost(...)` — resolves the rate effective at the turn's timestamp;
      **thinking tokens billed at the output rate**
- [x] 7.3 ✅ Unknown model → cost `NULL`, not `0`. **Zero is a lie that silently understates
      the total; null is a visible gap that gets fixed**
- [x] 7.4 ✅ Test: a price added with a later `valid_from` does not change an existing turn's
      stored cost *(Decision 2 — the whole reason cost is frozen)*

## 8. Insights page — ⛳ observability module ships here

- [x] 8.1 ✅ **Shipped as ONE route, deliberately.** `GET /api/insights/overview` returns
      everything the page needs; `/turns` and `/turns/{id}` serve the table and waterfall.
      Six separate calls would each pay the same cold-connection cost to a VM in Oregon —
      the queries are cheap, the round-trips are not. Original wording below:
      ~~`GET /api/insights/summary`, `/series`, `/by-model`,~~
      `/turns`, `/turns/{id}`. **Read-only; nothing on this page mutates anything**
      *(Decision 10)*
- [x] 8.2 ✅ Aggregates computed in SQL, not Python — do not pull a month of rows into memory
      on a 1 GB VM
- [x] 8.3 ✅ `ui/chart.tsx` — hand-written SVG: area, bar, sparkline. Theme tokens only, so
      dark mode is correct by construction *(Decision 9)*
- [x] 8.4 ✅ `ui/waterfall.tsx` — **the hero view**: one turn's spans as proportional
      horizontal bars. This is what made the 12 s embedding stall obvious in raw logs;
      here it is a click
- [x] 8.5 ✅ **Checkpoint — Narendra reviews the charts against real data before the page is
      assembled.** Hand-built charts are where a "finished product" bar quietly slips, and
      the time-series is the one with real exposure *(Decision 9)*. If the area chart
      disappoints, `ui/chart.tsx` has a fixed interface and that **single** chart can be
      swapped to a library without touching the page
- [x] 8.6 ✅ `InsightsView.tsx` — headline tiles (spend this month, turns, median latency,
      error rate), spend-over-time, cost by model and by kind, latency **p50/p95** (never a
      mean — one 30 s turn makes an average meaningless), error taxonomy
- [x] 8.7 ✅ Recent-turns table → click → waterfall
- [x] 8.8 ✅ **Every cost figure labelled an estimate**, with the pricing version reachable.
      Google bills through Cloud Billing; we never see the invoice *(Decision 2)*
- [x] 8.9 ✅ **Provider comparison** — cost, latency and error rate per provider side by side,
      so switching provider in Settings becomes an evidence-based choice. The data is
      already there (`turns.provider`); this is the view that makes it worth having
- [ ] 8.10 ⚠ **DROPPED on Narendra's instruction.** Built, then removed: "the finished
      product does not have these kind of lines". A page that has always been watching is
      the normal case; saying so in prose reads as a release note that is true this week
      and noise next month. ~~State the **data start date** on the page~~ — traces begin at deploy, and a chart
      that implies it has always been watching is misleading *(no backfill: Narendra's
      decision)*
- [x] 8.11 ✅ **Built (migration 009).** A monthly ceiling on `users.monthly_budget_usd`,
      NULL = off so nothing changes for an account that never sets one. Checked in
      `handle_message`, so web and Telegram are both covered by one check. Counts
      EVERYTHING — replies, recall, extraction — because that is what the provider bills;
      counting only visible replies would let a third of the calls escape. Warned at 80%,
      composer locked with a Change limit button at 100%, raised from Settings with
      immediate effect. A refusal writes no `turns` row: no model call was made, and
      inventing one would inflate the error rate on the page next door
- [x] 8.12 ✅ Loading, empty and error states; empty reads as "no data yet", not as failure
- [x] 8.13 ✅ Sidebar entry (`View = "insights"`, Activity icon); verified at 375 px — charts
      scroll inside their own container, the page never scrolls horizontally

## 9. Retention and hygiene

- [x] 9.1 ✅ `services/retention.py` — three tiers (spans 30d, turns 400d, `daily_usage`
      forever); `sweep()` always rolls up **before** it prunes; a turn is deleted only if
      its own day is in the rollup
- [x] 9.2 ✅ `maybe_sweep()` runs at most once per local day from `telemetry.record`,
      which already runs off the reply path and swallows everything. Idempotent, so a
      restart causing an extra sweep is harmless. TODO(scheduled-jobs) names its future home
- [x] 9.3 ✅ Done earlier, in the secret-leak commit — `httpx` at WARNING plus a
      redacting formatter, because the token appeared by **two** independent paths
- [x] 9.4 ✅ `DEPLOY.md` gains a Trace retention section with **measured** per-row cost
      (turns 319 B, spans 183 B → ~35 MiB steady state); both windows in `.env.example`
- [x] 10.1 ✅ ruff format + check clean
- [x] 10.2 ✅ `uv run pytest` — **242 passed**
- [x] 10.3 ✅ `npm run build` clean (NOT `tsc --noEmit` — `tsconfig.json` has `files: []`,
      so it checks zero files and passes a broken build); `npm run lint` clean bar one
      pre-existing fast-refresh warning
- [x] 10.4 ✅ 128 recorded calls: 50 chat, **47 embed, 31 memory_extract** — the
      background spend, now attributable. 0.4 settled: usage is reported **once, at the
      end**, so assignment (`set_usage`) is correct and summing chunks would overcount
- [x] 10.5 ✅ A real two-round turn recorded `in=2634` across `llm_round1 → tool:create_task
      → llm_round2`, not the last round alone
- [x] 10.6 ✅ Covered by named tests: `test_editing_text_supersedes_and_re_embeds`,
      `test_superseded_fact_leaves_recall_immediately`,
      `test_superseded_facts_are_reachable_as_history`
- [x] 10.7 ✅ No fixed widths on either page; the one wide table scrolls in its own
      container; the graph falls back to the list below 640 px. Confirmed visually by
      Narendra on a narrow window
- [x] 10.8 ✅ All **eight** migrations apply cleanly to an empty database (scratch DB
      created and dropped), and 008 applied cleanly to the dev database holding real rows.
      Production applies them on deploy via the compose `migrate` service
- [x] 10.9 ✅ `.env` confirmed unstaged before every commit
- [x] 11.1 ✅ `ARCHITECTURE.md`: three tables in the erDiagram + Mermaid flows for the
      knowledge map and trace capture; `AGENTS.md` Layout updated; `ROADMAP.md` moves both
      modules to Done and states what observability does **not** do; `REQUEST-ANATOMY.md`
      gains 6.4's before/after
- [x] 11.2 ✅ `backend/README.md` — `api/memory.py`, `api/insights.py`, `core/pricing.py`,
      the new services, and 10 tables
- [x] 11.3 ✅ `docs/INSIGHTS.md` — why p95 and not an average (the 6-second average that
      describes nothing), why cost is an estimate, what the waterfall shows, how far back it
      goes, and what the page deliberately does not do
