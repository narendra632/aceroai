## 0. Establish ground truth (no writing yet — verify first)

- [x] 0.1 Inventory every `.md` in the repo (root, `docs/`, `backend/`, `frontend/`, `.github/`) — the drift surface is bigger than `docs/`
- [x] 0.2 Extract every **file path** referenced in those docs; confirm each exists. Verified already: `PLAN.md` (`ARCHITECTURE.md` §3) is **gone**; `.github/skills/` and `.github/prompts/` are **present** — check each path, do not assume from a name
- [x] 0.3 Extract every **env var** named in docs; reconcile against `config.py` and `.env.example` — flag obsolete ones (`LLM_BASE_URL`, `LLM_API_KEY`) and any real setting the docs never mention (`EMBED_LOCATION`, `MEMORY_RECALL_TIMEOUT_S`, `CONTEXT_TASKS_LIMIT`, `TOOLS_MAX_ITERS`)
- [x] 0.4 Extract every **command** in docs; confirm each still runs as written
- [x] 0.5 List the applied migrations (`001`, `002`, `003`) and the actual table set; the docs claim only `001`
- [x] 0.6 Record findings as the worklist for §1–§2 *(do not fix while surveying — separate reading from writing)*

## 1. ARCHITECTURE.md — rewrite §1–§6 against the code

- [x] 1.1 Replace the "written at the close of Phase 0" header with a **last-verified** date and a one-line statement of the file's single job (*how it works* — not status, not plans)
- [x] 1.2 **§1 Overview** — remove "openai SDK pointed at an OpenAI-compatible endpoint"; describe the native-SDK provider layer and *why* it is native (`thought_signature`)
- [x] 1.3 **§2** — replace the ASCII diagram with the **system-context Mermaid** diagram (§4.1); it must include `providers/`, `services/`, `memory`, `tools`, `telemetry`
- [x] 1.4 **§3 Directory guide** — regenerate from the real tree: all 36 backend modules, all 14 frontend components, migrations `001`–`003`. Delete the false rows (`App.tsx` "health-check page", `index.css` "single line")
- [x] 1.5 **§4 Lifecycle** — rewrite as *current behavior*, not a contract: Bearer token (not cookie), memory recall, task-aware context, the tool loop, telemetry. Embed the **request-lifecycle** and **tool-loop** diagrams
- [x] 1.6 **§5 Data model** — remove "the vector column waits for Phase 2" (shipped in `002`); embed the **ER diagram**; keep the rationale prose, which is still sound
- [x] 1.7 **§6 Config** — delete the obsolete provider-swap recipe; document the settings that actually exist, including the **pinned embedding** and per-environment `EMBED_LOCATION`
- [x] 1.8 **Delete §8 (Status)** entirely — status belongs to `ROADMAP.md`; its presence is what invited seven rounds of append-only drift
- [x] 1.9 Remove every `(planned — Feature N)` annotation repo-wide *(each one became false on ship and nothing forced a revisit)*

## 2. Remaining documents

- [x] 2.1 **AGENTS.md** — fix the stack line ("openai SDK with base_url swap" is false); add `services/`, `core/providers/`, `memory.py`, `tools.py`, `telemetry.py` to `Layout`; compress the five-paragraph `Current status` to a short pointer at `ROADMAP.md`
- [x] 2.2 **DEPLOY.md** — verify every command against the live setup; confirm the VM **access-scopes** step is present and correctly ordered (it was the cause of a production 403)
- [x] 2.3 **DEPLOYMENT-EXPLAINED.md** — reconcile with `DEPLOY.md`; embed the **deploy-pipeline** diagram; ensure the two do not contradict each other
- [x] 2.4 **REQUEST-ANATOMY.md** — already current (written 2026-08-16); embed the request-lifecycle diagram and confirm the measurements still match the code paths
- [x] 2.5 **SOUL.md** — confirm it matches the assistant's actual instructions and tool set
- [x] 2.6 **backend/README.md** and **frontend/README.md** — ⚠ *this task was itself wrong: it repeated `ARCHITECTURE.md` §3's claim that these are an "empty uv-init placeholder" and "the Vite template". Both are real, substantial docs (14 KB / 5 KB). Verified, then corrected in place.* `backend/README.md` contradicted **itself** — its header described the OpenAI-compat shim its own "Model providers" section explains we rejected — and its auth section still claimed "httpOnly so browser JavaScript can never read the token", the opposite of what ships
- [x] 2.7 **README.md** (root) — rewritten; it linked to `docs/PHASE0_SETUP.md`, **which does not exist**, and called the project by its old name. **CLAUDE.md** — verified accurate, no change needed

## 3. Mermaid adoption

