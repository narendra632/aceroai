# Tasks

Findings get recorded inline as work proceeds, with ⚠ wherever a premise turns out to be
wrong. A task that cannot be done as written is annotated, never quietly ticked.

## 0. Repair the diagrams this is built from *(Decision 9)*

Four defects found by auditing all eleven Mermaid diagrams. Three were introduced by the
change archived on 2026-08-23.

- [x] 0.1 `ARCHITECTURE.md` — sections run **(a) (b) (c) (e) (d) (e)**. Re-letter so the
      recall section is `(d)`, the knowledge map `(e)`, trace capture `(f)`, and move the
      recall section after the memory section it belongs with
      → the recall section was already positioned correctly; only the letters were wrong.
      Now (a)…(f) in order, and the cross-reference from §(c) points at (d)
- [x] 0.2 `ARCHITECTURE.md` §2 — the `api/` node omits the **memory** and **insights**
      routers (7 routers are registered in `main.py`, 5 are drawn). The `core/` box omits
      **recall**, which is now its own module
      → all routers drawn (including `learn`, added by this change), and `recall` is its
      own node with an edge from `memory`. `memory → services` added too: the one writer
      lives in `services/`, and the old diagram showed only tools reaching it
- [x] 0.3 `ARCHITECTURE.md` §4a sequence — add the **budget check**, which runs *before*
      the user message is persisted, and the **`recall` SSE event**. The diagram currently
      shows a turn that cannot be refused and a recall the browser never hears about
      → budget check drawn as an `alt` that ends the turn with an `error` event and no
      persistence; recall now shows the term-frequency probe, both searches, and the
      `recall` event going back to the browser
- [x] 0.4 `REQUEST-ANATOMY.md` — node id **`U2` is declared twice** with different labels
      (`UI can show which facts were used` and `reply complete`). Mermaid keeps one and
      silently drops the other. Rename the second to `U3`
      → renamed, and the budget check added here too for the same reason as 0.3
- [x] 0.5 `DEPLOYMENT-EXPLAINED.md` — the prose still says recall is a "vector search";
      it is two searches now. Diagram itself is correct
- [x] 0.6 Record what the audit found **correct**, so it is not re-checked later: four
      containers matches `docker-compose.prod.yml`; the CI→GHCR→SSH→migrate→api chain
      matches `ci.yml`; the tool-use loop, memory write flow and knowledge-graph flow are
      accurate; all ten tables in the ER diagram match `db/models.py`
- [x] 0.7 Render every repaired diagram and confirm it parses — a Mermaid syntax error
      shows as a blank block on GitHub, which is exactly how 0.4 survived
      → done better than "render and look". `tests/test_docs_diagrams.py` checks all
      eleven structurally on every CI run: duplicate node ids with different labels, edges
      to undeclared nodes, unbalanced brackets, sequence messages to undeclared
      participants, fences that are not diagrams, and the section lettering from 0.1.
      **45 checks, all passing.** No `mermaid-cli` — it would pull Puppeteer and a headless
      Chromium into CI to catch strictly less
- [x] 0.7a **Test the tests.** Each defect was re-introduced synthetically to prove the
      guard fires. ⚠ One did **not**: `test_every_edge_connects_declared_nodes` was passing
      **vacuously** — the edge pattern expects an id where `A["label"] --> B` has a `]`, so
      it matched zero edges and asserted nothing. Fixed by stripping labels before matching.
      A guard nobody has tried to trip is not a guard
- [x] 0.7b ⚠ The bracket-balance check failed on a **correct** ER diagram: `||--o{` is
      crow's-foot cardinality, not braces. Cardinality is stripped before counting.
      Recorded because the first instinct was to look at the diagram, not the checker

## 1. The live constants endpoint *(Decision 2)*

- [ ] 1.1 `api/learn.py` — `GET /api/learn/constants`, read-only, behind `get_current_user`
      like every other route *(Decision 8)*
- [ ] 1.2 An **explicit allow-list** of settings, never `settings.model_dump()`. Limits,
      thresholds and windows only. **No key, URL, model name tied to a key, or anything
      from `.env`** — the allow-list is the security boundary and it must be readable at a
      glance
