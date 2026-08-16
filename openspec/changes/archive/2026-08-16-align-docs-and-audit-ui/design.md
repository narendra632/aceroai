## Context

Six markdown files in `docs/`, plus `AGENTS.md` and two `README.md`s, describe a system
that has changed under them seven times. The drift is not random — it has a shape, and
the fix has to address the shape, not just today's inaccuracies.

## Decision 1 — Mermaid, not draw.io

Narendra proposed the **draw.io VS Code extension**. It is a good tool and it is the
wrong one for this requirement, for one reason that dominates all others.

The requirement is *"diagrams that stay updated as we progress"* — meaning **an agent
edits them repeatedly, and a human reviews the edit**. Draw.io stores diagrams as
mxGraph XML in which **every node carries absolute x/y pixel geometry**. That has three
consequences:

1. **Editing is coordinate arithmetic.** Inserting a node means recomputing the position
   of everything around it. An agent can do this, but slowly and with poor results — the
   layout degrades a little on each pass.
2. **Diffs are unreviewable.** A one-node change produces a diff of shifted coordinates
   across the file. Narendra cannot review a diagram change the way he reviews code.
3. **Its strength is a mouse.** Draw.io is excellent when a *human* is drawing. That is
   the opposite of the workflow here.

Mermaid inverts all three: it is **declarative text with no coordinates**. `A --> B`
states a relationship; the renderer computes layout. Adding a provider is one line.
Diffs read as English.

**Correction (2026-08-16): the viewing story is not as clean as first stated here.** The
original claim was that Mermaid "renders natively on GitHub *and* in VS Code's built-in
markdown preview — no plugin". Only the first half is true:

| Surface | Renders ```mermaid? |
|---|---|
| **GitHub** (web, PRs, blame) | ✅ natively, since 2022 |
| **VS Code built-in preview** | ❌ **no** — needs `bierner.markdown-mermaid` |
| VS Code editor pane | ❌ raw source, as expected |

The extension is free, first-party-adjacent (by a VS Code maintainer), and one click —
so this does not change the decision. But it *is* a real cost that draw.io's extension
would equally have had, and the comparison below should be read with that corrected.
It is now in `.vscode/extensions.json` so the editor prompts for it automatically.

Alternatives considered and rejected:

| Option | Why not |
|---|---|
| **D2** | Better layout engine than Mermaid, genuinely. Needs a binary installed and a build step, and does not render on GitHub. Not worth the tooling for a repo this size. |
| **PlantUML** | Most powerful, best sequence diagrams. Requires Java or a render server. Disproportionate. |
| **Structurizr / C4** | The correct answer for a large system — one model, many generated views. Overkill for 36 modules; revisit if this ever becomes multi-service. |
| **Excalidraw** | Great for *Narendra* sketching ideas. JSON with geometry, so same agent-editing problem as draw.io. |
| **draw.io** | Above. Keep it available for one-off hand-drawn things; not the source of truth. |

**Mermaid's real limitation, stated honestly:** layout control is limited, and large
diagrams get visually messy. The mitigation is scope discipline — **six focused diagrams
rather than one giant one**. A diagram that needs pixel control is a diagram trying to
say too much.

## Decision 2 — diagrams embedded in the markdown, not in `docs/diagrams/*.mmd`

A separate `docs/diagrams/` folder was the initial suggestion. Rejecting it:

- GitHub and VS Code render ```mermaid **fences inside markdown**. They do **not** render
  a standalone `.mmd` file linked from a document. Separate files would therefore have to
  be *embedded or exported to be seen* — reintroducing a build step and a second copy.
- A diagram belongs **next to the prose that explains it**. Splitting them means they can
  drift from each other — a smaller version of the exact problem being fixed.

So: fences live inline in `ARCHITECTURE.md` and, where relevant, `DEPLOY.md` and
`REQUEST-ANATOMY.md`. One file, one truth, renders everywhere, no tooling.

## Decision 3 — rewrite `ARCHITECTURE.md`, do not append to it

The document is not uniformly stale. §8 (Status) is current; §1–§6 are badly out of date.
That asymmetry **is the diagnosis**: seven changes each appended a status paragraph, and
none went back to fix the body. Appending an eighth would deepen the problem while
appearing to solve it.

So §1–§6 are rewritten against the code, and the structure changes to remove the
incentive: **the giant prose "Status" section is deleted entirely.** Status lives in
`ROADMAP.md`, which already tracks it. `ARCHITECTURE.md` answers *"how does this work?"*
and nothing else. A document with one job is far harder to drift.

Two further rules adopted:

- **No `(planned — Feature N)` annotations.** They were the single largest source of
  falsehood — every one of them became a lie the moment the feature shipped, and nothing
  forced a revisit. `ARCHITECTURE.md` describes only what exists; what is planned lives
  in `ROADMAP.md`, one place.
- **The dated "written at the close of Phase 0" framing is replaced** with a
  *last-verified* date, which states what it actually means.

## Decision 4 — audit before implementing, and no mockups

Narendra's constraint: he does not want a loop where a mockup is produced, transferred,
opened on a phone, and commented on. That loop has a transfer step, and transfer steps
cost more than the review is worth.

He is right, and the reason is specific to this project: **Radix is already installed**
(`radix-ui@1.6.7`), so replacing a native `<select>` with a properly themed custom
control is roughly *thirty lines*. Mocking that costs about as much as building it. A
mockup earns its keep when implementation is expensive; here it is not.

The loop with no transfer step is the dev server itself: `npm run dev` is already
running, Vite hot-reloads in ~200 ms, in Narendra's own browser at his own window size,
with devtools device-emulation (`Ctrl+Shift+M`) covering mobile. Nothing to send.

**But that loop has no plan gate** — it discovers requirements by reacting, which is how
the interface reached its current state. So the gate moves earlier and becomes text:
`docs/UI-AUDIT.md`, reviewed and edited *before* code moves. Cheap to read, cheap to
argue with, and it makes the standard explicit rather than implicit.

**Constraint that shapes this:** there is no browser-driving or screenshot tool available
in this environment. The audit is therefore built by **reading all 14 components** plus
Narendra's screenshots. Static reading reliably catches structure, state handling,
accessibility, and control choice; it **cannot** catch visual spacing, contrast, or
animation feel. The audit will mark which findings are code-derived and which need
his eyes, rather than pretending to a completeness it does not have.

## The six diagrams

Chosen to answer the six questions actually asked when working on this system:

| Diagram | Answers | Type |
|---|---|---|
| System context | What talks to what? | `flowchart` |
| Request lifecycle | What happens on one message, and where does the time go? | `sequenceDiagram` |
| Tool-use loop | How does the assistant act, and what bounds it? | `flowchart` |
| Memory lifecycle | How does a fact get learned and recalled? | `flowchart` |
| Data model | What are the tables and how do they relate? | `erDiagram` |
| Deploy pipeline | What happens when I push to main? | `flowchart` |

The request-lifecycle diagram carries the **measured** stage timings from
`REQUEST-ANATOMY.md` rather than invented ones, so the picture and the measurements
cannot disagree.

## Risks

- **A rewrite can introduce new inaccuracies.** Mitigated by verifying every path,
  command, and env var against the repo as an explicit task — not from memory.
- **The standing checklist item can become ritual** — ticked without thought. No process
  prevents that; it is worth knowing rather than pretending otherwise.
- **The audit will be long.** Fourteen components with no prior standard will produce a
  lot of findings. It is grouped by severity so it can be triaged rather than read
  end-to-end, and Narendra sets the cut line.
