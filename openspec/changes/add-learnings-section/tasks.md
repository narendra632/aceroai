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

- [x] 1.1 `api/learn.py` — `GET /api/learn/constants`, read-only, behind `get_current_user`
      like every other route *(Decision 8)*
- [x] 1.2 An **explicit allow-list** of settings, never `settings.model_dump()`
- [x] 1.3 Include at least the listed values
      → 24 served. Some are **not** settings: `history_limit`, `graph_limit`,
      `graph_warn_at`, `graph_neighbours`, `graph_max_distance` and `tool_count` are module
      constants or derived, and are read from where they are defined for the same reason
- [x] 1.4 `LearnConstants` response schema — every field typed
- [x] 1.5 Test: the response contains **no** value that also appears in a secret-shaped
      setting
      → three layers: no secret *value* appears in the payload; no *field name* matches a
      secret shape; and every field must be `int` or `float`, so a string can never be
      added. Verified by deliberately leaking `jwt_secret` into a fake payload and
      confirming the guard fires
- [x] 1.6 Test: every key the frontend content references is present in the response
      → done in the content checker (6.2), which parses the response model directly

## 2. The click-through diagram primitive *(Decision 3)*

- [x] 2.1 `components/ui/flow-diagram.tsx` — nodes and edges declared as data
- [x] 2.2 Nodes render as **buttons** on a CSS grid
- [x] 2.3 Edges drawn in an SVG overlay from measured rects, recomputed on `ResizeObserver`
      → the stacked-vs-laid-out decision is taken from the **measured geometry**, not a
      media query, so it is correct inside any container rather than only at a page width
- [x] 2.4 Selected node is visibly selected, and selecting it again clears it
- [x] 2.5 `kind` drives the treatment; **planned nodes are muted and marked**
- [x] 2.6 375 px: the grid collapses to one column, edges become vertical connectors
- [x] 2.7 Respects `prefers-reduced-motion`
      → no new animation was added; the component uses transitions the app already scopes
- [x] 2.8 Test: every edge names nodes that exist
      → in the content checker, and verified against a synthetic dangling edge

## 3. The content model *(Decision 1)*

- [x] 3.1 `lib/learn/types.ts` — `Explanation`, `Diagram`, `Concept`, `Planned`, `BUDGET`
- [x] 3.2 `interpolate()` resolves `{placeholder}` against the constants response
- [x] 3.3 An unresolved placeholder renders as the **raw token**, never `undefined`
- [x] 3.4 `useLearnConstants()` — fetched once, cached at module scope, fails soft
      → cached outside React on purpose: the values cannot change while the tab is open,
      so re-fetching per visit is a request that can only return the same answer

## 4. The content itself

- [x] 4.1 **Diagram A — "How a message is answered"**, 12 nodes, every one with a panel
- [x] 4.2 **Diagram B — "What it costs, and how we know"**, 9 nodes, every one with a panel
- [x] 4.3 **Concepts** — 21 cards across memory · model · data · delivery
- [x] 4.4 Each explains the idea first, then how this project uses it
- [x] 4.5 **What's next** strip — 5 items, each with its measured trigger, styled apart
- [x] 4.6 Every panel with deeper detail links to the `docs/` file that owns it
      → **48 explanations total**, all inside the budget

## 5. The view

