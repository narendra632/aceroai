# frontend — aceroai web app

The web client for aceroai: a Claude-inspired, mobile-responsive chat. React 19
+ Vite + Tailwind v4. It talks to the FastAPI backend, streams replies token by
token, and keeps you logged in with a cookie.

> Architecture rationale lives in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
> This README is the *what & where* for the frontend.

## Run it

From `frontend/`:

| Task | Command |
|---|---|
| Dev server | `npm run dev` (serves `http://localhost:5173`) |
| Type-check + build | `npm run build` |
| Lint | `npm run lint` |

The backend must be running (`uv run uvicorn app.main:app --reload` from
`backend/`) and the single user seeded. Log in with that user's email/password.

## How it works

**Auth.** `App.tsx` calls `/api/auth/me` on load. No valid cookie → it shows
`LoginScreen`; a valid cookie → `ChatLayout`. Login/logout just flip that state.
Every request sends `credentials: "include"` so the httpOnly auth cookie rides
along — the token is never stored in JS.

**Streaming.** Chat is a `POST` that returns Server-Sent Events, so the browser's
`EventSource` (GET-only, no cookies) won't do. `lib/api.ts`'s `streamChat`
instead uses `fetch` + a body reader, splitting the stream into SSE frames and
`yield`ing `{event, data}` (`session` → id, `delta` → text chunk, `done`,
`error`). `ChatLayout` appends each delta to the in-progress assistant bubble.

## File guide

| Path | Role |
|---|---|
| `index.html` | SPA shell; sets the page title |
| `src/main.tsx` | React entry — mounts `<App/>`, imports the theme |
| `src/App.tsx` | Auth gate: LoginScreen vs ChatLayout |
| `src/index.css` | Tailwind v4 + the warm Claude-inspired theme (light/dark) |
| `src/lib/api.ts` | All backend calls + the `streamChat` SSE reader |
| `src/components/LoginScreen.tsx` | Centered sign-in card |
| `src/components/ChatLayout.tsx` | Orchestrator: sessions, messages, streaming, drawer state |
| `src/components/Sidebar.tsx` | Session list + New chat + sign out; drawer on mobile |
| `src/components/MessageList.tsx` | Scrollable transcript + empty state + auto-scroll |
| `src/components/MessageBubble.tsx` | One message (user right, assistant left, streaming caret) |
| `src/components/Composer.tsx` | Auto-growing input; Enter sends, Shift+Enter newlines |
| `vite.config.ts` | Vite with the React + Tailwind plugins |

## Theme & responsiveness

Colors are Tailwind v4 `@theme` tokens (`bg-paper`, `text-ink`, `bg-clay`, …) in
`src/index.css`; a `prefers-color-scheme: dark` block swaps the CSS variables, so
light/dark need no JS. The layout is mobile-first: the sidebar is an off-canvas
drawer below the `md` breakpoint (hamburger to open, tap the backdrop to close)
and docked from `md` up. Tap targets are ≥44px and the transcript never scrolls
horizontally.

## Config

`VITE_API_URL` (in `.env.development`) points at the backend, default
`http://localhost:8000`. No secrets live here — the frontend only ever holds the
API's base URL.
