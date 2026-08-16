> Finding numbers in **(n)** refer to `docs/UI-AUDIT.md`. All 38 are mapped; none is
> dropped silently.

## 0. Verify before building

- [x] 0.1 ✅ `radix-ui@1.6.7` exports **all** of `Select`, `Popover`, `Dialog`, `Toast`, `AlertDialog`, `VisuallyHidden`, `ScrollArea`. **No dependency needs adding**
- [x] 0.2 ⚠ **Violation found.** `api/chat.py` queries `ChatSession` and `Message` **directly in its routes** — sessions have **no service layer**, unlike tasks and journal. The soft-delete "one place to apply the filter" guarantee therefore does **not** hold for sessions. **Fix: create `services/sessions.py` first (1.3).** Tasks and journal were clean — `services/tasks.py:85` and `services/journal.py:47` own their queries
- [x] 0.3 ⚠ **This task's own premise was wrong.** `snoozed_until` is already in `TaskUpdate` (`schemas.py:52`), already passed through `PATCH /api/tasks/{id}`, and already writable by the assistant via `update_task`. `services/tasks.snooze_task()` is an **unused wrapper called only by a test**. **Snoozing needs no new route — the gap is UI-only.** Old task 1.7 is void; `proposal.md` corrected

## 1. Backend — reversible deletes and the missing routes

- [x] 1.1 **`services/sessions.py` first** *(from 0.2)* — move `list_sessions`, `get_history`, and the owner check out of `api/chat.py` so sessions have the same single-source-of-truth layer tasks and journal already have. **Without this the soft-delete filter has two homes and `design.md` Decision 1 does not hold.** Routes become thin, per golden rule 1
- [x] 1.2 **Migration 004:** nullable `deleted_at timestamptz` on `tasks`, `journal_entries`, `chat_sessions`; partial indexes on the active rows
- [x] 1.3 `db/models.py`: add the column to all three models
- [x] 1.4 **Apply the exclusion in the `services/` query builders, never in routes** — one place, so the API, the composer, and the assistant's tools all inherit it *(design.md Decision 1)*
- [x] 1.5 Convert `delete_*` to set `deleted_at`; add `restore_*` for all three. **Session delete currently hard-deletes its `Message` rows (`api/chat.py:73`) — that must stop, or restore returns an empty conversation**
- [x] 1.6 Routes: `POST /api/tasks/{id}/restore` · `POST /api/journal/{id}/restore` · `POST /api/chat/sessions/{id}/restore`
- [x] 1.7 `PATCH /api/chat/sessions/{id}` — **session rename; no such route exists today** (8)
- [x] 1.8 `GET /api/journal` gains `q` (text search via `ILIKE`, not `tsvector` — simpler and indistinguishable at this scale), `limit`, `offset` (20)
- [x] 1.9 `POST /api/chat/sessions/{id}/regenerate` — drop the trailing assistant message so the turn can be re-streamed (25, partial)
- [x] 1.10 Tests: soft-deleted records are invisible to the API, to `list_tasks`, to **`composer.build_context`'s task block**, and to the assistant's tools — *the composer path matters most; a leak there feeds deleted tasks into the model's context*
- [x] 1.11 Tests: restore is owner-scoped; restoring a record belonging to someone else 404s
- [x] 1.12 Tests: `find_duplicate` ignores soft-deleted tasks — otherwise a deleted task silently blocks re-creating one with the same title, which would look like the app refusing to work

## 2. Frontend primitives — built once, before any screen uses them

- [x] 2.1 `ui/select.tsx` — Radix Select, themed to the palette in both modes (1)
- [x] 2.2 `ui/date-picker.tsx` — Radix Popover + a hand-built month grid from `Intl`; **Today / Tomorrow / Next week presets above the calendar** (2, 30)
- [x] 2.3 Keyboard support for the calendar: arrows, Home/End, PageUp/Down, Escape, `aria-selected` — *the part a library would have given us; tested keyboard-only*
- [x] 2.4 `ui/sheet.tsx` — Radix Dialog positioned bottom (mobile) / right (desktop), with focus trap and scroll lock
- [x] 2.5 `ui/toast.tsx` — Radix Toast with an **action slot for Undo**; success / error variants (7)
- [x] 2.6 `ui/skeleton.tsx`, `ui/empty-state.tsx`, `ui/error-state.tsx` (16, 17, 21, 31)
- [x] 2.7 `hooks/useOptimisticList.ts` — apply locally, fire the request, **revert and raise an error toast on failure** *(without the revert an optimistic UI just shows false state — see design.md Decision 4)* (9)
- [x] 2.8 Raise `button.tsx` icon sizes to a **44 px** minimum touch target; audit every call site for layout fallout (13)
- [x] 2.9 **Checkpoint — Narendra reviews the primitives over HMR before five screens depend on them**

## 3. Tasks screen

