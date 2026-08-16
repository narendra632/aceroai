## Why

**The documentation has quietly stopped being true**, and it failed in a specific,
diagnosable pattern worth naming: every change **appended a status paragraph** and
**never fixed the body**. `ARCHITECTURE.md` §8 is accurate as of today. §1 through §6 —
the parts a reader actually uses to understand the system — describe a codebase that
stopped existing weeks ago:

| Where | What it says | What is true |
|---|---|---|
| §1 Overview | "an LLM reached through the **openai SDK pointed at any OpenAI-compatible endpoint**" | This is the architecture we **explicitly rejected** — it cannot round-trip `thought_signature`. We run native SDKs behind `core/providers/`. |
| §2 Diagram | `tasks, journal (planned)` · `core/llm — thin AsyncOpenAI wrapper` | Both shipped. `llm.py` is a provider facade. The diagram has no memory, tools, services, providers, or telemetry. |
| §3 Directory | `src/App.tsx` — "Health-check page" · `src/index.css` — "Single line: `@import tailwindcss`" | 14 components; 154 lines of theme tokens. Lists migration `001` only; `002` and `003` are applied. |
| §4 Lifecycle | "describe what **will** happen" · JWT **httpOnly cookie** | Built. Auth is a **Bearer token** — the cookie was blocked cross-site. No mention of the tool loop, recall, or telemetry. |
| §5 Data model | "The vector column **waits for Phase 2**" | Shipped in migration `002` (pgvector + HNSW). |
| §6 Config | "Provider swap recipe: set `LLM_BASE_URL`, `LLM_API_KEY`" | Both obsolete. |

`AGENTS.md` — the file `CLAUDE.md` calls "the source of truth for stack and conventions"
— still lists the stack as "**openai SDK with base_url swap**", and its `Layout` section
omits `services/`, `providers/`, `memory.py`, `tools.py`, and `telemetry.py` entirely.

This is not cosmetic. These files are read **first, by every agent and every future
reader**, to decide how to build the next thing. A source of truth that lies is worse
than no source of truth, because it is trusted.

**Second problem: there is no picture of the system anywhere.** The only diagram is an
ASCII block in `ARCHITECTURE.md` §2 that is itself wrong. Understanding aceroai today
requires reading 36 Python modules or 6 markdown files, and holding it in your head.

**Third problem: the UI is at "functional", not "product".** The interface uses raw
native `<select>` elements and a native `datetime-local` input — which renders an
OS-styled **white** popup inside a dark UI with a **black, invisible** calendar icon.
Chat sessions cannot be renamed. Every mutation triggers a **full refetch**, so a
checkbox waits on a network round-trip before it visibly moves. These are not
one-off bugs; they are the accumulated cost of choosing the fastest control that worked,
repeatedly. The stated bar for this project is ChatGPT/Claude, and the gap is now wide
enough that it needs a written inventory before it can be closed.

## What Changes

**1. Every document is made true.** `ARCHITECTURE.md` is rewritten section by section
against the actual code — not appended to. `AGENTS.md` stack, layout, and status are
corrected and compressed. Every file path, env var, and command referenced anywhere in
`docs/` is **verified to exist** before the change is done. The dated
"Written at the close of Phase 0" framing is dropped: the document describes the system
as it is, and says when it was last verified.

**2. Mermaid becomes the diagram format**, embedded as ```mermaid fences **directly in
the markdown** (not as separate files — see `design.md` for why). Six diagrams cover the
system: context, request lifecycle, tool-use loop, memory lifecycle, data model, and the
deploy pipeline. Mermaid is chosen because it is **text with no coordinates**: it diffs
reviewably in git, renders **natively on GitHub**, and can be edited correctly by an
agent — which draw.io's coordinate-bearing XML cannot. *(VS Code needs the free
`bierner.markdown-mermaid` extension to preview them; it has no built-in support. Added
to `.vscode/extensions.json`.)*

**3. Drift is made structurally hard to repeat.** A new `documentation` capability spec
states that docs must describe implemented behavior and that diagrams must match the
code. The OpenSpec `tasks.md` convention gains a standing final item — *"docs and
diagrams reflect what was built"* — so it is checked like tests are, rather than
remembered.

**4. A UI/UX audit is produced as a reviewable deliverable** (`docs/UI-AUDIT.md`): every
one of the 14 frontend components examined, each gap recorded with its location, why it
falls short of product standard, and a proposed fix. **No UI code changes in this
change.** The audit is the artifact Narendra edits — strike items, add items, reorder —
and it becomes the agreed scope of the UI change that follows.

## Capabilities

### New Capabilities

- `documentation`: the repository's documentation describes the system **as built**;
  architecture is expressed in diagrams that live in version control alongside the code
  they describe; and both are updated as part of the change that alters the behavior,
  not afterwards.

### Modified Capabilities

None. **No runtime behavior changes in this change** — no backend logic, no UI code, no
migrations, no dependencies. Every existing capability spec stays exactly as it is.

<!-- The UI standard implied by docs/UI-AUDIT.md deliberately does NOT become a spec
     here. It graduates into a `ui-standards` capability in the *next* change, once
     Narendra has reviewed and edited the audit — specifying a standard he has not
     agreed to yet would be putting the conclusion before the review. -->

## Impact

- **Docs:** `ARCHITECTURE.md` rewritten (§1–§6 truthed, diagrams embedded);
  `AGENTS.md` stack/layout/status corrected; `DEPLOY.md`, `DEPLOYMENT-EXPLAINED.md`,
  `REQUEST-ANATOMY.md`, `SOUL.md`, and both `README.md`s verified and corrected;
  `ROADMAP.md` already updated (DB-backup standing risk + the agreed order).
- **New:** `docs/UI-AUDIT.md` — the reviewable inventory.
- **Code:** none. **Dependencies:** none. **Migrations:** none.
- **Process:** the OpenSpec `tasks.md` template gains the standing docs/diagrams item.
- **Testing:** there is no test suite for prose, so verification is explicit and manual —
  every path, command, and env var named in the docs is checked to exist, and every
  Mermaid block is confirmed to render. `uv run pytest` must still pass untouched,
  proving the change is genuinely docs-only.

## Non-goals (this change)

- **Any UI code.** The audit only describes; it does not fix. That is the next change.
- **The architecture atlas artifact** — considered and declined: Mermaid already renders
  on GitHub and in VS Code, so a hosted page would be a *second* surface to keep in sync,
  which is the exact failure this change exists to correct.
- **Backfilling historical accuracy.** Docs describe the system as it is now; archived
  OpenSpec changes remain the historical record and are not edited.
- **The DB backup, scheduled jobs, and PWA** — now on `ROADMAP.md`, each its own change.