- [ ] 1.3 Include at least: `recall_k`, `recall_pool`, `rrf_k`, `vector_only_max`,
      `lexical_only_max`, `lexical_terms_max`, `memory_dedup_distance`,
      `vector_only_max_distance`, `consensus_max_distance`, `tools_max_iters`,
      `context_tasks_limit`, `history_limit`, `graph_limit`, `graph_max_distance`,
      `embed_dim`, `span_retention_days`, `turn_retention_days`, `memory_recall_timeout_s`,
      `max_input_chars`
- [ ] 1.4 `LearnConstants` response schema — every field typed, so a removed setting is a
      type error rather than a missing key at runtime
- [ ] 1.5 Test: the response contains **no** value that also appears in a secret-shaped
      setting. Asserted by name against a deny-list (`*_key`, `*_token`, `*_secret`,
      `*_url`, `password*`), so a future setting cannot be added to the page by accident
- [ ] 1.6 Test: every key the frontend content references is present in the response *(6.2
      depends on this)*

## 2. The click-through diagram primitive *(Decision 3)*

- [ ] 2.1 `components/ui/flow-diagram.tsx` — nodes declared with `{ id, label, hint, col,
      row, kind }`, edges as `{ from, to, label? }`
- [ ] 2.2 Nodes render as **buttons** on a CSS grid, so keyboard reach and focus rings come
      free rather than being reimplemented
- [ ] 2.3 Edges drawn in an absolutely-positioned SVG overlay, paths computed from the
      nodes' measured rects, recomputed on `ResizeObserver`. One code path for every width
- [ ] 2.4 Selected node is visibly selected, and selecting the same node again clears it
- [ ] 2.5 `kind` drives the visual treatment: `stage` · `store` · `external` · `planned`.
      **Planned nodes are muted and marked** and can never read as built *(Decision 4)*
- [ ] 2.6 375 px: the grid collapses to a single column, edges become vertical connectors,
      and the page does not scroll sideways
- [ ] 2.7 Respects `prefers-reduced-motion` — the existing `rise` animation is opt-out
      elsewhere and this must match
- [ ] 2.8 Test: every edge names nodes that exist; a dangling edge is a build failure, not
      a line drawn to nowhere

## 3. The content model *(Decision 1)*

- [ ] 3.1 `lib/learn/types.ts` — `Panel { id, title, what, how[], measured?, code[],
      reads[], concepts[] }`, `Diagram { id, title, intro, nodes[], edges[], panels }`,
      `Concept { id, title, what, how[], measured?, code[], reads[] }`
- [ ] 3.2 Text in `what`/`how`/`measured` may contain `{placeholder}` tokens; a single
      `interpolate()` resolves them against the constants response *(Decision 2)*
- [ ] 3.3 An unresolved placeholder renders as the raw token and logs — **never** as
      `undefined`, and never silently dropped. A missing number must be visible
- [ ] 3.4 `useConstants()` hook: fetch once, cache for the session, and fail soft — the
      section still renders without numbers rather than showing an error page

## 4. The content itself

Written to the budget in Decision 5: one summary line, ≤ 5 bullets, ≤ 1 measured figure.

- [ ] 4.1 **Diagram A — "How a message is answered"**: budget check → save → recall (two
      rankers) → build context → model → tool loop (tasks · journal · memory) → stream →
      save → learn in the background. Every node gets a panel
- [ ] 4.2 **Diagram B — "What it costs, and how we know"**: tokens counted per round →
      price list frozen at write time → `turns` + `spans` → daily rollup → retention prune
      → the spend ceiling that refuses a turn. Every node gets a panel
- [ ] 4.3 **Concepts**, one card each: embeddings · cosine distance · why a distance floor
      cannot work · full-text search and stemming · Reciprocal Rank Fusion · HNSW · GIN ·
      SSE streaming · the one-brain pattern · services as the single source of truth ·
      soft delete · migrations · supersession vs overwrite · tool calling · reasoning effort
- [ ] 4.4 Each concept explains **the idea first**, then how this project uses it. A card
      for "cosine distance" must make sense to someone who has never seen this codebase
