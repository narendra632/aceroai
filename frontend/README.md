# frontend — aceroai web app

The web client for aceroai: a Claude-inspired, mobile-first app with four views —
**Chat**, **Tasks**, **Journal**, and **Settings**. React 19 + Vite + Tailwind v4, with
**shadcn/ui** components and **lucide** icons. It talks to the FastAPI backend,
streams replies with a smooth typewriter reveal, renders markdown, and keeps you
logged in with a bearer token.

> Architecture rationale lives in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
> This README is the *what & where* for the frontend.

## Run it

From `frontend/`:

| Task | Command |
|---|---|
| Dev server | `npm run dev` (serves `http://localhost:5173`) |
| Type-check + build | `npm run build` |
| Lint | `npm run lint` |
| Add a shadcn component | `npx shadcn@latest add <name>` |

The backend must be running (`uv run uvicorn app.main:app --reload` from
`backend/`) and the single user seeded. Keep the frontend on **5173** — the
backend's CORS is pinned to that origin.

## How it works

**Auth.** `App.tsx` calls `/api/auth/me` on load. Not signed in → `LoginScreen`;
signed in → `AppShell`. Login returns a JWT that `lib/api.ts` stores in
`localStorage` and sends as an `Authorization: Bearer …` header — this works
cross-site (Vercel frontend ↔ DuckDNS backend), where a third-party cookie is
blocked by browsers. (Trade-off + the single-domain alternative: see
`../docs/DEPLOYMENT-EXPLAINED.md`.)

**Navigation.** `AppShell` holds the current view and a single sidebar (docked on
desktop, a drawer on mobile) with **Chat / Tasks / Journal / Settings**. Chat state lives in
the shell so switching views never drops an open conversation or an in-flight
stream. `TasksView` and `JournalView` are self-contained CRUD screens over
`/api/tasks` and `/api/journal`; the assistant can also drive both from Chat, and
a **"working…"** indicator shows while it runs a tool.

**Streaming + smooth reveal.** Chat is a `POST` returning Server-Sent Events, so
we can't use `EventSource` (GET-only, no cookies). `lib/api.ts`'s `streamChat`
uses `fetch` + a body reader and yields `{event, data}` (`session`, `delta`,
`done`, `error`); it accepts an `AbortSignal` for Stop. Gemini sends text in a
few big chunks, so `hooks/useSmoothReveal.ts` buffers incoming text and reveals
it at a steady, adaptive rate (rAF) — the typewriter feel. While waiting for the
first token, a `ThinkingDots` indicator shows; **Stop** aborts the fetch and
keeps the partial text.

**Markdown.** Assistant messages render through `Markdown.tsx`
(`react-markdown` + `remark-gfm`), which does **not** execute raw HTML, so model
output is safe. User messages stay plain text.

**Theme.** Light/dark is driven by a `.dark` class on `<html>`. A tiny inline
script in `index.html` sets it before first paint (from `localStorage`, else OS
preference) to avoid a flash; `hooks/useTheme.ts` + the sidebar toggle flip and
persist it.

## File guide

