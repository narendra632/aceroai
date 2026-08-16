## Context

38 audit findings, all approved for fixing. The interesting decisions are not *what* to
fix — the audit settled that — but **how**, because three of the choices have consequences
well beyond the UI.

## Decision 1 — soft delete, not a client-side undo timer

Narendra chose the **undo toast** over a confirm dialog. That choice forces a second one:
the deleted row has to survive long enough to be restored. Two ways:

**A. Client-side hold** — hide the row locally, start a 7 s timer, fire `DELETE` only when
it expires. No migration.

**B. Soft delete** — `DELETE` sets `deleted_at`; Undo clears it. Migration required.

**Chosen: B.** Option A looks cheaper and fails in ways that are hard to defend:

- **Close the tab during the hold and the delete never happens.** The item silently
  returns — the user watched it disappear and it came back. That is worse than no undo.
- **Refresh during the hold and the undo is gone**, but the delete may or may not have
  fired depending on timing.
- It cannot work across devices — delete on the phone, and the laptop's view is stale in a
  way nothing reconciles.

Soft delete costs a migration and introduces one real risk — **a query that forgets
`deleted_at IS NULL` leaks deleted data.** What makes that risk acceptable here
specifically is the existing architecture: **`services/` is already the single source of
truth for both the REST API and the assistant's tools.** There is exactly one layer to get
right, and getting it right there covers every consumer including the model. If reads were
scattered across routes, this decision would be much harder to justify.

The filter is therefore applied **in the service query builders**, never in routes, and
tested from four directions: the API, `list_tasks`, the **composer's injected task block**,
and the assistant's tools. The composer path matters most — a leak there feeds deleted
tasks straight into the model's context, where it would confidently act on them.

**Not doing:** a Trash view, or purging old rows. Both become possible; neither is needed
now, and building them speculatively would widen a change that is already large.

## Decision 2 — the primitives come first, and screens are rewritten against them

The tempting order is screen-by-screen: fix Tasks fully, then Journal, then Chat. Rejected.
Every screen needs the same six primitives, so screen-first means building `Select` inside
`TasksView`, then extracting it when `SettingsView` needs it — the extraction never quite
happens, and the app ends up with two dropdowns that differ subtly. That is precisely how
the current inconsistencies arose: `Sidebar` solved touch-reveal with `max-md:opacity-60`
while `MessageBubble` left `opacity-0` with no fallback. **Same problem, two answers,
because nobody built it once.**

So: primitives first (§2), screens after (§3–§6). It also gives Narendra a natural review
point — the primitives can be judged over HMR before five screens depend on them.

## Decision 3 — the DatePicker is hand-built on Radix Popover

Already agreed: no `react-day-picker`. Full control over theming so it matches the palette
in both modes, and no dependency. The work is a month grid from `Intl.DateTimeFormat`,
arrow-key navigation, and `aria-selected` — roughly 150 lines.

**Honest cost:** `react-day-picker` has years of edge cases handled (locales, DST
boundaries, range selection, screen-reader semantics). Hand-building means we own those.
Accepted because this app needs one date, in one locale, with no ranges — the narrow case
the library's generality is priced for. **If range selection or localisation ever
arrives, revisit rather than keep extending.**

Presets (**Today · Tomorrow · Next week**) sit above the calendar, since audit finding 30
notes the common case shouldn't require the full grid.

## Decision 4 — optimistic updates need a rollback path, or they are a lie

`useOptimisticList` applies the change locally, fires the request, and **reverts plus
raises an error toast on failure**. Without the revert, an optimistic UI simply shows
false state after an error — strictly worse than today's slow-but-honest refetch.

Ordering rule: **the optimistic update and the undo toast must not fight.** Delete is
optimistic (row vanishes instantly) *and* undoable (toast restores it). The row is removed
locally, `DELETE` is sent immediately, and Undo calls `restore`. If the delete itself
fails, the row returns and the toast reports the failure rather than offering Undo.

## Decision 5 — the task sheet is the home for everything a task has

Narendra chose the detail sheet. Beyond editing, it resolves a structural problem: `notes`
and `snoozed_until` **have no home in a list row**. Cramming them in is what produced the
truncated "Med" dropdown visible in the current UI.

Composition: Radix `Dialog` positioned as a sheet — bottom on mobile, right on desktop.
shadcn's `Sheet` is exactly this, so no new dependency. It gives focus trapping, escape
handling, and scroll locking for free — three things a hand-rolled panel gets wrong.

## Decision 6 — auto-scroll follows the user, not the stream

Finding 6 (`scrollIntoView` on every update) is fixed with the standard rule: **stick to
the bottom only while the user is already near it** (~100 px). Scroll up and streaming
stops yanking; a "jump to latest" affordance appears instead (finding 32). Both findings
are one mechanism, which is why they are fixed together.

## Risks

- **This is a large change.** Six primitives, five screens, a migration, six routes. The
  task list is ordered so each section is independently reviewable, and §2 ends at a
  natural checkpoint. If it proves too big in practice, §5–§6 (Chat and cross-cutting
  polish) can split into a follow-up without leaving anything half-built.
- **Soft delete touches the model's context.** Called out above; tested explicitly rather
  than assumed.
- **Hand-built calendar accessibility.** Keyboard navigation and screen-reader semantics
  are easy to get subtly wrong. Tested against keyboard-only use; noted as the first thing
  to revisit if it disappoints.
- **Four findings still need Narendra's eyes.** They cannot be closed from source and are
  deliberately scheduled for live review during implementation.