- [x] 3.1 Replace both native `<select>` elements with `Select` (1)
- [x] 3.2 Replace `datetime-local` with `DatePicker` (2)
- [x] 3.3 **Task detail sheet** — title, notes, due, priority, status, snooze. **Surfaces `notes` and `snoozed_until`, which the assistant can already write but the UI has never shown** (10, 11)
- [x] 3.4 Delete → optimistic removal + **Undo toast** (4)
- [x] 3.5 Optimistic complete / priority change; drop the refetch-everything pattern (9)
- [x] 3.6 Loading skeleton, empty state, **error state** — a failed load currently renders as "you have nothing", which is a lie (16, 17)
- [x] 3.7 Group by Today / This week / Later; add a sort control (29)
- [x] 3.8 Overdue gets an **icon or badge, not colour alone** — accessibility, not polish (29)
- [x] 3.9 Delete icon reveals on hover with a touch fallback, matching `Sidebar` (15)

## 4. Journal screen

- [x] 4.1 Entries become **editable** (12)
- [x] 4.2 Delete → optimistic + Undo toast; fix the **24 px** touch target (4, 13)
- [x] 4.3 Tags become a **chip/token input** with autocomplete from existing tags (19)
- [x] 4.4 Search box wired to `?q=`; pagination or infinite scroll wired to `limit`/`offset` (20)
- [x] 4.5 Loading / empty / error states (16, 17)
- [x] 4.6 Optimistic add and delete (9)

## 5. Chat, sidebar and message list

- [x] 5.1 **Session rename** — inline in the sidebar, wired to the new PATCH (8)
- [x] 5.2 Session delete → optimistic + Undo toast (4)
- [x] 5.3 Group sessions by date (Today / Yesterday / Previous 7 days); add search (28)
- [x] 5.4 **Auto-scroll sticks to the bottom only when the user is already near it**, plus a "jump to latest" affordance — *one mechanism, two findings* (6, 32)
- [x] 5.5 **Preserve the composer draft across view switches** — lift it into `AppShell`, where chat state already lives; it was the one piece left behind (3)
- [x] 5.6 Character counter as the 16,000-char cap approaches (18)
- [x] 5.7 Show the composer hint on mobile too — the platform where Enter-to-send is least obvious (23)
- [x] 5.8 Copy button reachable on touch, matching `Sidebar`'s pattern (14)
- [x] 5.9 Message timestamps (24); copy on user messages (26)
- [x] 5.10 **Regenerate the last reply** (25, partial) — drop the trailing assistant message and re-stream. Needs one endpoint. ⚠ *`memory.extract_and_store` may already have learned facts from the discarded reply; regenerating does **not** retract them. Acceptable (facts are deduped and supersedable) but must be stated in `ARCHITECTURE.md`, not discovered later.* **Edit-and-resend is deliberately deferred** — truncating mid-conversation raises the same question with no cheap answer
- [x] 5.11 Chat errors get a **retry action** instead of a dead `⚠` bubble (27)
- [x] 5.12 Suggested prompts on the empty state (31)
- [x] 5.13 Replace `key={i}` with a stable id (33)
- [x] 5.14 Loading state while `getMessages` resolves; handle `listSessions` failure (16, 17)

## 6. Settings, login, cross-cutting

- [x] 6.1 Replace both `ModelField` native selects with `Select` (1)
- [x] 6.2 **Switching provider must not silently discard model choices** — preserve, or state clearly what will change (5)
- [x] 6.3 Retry action when settings fail to load (21)
- [x] 6.4 Fix both `setTimeout` leaks — state set after unmount (22)
- [x] 6.5 Simplify the "Other…" custom-model flow (35)
- [x] 6.6 Login: show-password toggle; `role="alert"` on the error (34)
- [x] 6.7 Keyboard shortcuts — new chat, focus composer, switch view; discoverable, not hidden (36)
- [ ] 6.8 **Narendra's live review of the four visual findings** — `--faint` contrast in dark mode (37), spacing/density/animation (38), the date-picker icon (2), overdue treatment (29)

## 7. Verify and hand over

- [x] 7.1 `uv run ruff format .` · `uv run ruff check .` · `uv run pytest` from `backend/`
- [x] 7.2 `npm run build` (type-check) and `npm run lint` from `frontend/`
- [ ] 7.3 Exercise at ~375 px and desktop: no horizontal overflow, sheet reachable, 44 px targets, composer clear of the on-screen keyboard
- [ ] 7.4 Keyboard-only pass: tab order, focus-visible, the calendar, the sheet's focus trap
- [ ] 7.5 **Verify soft delete end-to-end**: delete a task, confirm Acero cannot see it in the same conversation, then Undo and confirm it returns
- [x] 7.6 Confirm `.env` is not staged
- [x] 7.7 **Docs and diagrams reflect what was built** *(golden rule 11)*: mark the 38 findings resolved in `UI-AUDIT.md`, add `deleted_at` to the `ARCHITECTURE.md` ER diagram, document the primitives in `frontend/README.md`, note the new routes in `backend/README.md`
- [ ] 7.8 `/opsx:archive`
