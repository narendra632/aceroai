# Design

The brief was "explained beautifully, not too much text, accurate to this stage, and kept
updated as we build". Three of those four are content decisions. The fourth — *accurate*,
and staying accurate — is an engineering decision, and it is what most of this document is
about.

---

## Decision 1 — The content is typed data in the frontend, not rows in a database

Three places it could live:

| | reviewable in a diff | versioned with the code it describes | needs a migration to fix a typo |
|---|---|---|---|
| Postgres rows | no | no | **yes** |
| markdown files served by the API | yes | yes | no |
| **typed TS modules** | yes | yes | no |

The database is wrong on its face: this is not user data. It is a *description of the
code*, and it must move when the code moves — which means it belongs in the same commit as
the code, reviewed in the same diff. A fact about the user survives a deploy; a sentence
explaining how recall works must not.

Markdown-in-a-file is closer but loses structure. A node panel is not prose — it is
`{ title, what, how[], measured?, code[], reads[] }`, and only a typed shape lets a test
assert that `code` points at a file that exists.

**Rejected — a `learnings` table with an admin UI.** Editing content through a form means
the content is no longer reviewed, no longer diffed, and no longer tied to the commit that
made it true.

---

## Decision 2 — Every number is fetched, never typed

This is the mechanism the whole feature rests on.

The page will want to say things like *"recall sends at most 16 facts"* and *"the tool loop
is capped at 5 rounds"*. Written as literals, they are correct on the day and wrong later.
That is not a risk, it is a certainty, and it has already happened once: the change
archived on 2026-08-23 moved `MEMORY_RECALL_K` **12 → 16**. A Learnings page written on the
20th would already be teaching a wrong number.

So the content writes a **placeholder**, and a read-only endpoint serves the live value:

```
"Recall sends at most {recall_k} facts, chosen from {recall_pool} candidates per ranker."
```

```
GET /api/learn/constants  ->  { "recall_k": 16, "recall_pool": 20, "rrf_k": 60, ... }
```

The endpoint reads `settings` directly, so there is exactly one source. Change the setting,
the lesson changes.

Two properties worth stating:

- **It is read-only and derived.** No new table, no migration, nothing to keep in sync.
- **It exposes only tuning constants** — limits, thresholds, window lengths. Never a model
  name tied to a key, never a URL, never anything from `.env`. The allow-list is explicit
  in code rather than "serialise `settings`", so a secret cannot be added to the page by
  accident later.

**Rejected — generating the content at build time from the backend.** Couples the frontend
build to a running backend, and a stale build would still lie. Fetching at view time cannot.

**Rejected — hardcoding and adding a test that greps the numbers.** The test would have to
know which literal in which sentence maps to which setting. The placeholder *is* that
mapping, expressed once.

---

## Decision 3 — The diagram is hand-built, not Mermaid

**This is the decision worth reviewing before work starts**, because it drives most of the
effort.

The requirement is not "render a diagram". It is: click a node, get a panel; reachable by
keyboard; correct in dark mode; usable at 375 px; themed to the app's warm palette.

| | Mermaid | hand-built SVG + CSS grid |
|---|---|---|
| new dependency | **~500 KB**, needs approval | none |
| node click → panel | `click` directives, awkward with React state | a `<button>` |
| keyboard reachable | not by default | free — they are buttons |
| dark mode | needs a theme override and a re-render on toggle | uses the existing tokens |
| 375 px | fixed SVG, scales down until unreadable | grid collapses to one column |
| matches the codebase | no | yes — `force-graph` and `waterfall` are both hand-built |

Mermaid is the right tool for a diagram in a *document*, which is exactly why `docs/` uses
it. It is the wrong tool for an interactive component, and the work saved on layout is
spent again on fighting its output.

**Shape.** Nodes are declared with a grid position and rendered as buttons on a CSS grid.
Edges are drawn in an absolutely-positioned SVG overlay, with paths computed from the
nodes' measured rectangles and recomputed by a `ResizeObserver`. That single code path
handles the narrow screen for free: the grid collapses to one column and the edges become
short vertical connectors.

