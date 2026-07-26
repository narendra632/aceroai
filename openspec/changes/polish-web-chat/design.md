## Context

add-web-chat delivered a working SSE chat. Gemini's OpenAI-compatible endpoint
emits replies in a few large chunks after a multi-second "thinking" pause, so the
raw render feels like a dump. The stack is React 19 + Tailwind v4; the theme is
CSS-variable based; `MODEL_CHAT=gemini-3.5-flash` stays (chosen for answer
quality). This change is frontend-only apart from confirming the backend tolerates
client disconnect.

## Goals / Non-Goals

**Goals:**
- Make the chat feel like Claude/ChatGPT: smooth reveal, a clean thinking
  animation, markdown, stop control, copy, refined visuals, theme toggle.
- Keep it dependency-light and safe (no raw HTML execution from model output).

**Non-Goals:**
- Changing the model or backend streaming protocol.
- Message editing/regeneration, syntax highlighting themes, KaTeX (later).
- Persisting partial replies when the user stops (a stop discards the turn).

## Decisions

**1. Smoothing via a reveal queue, not raw render.**
Incoming deltas append to a `pending` buffer; a `requestAnimationFrame`/interval
loop moves characters from `pending` to `displayed` at a steady rate (adaptive:
speed up if the buffer grows so we never lag far behind, and flush fully on
`done`). This decouples display cadence from network cadence. *Alternative
rejected:* CSS-only animation — can't handle variable chunk sizes cleanly.

**2. Keep gemini-3.5-flash; mask latency with a thinking indicator.**
Per product choice, answer quality wins. A tasteful animated indicator (pulsing
dots / shimmer) shows until the first delta, so the wait reads as intentional.

**3. Stop via AbortController.**
`streamChat` accepts an `AbortSignal`; the Stop button aborts the fetch. The
server's `EventSourceResponse` generator is cancelled on disconnect
(sse-starlette), so no assistant row is persisted for a stopped turn — acceptable
and simplest. The already-revealed partial text stays on screen (client-only).

**4. Markdown with react-markdown + remark-gfm, no raw HTML.**
`react-markdown` does not render raw HTML by default (no `rehype-raw`), so model
output cannot inject scripts — safe. `remark-gfm` adds tables/strikethrough/task
lists. Assistant only; user messages stay plain. Minimal, well-maintained deps.

**5. Theme toggle via `data-theme` + localStorage.**
Default follows `prefers-color-scheme`; the toggle writes `data-theme` on
`<html>` and persists to localStorage. `index.css` gains
`:root[data-theme="dark"]` / `[data-theme="light"]` overrides alongside the
existing media query. No flash-of-wrong-theme: read localStorage in a tiny inline
script or on mount before paint.

**6. Icons via lucide-react; shadcn/ui foundation.**
Replace `↑ + ☰ ✕` glyphs with `lucide-react` icons (send, plus, menu, close,
copy, check, square/stop, sun/moon). Set up shadcn/ui (a `@/` path alias, a
`cn()` util from clsx + tailwind-merge, `components.json`) and pull in the few
components that improve the chat (Button, Tooltip, DropdownMenu). shadcn's
semantic tokens (`--background`, `--primary`, `--muted`, …) are mapped to our
warm Claude palette so the look stays ours, not the default zinc. Charts are
**not** installed — deferred to the first data screen (Feature 3), chosen then
against the real use case per the dataviz approach.

## Risks / Trade-offs

- **Reveal lag on very long replies** → adaptive rate + full flush on `done`
  guarantee we never fall behind at the end.
- **Markdown dep size** → react-markdown + remark-gfm are small and tree-shaken;
  acceptable for the UX gain.
- **Stop leaves an orphaned user message** (no assistant reply) → acceptable;
  the user chose to stop, and history stays coherent (a user turn with no answer).
- **Theme flash on load** → set `data-theme` before first paint.

## Migration Plan

Additive frontend change; `npm install react-markdown remark-gfm`. No DB or API
migration. Rollback = revert the branch commits and remove the two deps.

## Open Questions

- Code-block syntax highlighting (e.g., highlight.js) — deferred to keep deps
  minimal; plain styled code blocks for now.
