# A Learnings section: the app explaining itself, in the app

## Why

Narendra is building this to **learn how software gets built**. Everything learned so far
lives in `docs/` — eight markdown files, eleven Mermaid diagrams, written for whoever
maintains the code. None of it is reachable from the product, and none of it teaches: it
records.

The gap is not documentation. It is that the most interesting thing about this project —
*why* a decision was made, what was measured, what was rejected — is invisible to the
person it was built for unless he opens a text editor.

This adds a **Learn** section to the app: two or three diagrams you can click into, a set
of concept explanations, and a standing record of what is planned next. Built to stay
accurate as the project grows, not accurate once.

## What changes

### A. The docs' diagrams are audited and repaired first

The Learnings diagrams are derived from the ones in `docs/`, so those have to be right.
An audit of all eleven found four real defects — three introduced by the change archived
two days ago:

| file | defect | severity |
|---|---|---|
| `ARCHITECTURE.md` | sections run **(a) (b) (c) (e) (d) (e)** — two `(e)`s, out of order | broken navigation |
| `ARCHITECTURE.md` §2 | the `api/` node omits the **memory** and **insights** routers; `core/` omits `recall` | incomplete |
| `ARCHITECTURE.md` §4a | the sequence diagram shows neither the **budget check** (which runs *first*, before anything is persisted) nor the **`recall` SSE event** | wrong order, missing step |
| `REQUEST-ANATOMY.md` | node id **`U2` is declared twice** with different labels — Mermaid silently keeps one, so "reply complete" and "UI can show which facts were used" collide | renders wrong |

The deployment diagrams and the ER diagram check out: four containers matches
`docker-compose.prod.yml`, the CI→GHCR→SSH→migrate→api chain matches `ci.yml`, and the ten
tables match `db/models.py`.

### B. A Learn view, built around clicking rather than reading

Three sections, each answering one question:

1. **How it works** — one flow diagram covering a message end to end: chat → recall →
   context → model → tools (tasks, journal, memory) → reply → learn. **Click any node** and
   a panel explains that step: what it is, how it works, what was measured, and which file
   to open.
2. **What it costs, and how we know** — the same treatment for the money: tokens, the
   price list frozen at write time, traces, the rollup, the spend ceiling.
3. **Concepts** — the fundamentals underneath, each its own card: embeddings, cosine
   distance, HNSW, full-text search, Reciprocal Rank Fusion, SSE streaming, the one-brain
   pattern, soft delete, migrations. Deep, but one idea at a time.

Plus a short **What's next** strip, so planned work is visibly *planned* and never reads as
built.

### C. Two mechanisms so it cannot quietly go stale

This is the part that makes it worth building rather than writing once and abandoning.

- **Every number is fetched live.** A read-only `GET /api/learn/constants` serves the
  values the page quotes — recall limit, tool-loop cap, graph ceiling, retention windows,
  fusion constant. The content never hardcodes a number. This is not hypothetical: the
  change archived on 2026-08-23 moved `MEMORY_RECALL_K` from 12 to 16, and a page written
  three days earlier would already be lying.
- **Content is checked against the repo.** Tests assert that every file path a panel points
  at exists, every constant placeholder is actually served, and every concept a diagram
  node references is defined. A rename that breaks a reference fails CI instead of rotting.

### D. A stated text budget

"Not too much text" is the brief, so it becomes a rule rather than an intention: one
summary line, at most five bullets, at most one measured figure per panel — enforced by a
test. Anything longer belongs in `docs/`, and the panel links to it.

## Impact

- **New capability:** `learnings`
- **Backend:** one read-only router (`api/learn.py`), no new table, no migration
- **Frontend:** a `LearnView`, a reusable click-through diagram primitive, and the content
  as typed data
- **Docs:** four diagram repairs; `ARCHITECTURE.md` gains the section this describes
- **No new dependency.** The diagram is hand-built rather than Mermaid — see design
  Decision 3, which is the one call worth reviewing before work starts
