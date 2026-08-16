# UI-AUDIT.md — the gap between "it works" and "it's finished"

> **Status: for review.** This is an inventory, not a plan of record. Narendra strikes,
> adds, and reorders; what survives becomes the scope of the UI change that follows.
>
> *Audited 2026-08-16 against all 14 components.*

## How to read this

Every finding is marked with how it was established:

| Mark | Meaning |
|---|---|
| 🔍 **code** | Derived by reading the source. Reliable — the behavior is in the file. |
| 👁 **eyes** | Needs Narendra to look. Spacing, contrast, and motion **cannot** be judged from source. |

**A limitation worth stating plainly:** there is no browser or screenshot tool available in
this environment. Everything below about *structure, state, controls, and accessibility* is
solid; anything about *how it looks* is inferred and marked 👁. This audit is not a
substitute for your eyes — it is the half of the work that can be done without them.

Severity: **P1** breaks the product feel or loses user work · **P2** a visible quality gap ·
**P3** polish.

---

## The pattern behind most of this

Three habits produced the majority of findings. Naming them is more useful than the list:

1. **The fastest control that worked was chosen.** Four native `<select>` elements and one
   `datetime-local` input. They function, they're accessible, and they render as the
   operating system's widget — a white popup inside a dark app. Radix was already
   installed the whole time.
2. **Every mutation refetches everything.** `create → await → load()`. So the UI waits on a
   network round-trip before it reflects your own click.
3. **Nothing ever confirms, and nothing can be undone.** Three destructive actions, no
   dialog, no toast, no undo. Success and failure look identical: nothing happens.

---

## P1 — must fix