| Path | Role |
|---|---|
| `index.html` | SPA shell; title; no-flash theme script |
| `src/main.tsx` | React entry — mounts `<App/>`, imports the theme |
| `src/App.tsx` | Auth gate (LoginScreen vs AppShell) inside `TooltipProvider` |
| `src/index.css` | Tailwind v4 + shadcn tokens in a warm palette + animations |
| `src/lib/api.ts` | Backend calls (auth, chat SSE, tasks, journal) + the token header |
| `src/lib/utils.ts` | `cn()` class-merge helper (shadcn) |
| `src/hooks/useSmoothReveal.ts` | Steady-rate typewriter reveal of streamed text |
| `src/hooks/useTheme.ts` | Light/dark toggle + persistence |
| `src/components/AppShell.tsx` | Top-level shell: view switch + chat state (sessions, streaming, abort) |
| `src/components/Sidebar.tsx` | Chat/Tasks/Journal/Settings nav + (in chat) session list; theme, sign out; mobile drawer |
| `src/components/TasksView.tsx` | Tasks screen: quick-add, complete, priority, due, delete |
| `src/components/JournalView.tsx` | Journal screen: dated entries, mood, tags |
| `src/components/SettingsView.tsx` | Pick AI provider + chat/think-harder models; read-only pinned memory model |
| `src/components/MessageList.tsx` | Transcript + live streaming bubble + "working…" + empty state |
| `src/components/MessageBubble.tsx` | One message (markdown + copy for assistant) |
| `src/components/Markdown.tsx` | Safe markdown renderer |
| `src/components/ThinkingDots.tsx` | Animated first-token indicator |
| `src/components/Composer.tsx` | Auto-grow input; send / stop button |
| `src/components/LoginScreen.tsx` | Sign-in card |
| `src/components/TaskSheet.tsx` | Task detail panel — title, notes, due, priority, status, snooze |
| `src/components/ui/*` | Shared primitives (below) |
| `src/hooks/useOptimisticList.ts` | Instant list mutations with rollback on failure |
| `src/hooks/useToast.ts` | Toast context + `useToast()` (kept apart from the provider so HMR works) |

## Shared primitives

Built once and used by every screen, so the same interaction cannot behave two ways.
All are composed from **`radix-ui`, which was already a dependency** — none of them
required a new package.

| Primitive | Why it exists |
|---|---|
| `ui/select.tsx` | A native `<select>` delegates its popup to the OS, so it ignores the palette entirely — a white list inside a dark app |
| `ui/date-picker.tsx` | Hand-built calendar on Radix Popover + Today/Tomorrow/Next-week presets. Formats **local** time; `toISOString()` would shift to UTC and can land a due date on the wrong day |
| `ui/sheet.tsx` | Detail panel — bottom on mobile, right on desktop. Radix Dialog supplies focus trapping, Escape, and scroll lock |
| `ui/toast.tsx` | The only feedback channel, and the carrier for **Undo** |
| `ui/states.tsx` | `ListSkeleton` / `EmptyState` / `ErrorState`. The last one matters: a failed load used to render the empty state, telling the user "you have nothing" when the request had failed |
| `ui/tag-input.tsx` | Tag chips with suggestions from tags already in use |

**Deleting is reversible, not confirmed.** Delete happens immediately and a toast
offers Undo for ~7 s — the Gmail/Linear pattern. It adds no friction to the
intentional case while still covering the mistake you notice a second later. The
backend soft-deletes and `POST …/restore` brings the record back **with the same
id**, so anything referring to it still points at the same thing.

**Touch targets** reach the ~44 px guideline through a `.touch-target` hit-area
overlay rather than by growing the visible control, so dense rows stay dense.

## Dependencies

Beyond React/Vite/Tailwind: `react-markdown` + `remark-gfm` (markdown),
`lucide-react` (icons), and the shadcn/ui stack (`class-variance-authority`,
`clsx`, `tailwind-merge`, `tw-animate-css`, `radix-ui`). Charts are intentionally
not included yet — they'll be chosen against the first data screen.

**`radix-ui` is already installed**, so custom `Select`, `Popover`, `Dialog`, and
similar controls need **no new dependency** — which is why the audit below treats
the remaining native `<select>` / `datetime-local` elements as a choice to revisit,
not a constraint.

## Known UI/UX gaps

The interface is functional but not yet finished to product standard. Every known
gap is inventoried in [`../docs/UI-AUDIT.md`](../docs/UI-AUDIT.md) — read it before
adding a screen, so new work meets the standard instead of extending the debt.

## Config

`VITE_API_URL` (in `.env.development`) points at the backend, default
`http://localhost:8000`. No secrets live here.

## Deploying

Hosted on **Vercel** (Root Directory `frontend`, framework Vite), which
auto-deploys on every push to `main`. Set `VITE_API_URL` in the Vercel project to
the backend's HTTPS URL (the DuckDNS subdomain). Full runbook:
[`../docs/DEPLOY.md`](../docs/DEPLOY.md).
