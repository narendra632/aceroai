## Why

`docs/UI-AUDIT.md` inventoried **38 gaps** across all 14 components. Narendra reviewed it
and set the scope: **all of them**. This change closes that list.

The findings are not 38 unrelated bugs. They trace to **three habits**, and naming them
explains why the fix is a system rather than 38 patches:

1. **The fastest control that worked was chosen.** Four native `<select>` elements and a
   native `datetime-local` — which renders an OS-styled *white* calendar inside a dark app
   with a near-invisible dark icon. `radix-ui` was a dependency the entire time; the
   shortcut was never a constraint.
2. **Every mutation refetches everything.** `await create() → load()`. The UI waits on a
   network round-trip before it reflects your own click.
3. **Nothing confirms, and nothing can be undone.** Three destructive actions with no
   dialog, no toast, no undo. Success and failure look identical: nothing happens.

There is also a fourth problem the audit surfaced that is **not** cosmetic: **the backend
already has capabilities the UI never exposed.** `tasks.notes` and `tasks.snoozed_until`
are in the schema, served by `PATCH /api/tasks/{id}`, and writable by the assistant
through its `update_task` tool — but **have no interface at all**. So Acero can set notes
and snooze a task that Narendra can never see or correct. Data the user cannot see is
worse than a missing feature; it is a trap.

> *Corrected during §0 verification:* an earlier draft of this proposal claimed
> `services/tasks.snooze_task()` "exists with no REST route at all". That was wrong —
> snoozing is fully reachable via `PATCH` with `snoozed_until`; the standalone service
> function is simply an unused wrapper called only by a test. **The gap is UI-only.** No
> new route is needed, and this change adds none for it.

## What Changes

**1. Six shared primitives, built once** — every one on Radix, which is **already
installed**. No new dependencies.

| Primitive | Replaces / enables |
|---|---|
| `Select` | 4 native `<select>` elements |
| `DatePicker` | the native `datetime-local`; adds Today/Tomorrow/Next-week presets |
| `Sheet` | the task detail panel (bottom on mobile, side on desktop) |
| `Toast` | all action feedback — and carries **Undo** |
| `Skeleton` · `EmptyState` · `ErrorState` | the three states every list currently lacks |
| `useOptimisticList` | instant UI + rollback on failure, replacing refetch-everything |

**2. Delete becomes reversible.** Deleting a task, journal entry, or chat session takes
effect immediately and raises a toast offering **Undo**. This requires the row to survive
the delete, so deletion becomes a **soft delete** (`deleted_at`, migration 004) with the
filter centralised in `services/` — see `design.md` for why that, and not a client-side
timer.

**3. Hidden capabilities get a UI.** A task **detail sheet** (title, notes, due, priority,
status, snooze) surfaces `notes` and `snoozed_until` for the first time — both already
served by the API, neither ever rendered. Journal entries become editable. Chat sessions
become renameable, which needs a `PATCH /api/chat/sessions/{id}` that does not exist today.

**3b. Chat sessions get a service layer.** §0 verification found that `api/chat.py`
queries `ChatSession` and `Message` **directly in its routes** — unlike tasks and journal,
sessions have no `services/` module. That breaks the guarantee this change's soft-delete
design depends on (one place to apply the filter), so `services/sessions.py` is created
and the routes become thin, as golden rule 1 already requires everywhere else.

**4. The remaining audit findings.** Touch targets to 44 px, the copy button made
reachable on touch, hover-reveal made consistent between lists, loading and error states
everywhere, a character counter against the 16,000-char backend cap, journal search and
pagination, message timestamps, session date-grouping, task grouping, keyboard shortcuts,
the two `setTimeout` leaks, `key={i}`, the auto-scroll that fights the user, and the
provider switch that silently discards model choices.

**5. The standard is written down** as a `ui-standards` capability, so "no shortcuts on
UI/UX" becomes something a change can be checked against rather than a good intention.

## Capabilities

### New Capabilities

- `ui-standards`: the interface meets a stated product bar — controls are themed and
  consistent, actions are acknowledged and reversible, every asynchronous surface has
  loading/empty/error states, and anything the data model stores is visible and editable
  by the person it belongs to.

### Modified Capabilities

- `tasks`: tasks are **editable after creation** (title, notes, due, priority, status,
  snooze) — every stored field becomes visible and correctable; deletion is **reversible**.
- `journal`: entries are **editable**; deletion is **reversible**; the list is
  **searchable and paginated** rather than loading every entry forever.
- `web-chat`: sessions can be **renamed**; deletion is **reversible**.
- `assistant-tools`: the assistant **never sees soft-deleted records** — the filter lives
  in `services/`, which the tools already share with the API, so this holds by
  construction rather than by remembering.

## Impact

- **Backend:** migration **004** adds `deleted_at` to `tasks`, `journal_entries`,
  `chat_sessions`; **new `services/sessions.py`** (sessions had no service layer); the
  exclusion filter plus restore functions in `services/`; new routes for restore (×3),
  session rename, and regenerate; journal list gains `q`, `limit`, `offset`.
- **Frontend:** six new primitives under `components/ui/`; all five screens reworked;
  `lib/api.ts` gains restore/rename/search methods.
- **⚠ The soft-delete filter is the risk in this change.** A query that forgets
  `deleted_at IS NULL` shows deleted data. Mitigated structurally: reads go through
  `services/`, which is already the single source of truth for both the REST API and the
  assistant's tools, so there is one place to get it right — plus explicit tests that a
  soft-deleted record is invisible to the API, to `list_tasks`, to the composer's
  task block, and to the assistant.
- **Dependencies:** **none.** Every primitive is built on `radix-ui@1.6.7`, already
  present.
- **Testing:** service-level tests for soft delete/restore and scoping; API tests for the
  new routes; a test that the composer's injected task list excludes deleted tasks (the
  path that would otherwise feed deleted data straight to the model).
- **Docs:** `UI-AUDIT.md` findings marked resolved; `ARCHITECTURE.md` data-model diagram
  updated for `deleted_at`; `frontend/README.md` gains the primitives; per golden rule 11,
  in this change — not after it.

## Non-goals (this change)

- **PWA packaging and push notifications** — the next change; this one makes the UI worth
  installing first.
- **A Trash / recently-deleted view.** Soft delete makes it possible later; only Undo is
  built now.
- **Purging soft-deleted rows.** They accumulate harmlessly at single-user scale; a
  retention job can come with the scheduled-jobs change.
- **Redesigning the visual language.** The warm Claude-inspired palette, spacing, and type
  scale stay; this is about controls, states, and reversibility — not a re-skin.
- **Journal semantic search.** Text search only here; embedding-based search remains
  deferred, as it has been since the journal shipped.
- **The four findings needing Narendra's eyes** (`--faint` contrast, spacing rhythm,
  animation timing, the date-picker icon) — carried into implementation, where he can
  judge them live over HMR rather than from a description.