| # | Finding | Where | Mark |
|---|---|---|---|
| 1 | **Native `<select>` × 4.** Renders the OS widget — the blue-highlighted list in your screenshot. Not themeable, ignores the palette entirely. | [TasksView:100](../frontend/src/components/TasksView.tsx#L100), [:164](../frontend/src/components/TasksView.tsx#L164), [SettingsView:31](../frontend/src/components/SettingsView.tsx#L31) (×2 via `ModelField`) | 🔍 |
| 2 | **Native `datetime-local`.** White OS calendar inside a dark UI; the picker icon is near-black on a dark field, effectively invisible. Also `dd-mm-yyyy --:--` is a poor empty state. | [TasksView:93](../frontend/src/components/TasksView.tsx#L93) | 🔍 + 👁 |
| 3 | **Typed message is lost on view switch.** `Composer` unmounts when you leave Chat, so a half-written message is gone on return. Chat state was deliberately lifted to `AppShell` to survive this — the draft was missed. | [AppShell:164-175](../frontend/src/components/AppShell.tsx#L164-L175) | 🔍 |
| 4 | **Destructive actions have no confirmation and no undo** — task delete, journal delete, session delete. One mis-tap is permanent. `SOUL.md` explicitly requires the *assistant* to confirm before deleting; the UI holds itself to a lower standard than the AI. | [TasksView:176](../frontend/src/components/TasksView.tsx#L176), [JournalView:108](../frontend/src/components/JournalView.tsx#L108), [AppShell:49](../frontend/src/components/AppShell.tsx#L49) | 🔍 |
| 5 | **Switching provider silently discards your model choices.** Clicking a provider chip overwrites both model fields with `catalog[0]` — no warning, no undo. | [SettingsView:139-145](../frontend/src/components/SettingsView.tsx#L139-L145) | 🔍 |
| 6 | **Auto-scroll fights the user.** `scrollIntoView` fires on every streaming update with no "is the user near the bottom?" check — scroll up to re-read while a reply streams and you're yanked back down. | [MessageList:26-28](../frontend/src/components/MessageList.tsx#L26-L28) | 🔍 |
| 7 | **No feedback on any action, anywhere.** No toast, no inline confirmation. A save that succeeded and a save that failed both look like nothing happening. (Settings is the lone exception — it has a "Saved" tick.) | app-wide | 🔍 |
| 8 | **Chat sessions cannot be renamed.** Titles are auto-generated from the first message and permanent. The sidebar is the main navigation and it fills with unhelpful labels. | [Sidebar:120-131](../frontend/src/components/Sidebar.tsx#L120-L131) | 🔍 |

## P2 — should fix

| # | Finding | Where | Mark |
|---|---|---|---|
| 9 | **Full refetch after every mutation** instead of optimistic update — completing a task waits on a round-trip before the checkbox moves. | [TasksView:50-61](../frontend/src/components/TasksView.tsx#L50-L61), [JournalView:31-48](../frontend/src/components/JournalView.tsx#L31-L48) | 🔍 |
| 10 | **Tasks cannot be edited after creation.** Only priority and delete. Title, notes, and due date are fixed — so a typo means delete and retype. | [TasksView](../frontend/src/components/TasksView.tsx) | 🔍 |
| 11 | **`notes` and `snoozed_until` have no UI at all** — both exist in the schema, the API, and the assistant's tools. The assistant can set notes you can never see or edit. | [TasksView](../frontend/src/components/TasksView.tsx) | 🔍 |
| 12 | **Journal entries cannot be edited** — write-once, delete-only. | [JournalView](../frontend/src/components/JournalView.tsx) | 🔍 |
| 13 | **Touch targets below the 44 px guideline.** `icon-xs` = **24 px** (journal delete), `icon-sm` = 32 px (task delete, sidebar), `icon-lg` = 40 px (send). | [button.tsx:29-31](../frontend/src/components/ui/button.tsx#L29-L31) | 🔍 |
| 14 | **Copy button is invisible on touch devices.** `opacity-0 group-hover:opacity-100` with no touch fallback — and `Sidebar` already solved exactly this with `max-md:opacity-60`. Same problem, two answers. | [MessageBubble:33](../frontend/src/components/MessageBubble.tsx#L33) vs [Sidebar:141](../frontend/src/components/Sidebar.tsx#L141) | 🔍 |
| 15 | **Task delete icon is permanently visible; session delete reveals on hover.** The same action behaves two different ways in two lists. | [TasksView:174](../frontend/src/components/TasksView.tsx#L174) vs [Sidebar:132-145](../frontend/src/components/Sidebar.tsx#L132-L145) | 🔍 |
| 16 | **No loading states anywhere.** Lists render empty, then pop. Opening a session awaits `getMessages` with no indication. | [AppShell:41-47](../frontend/src/components/AppShell.tsx#L41-L47), all three CRUD views | 🔍 |
| 17 | **Failed loads fail silently.** `listTasks`, `listJournal`, and `listSessions` have no `.catch` — a network error renders as "you have nothing", which is a lie. | [TasksView:30](../frontend/src/components/TasksView.tsx#L30), [JournalView:27](../frontend/src/components/JournalView.tsx#L27), [AppShell:32-34](../frontend/src/components/AppShell.tsx#L32-L34) | 🔍 |
| 18 | **No character counter** though the backend rejects input over `MAX_INPUT_CHARS` (16,000). The user hits an invisible wall. | [Composer](../frontend/src/components/Composer.tsx) | 🔍 |
| 19 | **Tags are a raw comma-separated text field** — no chips, no autocomplete from existing tags, no way to see what tags exist. | [JournalView:80-85](../frontend/src/components/JournalView.tsx#L80-L85) | 🔍 |
| 20 | **Journal has no search, filter, or pagination** — it loads every entry, forever, and is the one screen guaranteed to grow without bound. | [JournalView](../frontend/src/components/JournalView.tsx) | 🔍 |
| 21 | **Settings has no retry** when loading fails — it renders the error text and stops. | [SettingsView:89-97](../frontend/src/components/SettingsView.tsx#L89-L97) | 🔍 |
| 22 | **`setTimeout` without cleanup** in two places — sets state after unmount. | [SettingsView:81](../frontend/src/components/SettingsView.tsx#L81), [MessageBubble:20](../frontend/src/components/MessageBubble.tsx#L20) | 🔍 |
| 23 | **The composer hint is hidden on mobile** (`hidden sm:block`) — phone users are never told Enter sends and Shift+Enter breaks the line, on the platform where it's least obvious. | [Composer:89](../frontend/src/components/Composer.tsx#L89) | 🔍 |

## P3 — polish

| # | Finding | Where | Mark |
|---|---|---|---|
| 24 | No message timestamps anywhere. | MessageBubble | 🔍 |
| 25 | No regenerate, or edit-and-resend, on an assistant reply. | MessageBubble | 🔍 |
| 26 | User messages have no copy button (assistant messages do). | [MessageBubble:44-52](../frontend/src/components/MessageBubble.tsx#L44-L52) | 🔍 |
| 27 | Chat errors render as a `⚠` bubble in the transcript with no retry action. | [AppShell:105-116](../frontend/src/components/AppShell.tsx#L105-L116) | 🔍 |
| 28 | Sessions are a flat list — no date grouping (Today / Previous 7 days), no search, no pin. | Sidebar | 🔍 |
| 29 | Tasks have no grouping (Today / This week / Later) and no sort control; overdue is conveyed by text color alone — a problem for color-blind users and easy to miss. | TasksView | 🔍 + 👁 |
| 30 | No quick due-date presets (Today, Tomorrow, Next week) — the common cases need the full picker. | TasksView | 🔍 |
| 31 | Empty chat state offers no suggested prompts. | [MessageList:30-39](../frontend/src/components/MessageList.tsx#L30-L39) | 🔍 |
| 32 | No "scroll to bottom" affordance when scrolled up mid-stream. | MessageList | 🔍 |
| 33 | `key={i}` (array index) on messages. | [MessageList:45](../frontend/src/components/MessageList.tsx#L45) | 🔍 |
| 34 | No show-password toggle; the login error isn't announced (`role="alert"`). | LoginScreen | 🔍 |
| 35 | The "Other…" custom-model flow is two-step and awkward — pick "Other", then a second input appears. | [SettingsView:43-50](../frontend/src/components/SettingsView.tsx#L43-L50) | 🔍 |
| 36 | No keyboard shortcuts (new chat, focus composer, switch view). | app-wide | 🔍 |
| 37 | Contrast of `--faint` (`#7d7666` on `#1f1e1b`) against WCAG AA — needs measuring. | [index.css:55](../frontend/src/index.css#L55) | 👁 |
| 38 | Spacing rhythm, animation timing, and visual density across views. | app-wide | 👁 |

---

## What's already good

Worth recording so it isn't "fixed" away:

- **Settings' live indicator** — the pulsing "Answering with…" dot showing *saved* state, not
  the pending picker, plus the `active` badge and the unsaved-changes hint. This is the
  standard the rest of the app should meet.
- **The pinned Memory-model card** — explains a subtle, dangerous constraint in plain English.
- **Streaming feel** — `useSmoothReveal` buffering into a steady typewriter reveal, with
  `ThinkingDots` before the first token and a working Stop.
- **Mood buttons** — proper `aria-label` and `aria-pressed`.
- **Sidebar's touch fallback** (`max-md:opacity-60`) — the right pattern; it just wasn't
  applied elsewhere.
- **Markdown is rendered without raw HTML**, so model output can't inject markup.
- **Theme has no flash on load** (inline script before first paint).

---

## The primitives this implies

Most findings collapse into six missing building blocks. Building these once fixes the
list in a system rather than patching 14 files independently:

| Primitive | Fixes | Cost |
|---|---|---|
| **`Select`** | 1 | Radix — **already installed** |
| **`DatePicker`** | 2, 30 | Radix Popover + a hand-built calendar — **0 new deps** (agreed) |
| **`ConfirmDialog`** | 4 | Radix AlertDialog — already installed |
| **`Toast`** | 7, 27 | Radix Toast — already installed |
| **`Skeleton` + `EmptyState` + `ErrorState`** | 16, 17, 21, 31 | Plain components |
| **A mutation helper** (optimistic + rollback + toast on failure) | 9, 5, 17 | Plain hook |

**Every one of these needs zero new dependencies.** `radix-ui@1.6.7` is already in
`package.json` — the native controls were never a constraint, only a shortcut.

---

## Decisions — reviewed and set by Narendra, 2026-08-16

**Scope: all 38 findings.** Not a phased cut — the interface is brought to product
standard in one deliberate pass. P3 is included because the small things (timestamps,
grouping, keyboard access, suggested prompts) are exactly what separates a tool that
works from one that feels finished.

**Destructive actions: delete immediately, offer Undo in a toast (~7 s).** Chosen over a
confirm dialog because it adds no friction to intentional deletions while protecting
against the mistakes you only notice a second later — the Gmail/Linear/Notion pattern.

> ⚠ **This has a backend consequence the UI change must resolve.** Undo requires the row
> to survive the delete. Options: a **soft delete** (`deleted_at` column via migration —
> robust, but every query and every assistant tool must learn to exclude it), or a
> **client-side hold** (defer the API call ~7 s — no migration, but the undo dies on
> refresh or navigation, and the row must stay hidden meanwhile). To be designed in the
> UI change's `design.md`, not assumed here.

**Task editing: a detail sheet** — tapping a row opens a slide-over (bottom on mobile,
side on desktop) holding title, notes, due date, priority, and status. This is what
finally surfaces **`notes` and `snoozed_until`**, which exist in the schema and in the
assistant's tools but have never had any UI. The sheet pattern also suits the PWA that is
now two changes away.

**Still needs Narendra's eyes** (unchanged — these cannot be settled from source):
findings **37** (`--faint` contrast in dark mode) and **38** (spacing, density, animation
timing), plus visual confirmation of **2** (the date-picker icon) and **29** (overdue
conveyed by colour alone).