- [x] 3.1 Author the six diagrams as ```mermaid fences **inline in the relevant `.md`** (not `docs/diagrams/*.mmd` — see `design.md` Decision 2)
- [x] 3.2 **system-context** — channels → API → one brain → providers / services / DB
- [x] 3.3 **request-lifecycle** (`sequenceDiagram`) — carrying the **measured** stage timings from `REQUEST-ANATOMY.md`, never invented ones
- [x] 3.4 **tool-use loop** — bounded by `TOOLS_MAX_ITERS`, showing the fault-tolerant path and where `thought_signature` round-trips
- [x] 3.5 **memory lifecycle** — extract → embed → store → recall, with the `MEMORY_RECALL_TIMEOUT_S` bound and the pinned-embedding warning
- [x] 3.6 **data model** (`erDiagram`) — the 8 tables incl. `profile_facts.embedding` and the supersession relationship
- [x] 3.7 **deploy pipeline** — push → CI → GHCR → SSH → compose, incl. the `migrate` service
- [x] 3.8 Confirm every block renders in **VS Code preview** *and* on **GitHub** — ⚠ *root cause found in review: **VS Code has no built-in Mermaid support at all**, so the preview showed raw code. `design.md` originally claimed it rendered "natively in VS Code preview with no plugin" — that was wrong and is now corrected there and in `proposal.md`. Fix: `bierner.markdown-mermaid` added to `.vscode/extensions.json` so the editor prompts for it. GitHub renders natively with no setup. **Confirmed rendering by Narendra, 2026-08-16.***
- [x] 3.9 Keep each diagram small enough to stay legible; split rather than cram *(6 focused diagrams, none exceeding ~12 nodes)*

## 4. Make drift structurally harder

- [x] 4.1 Add the standing final item to the OpenSpec `tasks.md` convention: **"docs and diagrams reflect what was built"**, checked like tests
- [x] 4.2 Record the rule in `AGENTS.md` golden rules so it is read before work starts, not after
- [x] 4.3 State in `ARCHITECTURE.md` that it describes *current* behavior only, so future contributors append status nowhere

## 5. UI/UX audit — `docs/UI-AUDIT.md` (describe only; change no code)

- [x] 5.1 Read all 14 components: `AppShell`, `Sidebar`, `MessageList`, `MessageBubble`, `Composer`, `Markdown`, `ThinkingDots`, `TasksView`, `JournalView`, `SettingsView`, `LoginScreen`, `ui/{button,dropdown-menu,tooltip}`
- [x] 5.2 Record every gap with **file:line**, why it falls short of product standard, and a proposed fix — grouped by severity so it can be triaged, not read end-to-end
- [x] 5.3 Mark each finding **code-derived** vs **needs Narendra's eyes** *(no browser/screenshot tool is available here — spacing, contrast, and motion cannot be judged from source; do not claim otherwise)*
- [x] 5.4 Cover the known ones explicitly: native `<select>` ×2 ([TasksView.tsx:100](../../../frontend/src/components/TasksView.tsx#L100), [:164](../../../frontend/src/components/TasksView.tsx#L164)); native `datetime-local` with an invisible dark-mode icon ([:93](../../../frontend/src/components/TasksView.tsx#L93)); no session rename ([Sidebar.tsx:120](../../../frontend/src/components/Sidebar.tsx#L120)); **full refetch on every mutation** instead of optimistic update ([TasksView.tsx:50-61](../../../frontend/src/components/TasksView.tsx#L50-L61))
- [x] 5.5 Note cross-component **inconsistencies** — e.g. session delete reveals on hover ([Sidebar.tsx:141](../../../frontend/src/components/Sidebar.tsx#L141)) while task delete is permanently visible ([TasksView.tsx:174](../../../frontend/src/components/TasksView.tsx#L174)); the same action should not behave two ways
- [x] 5.6 Cover what is **missing** as well as what is wrong: destructive actions with no confirm/undo, no success or error feedback anywhere, no loading skeletons, no task editing after creation, no keyboard affordances
- [x] 5.7 Audit **accessibility** (focus-visible states, labels, contrast ratios, touch-target sizes) and **mobile** behaviour — a PWA is two changes away
- [x] 5.8 Propose the **shared primitives** the fixes imply (`Select`, `DatePicker`, `ConfirmDialog`, `Toast`, `Skeleton`) so the UI change builds a system rather than patching 14 files independently
- [x] 5.9 End with a **proposed cut line** — must-fix vs nice-to-have — as a recommendation for Narendra to move, not a decision made for him

## 6. Verify and hand over

- [x] 6.1 Re-ran 0.2–0.4 against the **rewritten** docs, scripted rather than by eye: **every relative markdown link resolves** (10 files), and every `UPPERCASE_VAR` was reconciled against `config.py`. That caught one fresh inaccuracy — `HISTORY_LIMIT` was presented as a setting when it is a **code constant** in `composer.py` — plus four real settings missing from `.env.example` (`CONTEXT_TASKS_LIMIT`, `MEMORY_DEDUP_DISTANCE`, `LLM_MAX_RETRIES`, `MAX_INPUT_CHARS`), now added
- [x] 6.2 `uv run ruff format .` → **52 files left unchanged**; `uv run ruff check .` → all checks passed; `uv run pytest` → **108 passed**
- [x] 6.3 `git status` confirms **no** changes under `backend/app/` or `frontend/src/` — scope guard held
- [x] 6.4 `.env` not staged or modified (only `.env.example` touched)
- [x] 6.5 **Narendra reviewed `docs/UI-AUDIT.md`** and set the cut line: **all 38 findings**, **undo-toast** for destructive actions (with the soft-delete question flagged for the next `design.md`), and a **detail sheet** for task editing that finally surfaces `notes`/`snoozed_until`. Recorded in the audit's Decisions section
- [ ] 6.6 `/opsx:archive` — fold the `documentation` capability into `openspec/specs/`
