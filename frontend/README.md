# frontend — aceroai web app

The web client for aceroai: a Claude-inspired, mobile-responsive chat. React 19
+ Vite + Tailwind v4, with **shadcn/ui** components and **lucide** icons. It talks
to the FastAPI backend, streams replies with a smooth typewriter reveal, renders
markdown, and keeps you logged in with a cookie.

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

**Auth.** `App.tsx` calls `/api/auth/me` on load. No valid cookie → `LoginScreen`;
valid cookie → `ChatLayout`. Every request sends `credentials: "include"` so the
httpOnly auth cookie rides along — the token is never in JS.

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
| `src/App.tsx` | Auth gate (LoginScreen vs ChatLayout) inside `TooltipProvider` |
| `src/index.css` | Tailwind v4 + shadcn tokens in a warm palette + animations |
| `src/lib/api.ts` | Backend calls + the `streamChat` SSE reader (with abort) |
| `src/lib/utils.ts` | `cn()` class-merge helper (shadcn) |
| `src/hooks/useSmoothReveal.ts` | Steady-rate typewriter reveal of streamed text |
| `src/hooks/useTheme.ts` | Light/dark toggle + persistence |
| `src/components/ChatLayout.tsx` | Orchestrator: sessions, messages, streaming, abort, drawer |
| `src/components/Sidebar.tsx` | Session list, New chat, theme toggle, sign out; mobile drawer |
| `src/components/MessageList.tsx` | Transcript + live streaming bubble + empty state |
| `src/components/MessageBubble.tsx` | One message (markdown + copy for assistant) |
| `src/components/Markdown.tsx` | Safe markdown renderer |
| `src/components/ThinkingDots.tsx` | Animated first-token indicator |
| `src/components/Composer.tsx` | Auto-grow input; send / stop button |
| `src/components/LoginScreen.tsx` | Sign-in card |
| `src/components/ui/*` | shadcn primitives (button, tooltip, dropdown-menu) |

## Dependencies

Beyond React/Vite/Tailwind: `react-markdown` + `remark-gfm` (markdown),
`lucide-react` (icons), and the shadcn/ui stack (`class-variance-authority`,
`clsx`, `tailwind-merge`, `tw-animate-css`, `radix-ui`). Charts are intentionally
not included yet — they'll be chosen against the first data screen (Feature 3).

## Config

`VITE_API_URL` (in `.env.development`) points at the backend, default
`http://localhost:8000`. No secrets live here.

## Deploying

Hosted on **Vercel** (Root Directory `frontend`, framework Vite), which
auto-deploys on every push to `main`. Set `VITE_API_URL` in the Vercel project to
the backend's HTTPS URL (the DuckDNS subdomain). Full runbook:
[`../docs/DEPLOY.md`](../docs/DEPLOY.md).
