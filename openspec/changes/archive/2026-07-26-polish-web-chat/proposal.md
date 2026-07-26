## Why

Feature 1's chat works end to end but does not yet feel product-grade. Gemini
streams replies in a few large chunks, so the UI renders a long pause (the
model's thinking time) followed by a sudden text dump instead of the smooth
reveal users expect from Claude/ChatGPT. Assistant markdown shows as raw text,
the input has a stray native scrollbar, there is no way to stop a running reply,
and there is no indication during the first-token wait. This change polishes the
chat to a genuinely product-ready feel before Feature 1 is archived.

## What Changes

- **Smooth streaming reveal**: a client-side buffer drains incoming text at a
  steady character rate, decoupling display speed from network chunk size.
- **Thinking indicator**: a clean animated indicator while waiting for the first
  token (we keep `gemini-3.5-flash` for answer quality and mask its latency).
- **Stop generating**: a control to abort an in-progress reply (AbortController;
  server stream cancels on disconnect).
- **Markdown rendering** of assistant messages (bold, lists, code, links) via
  `react-markdown` + `remark-gfm`. **New dependencies** — added with `npm`.
- **Copy-to-clipboard** on assistant messages.
- **UI foundation**: adopt `lucide-react` for icons and set up **shadcn/ui**
  (themed to our warm Claude palette, not its default) so future features have a
  consistent, accessible component base — aligned with AGENTS.md ("shadcn/ui
  later"). Charts are intentionally **not** added yet (no data to chart;
  library chosen with the real use case in Feature 3).
- **Visual polish**: replace text-glyph controls (`↑ + ☰ ✕`) with lucide icons;
  refine spacing, typography, and the assistant avatar.
- **Light/dark toggle**: an explicit, persisted theme switch (today it only
  follows the OS setting).
- **Fix the input scrollbar**: hide textarea overflow until content genuinely
  exceeds the max height.
- No backend behavior change beyond honoring client disconnect on stop; no model
  change; no schema change.

## Capabilities

### New Capabilities
<!-- none — this refines the existing web-chat capability -->

### Modified Capabilities
- `web-chat`: add client-experience requirements — smooth incremental reveal,
  stop-generation, markdown rendering, and theming — on top of the streaming
  chat introduced by add-web-chat.

## Impact

- **Frontend:** `lib/api.ts` (AbortSignal on `streamChat`); new smoothing hook;
  `MessageBubble` (markdown + copy), `Composer` (icons, scrollbar, stop),
  `MessageList`/`ChatLayout` (thinking state, stop wiring), a theme toggle +
  `index.css` tokens; new inline icon components.
- **Dependencies (frontend):** `react-markdown`, `remark-gfm`, `lucide-react`,
  and shadcn/ui prerequisites (`class-variance-authority`, `clsx`,
  `tailwind-merge`, `tw-animate-css`) plus Radix primitives pulled per shadcn
  component. Approved by request. Charts deferred.
- **Backend:** none required; verify the SSE generator tolerates client
  disconnect (sse-starlette cancels the generator; no partial assistant row is
  persisted on stop).
- **Docs:** update `frontend/README.md` for the new deps and behavior.