**Rejected — reusing `force-graph.tsx`.** It is a physics simulation for a graph with no
inherent layout. A pipeline has a *deliberate* order, and letting a force simulation
scramble it every render would destroy the only thing the diagram is trying to say.

**Rejected — a static image.** Cannot be clicked, cannot be themed, goes stale silently,
and is invisible to a screen reader.

---

## Decision 4 — Three sections, because there are three different questions

The brief listed several things at once. They are not one page:

| section | the question it answers | form |
|---|---|---|
| **How it works** | "what happens when I send a message?" | one flow diagram, click-through |
| **What it costs** | "how do you know what this costs, and how do you stop it?" | one flow diagram, click-through |
| **Concepts** | "what *is* an embedding / RRF / HNSW?" | card grid → the same panel |
| **What's next** | "what is planned but not built?" | a short strip, visually distinct |

The first two are *this system*. The third is *the ideas underneath*, which outlive this
system and are the part actually worth learning. Keeping them apart matters: a concept card
for "cosine distance" should make sense to someone who has never seen this codebase.

**"What's next" is styled differently on purpose** — muted, marked, never mixed into the
built sections. A learning tool that blurs "we did this" and "we might do this" teaches the
wrong thing, and this project already keeps that line clean in `ROADMAP.md`.

---

## Decision 5 — The text budget is a test, not an intention

"Not too much text" was explicit, and it is the requirement most likely to erode — every
future edit adds a sentence and none removes one.

So it is enforced:

```
title      <= 60 chars
what        1 sentence, <= 140 chars
how         <= 5 bullets, <= 120 chars each
measured    at most ONE figure
```

A panel that wants more is a signal that the idea belongs in `docs/`, and the panel links
there instead. The `reads` field exists for exactly that hand-off.

This is the same argument as the graph's 800-node ceiling: a limit that announces itself
beats a limit discovered later as sprawl.

---

## Decision 6 — Accuracy is checked mechanically, not promised

Four tests, each closing a specific way this rots:

| rots by | test |
|---|---|
| a file gets renamed | every `code` path in the content exists on disk |
| a setting is removed | every `{placeholder}` used is served by the endpoint |
| a node points at a deleted concept | every concept id referenced is defined |
| someone writes an essay | the budget in Decision 5 holds |

None of these check that the *prose* is true — nothing can. They check that every
mechanical claim resolves, which is where staleness actually enters. The prose is kept
honest the same way `docs/` is: it gets updated in the commit that makes it wrong.

---

## Decision 7 — `docs/` stays the reference; Learn is the teaching

They will overlap in substance. That is fine and not duplication to be eliminated, because
they have different jobs:

- **`docs/ARCHITECTURE.md`** — complete, ordered, for whoever has to change the code.
- **Learn** — one idea at a time, clicked into, for whoever wants to understand it.

The relationship is one-way: Learn links out to `docs/`, and `docs/` never links into the
UI. Numbers flow from `settings` to both. Where they disagree, the endpoint wins, because
it is the only one reading the live value.

---

## Decision 8 — Behind auth, like everything else

The page holds no user data — it describes the system, not Narendra. So it *could* be
public, and the roadmap does mention a possible public version later.

It ships behind the existing auth anyway, because that is the default every other route
follows and a public route is a decision to make deliberately, not by omission. Nothing in
the design prevents it later: the content is static, the endpoint is derived, and neither
touches a user id.

---

## Decision 9 — The docs' diagrams are repaired first, in the same change

Four defects found by audit (listed in the proposal), three of them introduced by the
change archived two days ago. They are repaired here rather than in a separate pass because
the Learn diagrams are built *from* them — drawing a new diagram from a source known to be
wrong is how the error gets copied rather than caught.

The audit also confirmed what is **right**, which is worth recording so it is not re-checked
later: the deployment topology (four containers), the CI→deploy chain, the tool-use loop,
the memory write flow, the knowledge-graph flow, and all ten tables in the ER diagram.