- [ ] 4.5 **What's next** strip, sourced from the triggered-work section of `ROADMAP.md`:
      Barnes-Hut at ~1,000 facts · real BM25 at ~1,000 facts · conflict review · scheduled
      jobs · PWA + push. Marked planned, styled apart *(Decision 4)*
- [ ] 4.6 Every panel that has a deeper source links to the `docs/` file that owns it
      *(Decision 7)*. The measured numbers stay in `docs/`; the panel quotes at most one

## 5. The view

- [ ] 5.1 `components/LearnView.tsx` — the three sections plus the planned strip
- [ ] 5.2 `Sidebar`: add `learn` to the `View` union and a nav entry. Pick an icon that is
      not already in use (`Compass` / `GraduationCap` — `Brain` is taken by Knowledge)
- [ ] 5.3 `AppShell`: route the view. It holds no state worth preserving, so it needs none
      of the chat view's care
- [ ] 5.4 The explanation panel: a side panel on wide screens, a `Sheet` on narrow — the
      `Sheet` primitive already exists and already handles focus and dismissal
- [ ] 5.5 Deep-linkable: the selected node is reflected in the URL hash, so a panel can be
      pointed at. Without this, "look at this bit" means "click the third box"
- [ ] 5.6 Loading and error states, per `ui-standards` — the constants fetch is a network
      call and every list in this app already has all three states

## 6. Tests *(Decision 6)*

- [ ] 6.1 Every `code` path in the content exists on disk. This is the test that catches a
      rename
- [ ] 6.2 Every `{placeholder}` used anywhere in the content is served by `/api/learn/constants`
- [ ] 6.3 Every concept id referenced by a diagram node is defined
- [ ] 6.4 The text budget holds: title ≤ 60, `what` ≤ 140, ≤ 5 bullets of ≤ 120 *(Decision 5)*
- [ ] 6.5 Backend: the constants endpoint requires auth, and its payload is secret-free (1.5)
- [ ] 6.6 ⚠ Decide where 6.1–6.4 run. The content is TypeScript and the repo has **no
      frontend test runner** — `npm run lint` is `oxlint` and there is no vitest. Options:
      (a) add vitest, a new dependency needing approval; (b) write the checks as a Node
      script run by `npm run lint`; (c) express the content as JSON and check it from
      pytest. **Recommend (b)** — no dependency, runs in CI with what is already there.
      Confirm with Narendra before building

## 7. Documentation

- [ ] 7.1 `ARCHITECTURE.md` — a short section for the Learn view and the constants
      endpoint, and `api/learn.py` in the directory guide
- [ ] 7.2 `AGENTS.md` — `api/learn.py` and `lib/learn/` in the Layout
- [ ] 7.3 `ROADMAP.md` — move to Done; state what it does **not** do (it does not generate
      itself from the code; the prose is written and must be maintained)
- [ ] 7.4 `README.md` — add the Learn section to the "I want to…" table
- [ ] 7.5 A note in `docs/` on **how to add a concept or a node**, so the next change to the
      system can update this in the same commit rather than later. Without it, the section
      rots regardless of the tests

## 8. Verification

- [ ] 8.1 From `backend/`: `uv run ruff format .` and `uv run ruff check .` clean
- [ ] 8.2 From `backend/`: `uv run pytest` — all green
- [ ] 8.3 Frontend: `npm run build` clean (**not** `tsc --noEmit` — `tsconfig.json` has
      `files: []`, so it checks zero files and passes a broken build)
- [ ] 8.4 **Live:** every node in both diagrams opens a panel, and every panel's links work
- [ ] 8.5 **Live:** change `MEMORY_RECALL_K` in `.env`, restart, and confirm the Learn page
      shows the new number **without any content edit**. This is Decision 2's whole claim
      and it must be demonstrated, not asserted
- [ ] 8.6 **Live at 375 px:** both diagrams legible, every node selectable, no sideways
      scroll
- [ ] 8.7 Keyboard-only pass: tab to a node, activate it, read the panel, dismiss it
- [ ] 8.8 Dark mode pass on both diagrams and the panel
- [ ] 8.9 **Confirm `.env` is NOT staged** before any commit