- [x] 5.1 `components/LearnView.tsx` — three sections plus the planned strip
- [x] 5.2 `Sidebar`: `learn` added to `View`, with the `Compass` icon (`Brain` is Knowledge's)
- [x] 5.3 `AppShell`: routed
- [x] 5.4 Side panel on wide screens, `Sheet` below `lg`
      → ⚠ the `Sheet` primitive renders its own title and close button, so the panel was
      split into a headless `PanelBody`. One component with two headers would have shown
      the title twice on a phone
- [x] 5.5 Deep-linkable via the URL hash
- [x] 5.6 Fails soft rather than showing an error state — see 3.4

## 6. Tests *(Decision 6)*

- [x] 6.1 Every `code` path in the content exists on disk
- [x] 6.2 Every `{placeholder}` is served — checked against the response model in
      `schemas.py`, so it runs offline and in CI
- [x] 6.3 Every concept id referenced by a node is defined
- [x] 6.4 The text budget holds
- [x] 6.5 Backend: auth required, payload secret-free
- [x] 6.6 Where the checks run — **decided: option (b)**, a Node script in `npm run lint`.
      Node 22 strips TypeScript natively, so the content is imported rather than parsed.
      No new dependency
- [x] 6.7 **Test the tests.** Every check was verified against a deliberately broken input:
      unknown placeholder, missing file, over-budget title/what/bullets, dangling edge,
      orphan panel. The checker also refuses to run if it parses **zero** fields from the
      schema, so it can never pass vacuously
- [x] 6.8 ⚠ **There was no frontend CI job at all.** `npm run lint` and `npm run build`
      had never run outside a laptop — which means this whole guarantee would have been
      decorative. Added a `frontend` job. Deliberately **not** a dependency of `deploy`:
      the two deploy separately, so a stale sentence must not block an API fix
- [x] 6.9 ⚠ **Found by the endpoint on its first run: the live app was recalling 12 facts,
      not 16.** `.env.example` still pinned `MEMORY_RECALL_K=12` from before the default
      moved, and every `.env` copied from it inherited that silently. The template now
      leaves it commented out, and `test_env_example_does_not_pin_a_stale_default` fails
      the build if any numeric pin drifts from its code default again.
      **Narendra's own `.env` still overrides it** — that file is his, and changing it is
      his call

## 7. Documentation

- [x] 7.1 `ARCHITECTURE.md` — new §(g) with its own diagram, plus `api/learn.py` in the
      directory guide
- [x] 7.2 `AGENTS.md` — `api/learn.py` (with the allow-list warning) and `lib/learn/`
- [x] 7.3 `ROADMAP.md` — moved to Done, including what it does **not** do: it does not
      generate itself, and the tests catch broken references rather than missing ones
- [x] 7.4 `README.md` — Learn added to the "I want to…" table
- [x] 7.5 How to add a concept or a node — in `ARCHITECTURE.md` §(g), next to the diagram
      it describes, plus editing rules at the top of `content.ts` where they are seen

## 8. Verification

- [x] 8.1 `uv run ruff format .` / `ruff check .` clean
- [x] 8.2 `uv run pytest` — **368 passed** (was 333 before this change, 262 two changes ago)
- [x] 8.3 Frontend `npm run build` clean, and `npm run lint` runs the content checker
- [ ] 8.4 **Live:** every node in both diagrams opens a panel, and every panel's links work
- [x] 8.5 **Live:** confirm the page shows the running value without a content edit
      → demonstrated by accident, which is stronger than a contrived test. The code default
      is 16 and the live endpoint returned **12**, because `.env` overrides it. The page
      shows what the system uses, not what the source says
- [ ] 8.6 **Live at 375 px:** both diagrams legible, every node selectable, no sideways scroll
- [ ] 8.7 Keyboard-only pass
- [ ] 8.8 Dark mode pass
- [x] 8.9 **Confirm `.env` is NOT staged** before any commit

## 9. Review feedback — first look at the live page

Narendra reviewed it running and raised three things. All addressed.

- [x] 9.1 ⚠ **Bug: two panels opened at once on a wide screen.** The inline panel was
      `hidden lg:block` and the Sheet's wrapper `lg:hidden`, which looks correct and is
      not: a Radix Sheet renders through a **portal into `document.body`**, so it is no
      longer a descendant of that wrapper and the class never reaches it. Both drew.
      Fixed with `useMediaQuery` — anything portalled has escaped its CSS ancestors, so
      the decision to render it has to be made in JavaScript
- [x] 9.2 **The diagram was too plain.** Every node now carries an **icon** (read before
      the label is), main-path nodes carry a **step number**, and the four `kind`s have
      genuinely different treatments — solid card for work, tinted for storage, dashed for
      external, ghosted for planned. Edges got heavier strokes, visible arrowheads, and
      **labels on a pill** so the line no longer runs through the text
- [x] 9.2a The dashed side-connections were unlabelled, so a reader could see *that* a step
      touches a store but not what it does there. Now `reads` / `writes` / `via` / `detail`
      — the difference between reading memory and writing to it is the interesting part
- [x] 9.2b Icon names live in their own module (`icon-names.ts`) apart from the components
      (`icons.ts`). The checker runs in bare Node and must not load a React icon library to
      validate a string; `Record<IconName, ...>` still makes a missing mapping a **compile
      error** rather than a blank square
- [x] 9.2c Checker additions: an icon name must exist, and **step numbers must be a real
      order** — 1..N, nothing skipped, nothing repeated. A misnumbered sequence teaches the
      wrong order, which is worse than no numbers
- [x] 9.3 **No way to navigate.** Added a sticky contents bar that highlights the section
      you are actually in, via `IntersectionObserver` picking the **most visible** section
      rather than the first intersecting one — the latter flickers whenever a boundary
      crosses the viewport
- [x] 9.4 `icons.tsx` → `icons.ts`: no JSX in it, and a "component file" exporting only a
      lookup table trips the fast-refresh lint rule for nothing
