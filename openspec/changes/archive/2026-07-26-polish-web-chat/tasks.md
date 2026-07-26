## 1. Streaming feel

- [ ] 1.1 `lib/api.ts`: `streamChat(message, sessionId, signal?)` accepts an `AbortSignal` and passes it to `fetch`
- [ ] 1.2 Add a reveal hook/util: buffer incoming deltas, drain to displayed text at a steady adaptive rate via rAF, flush fully on stream end
- [ ] 1.3 `ChatLayout`: feed deltas into the reveal buffer instead of appending raw; track a per-turn "thinking" (no text yet) vs "streaming" vs "done" state

## 2. Thinking indicator + stop

- [ ] 2.1 `MessageBubble` (or a `ThinkingDots` component): clean animated indicator shown for a pending assistant turn with no text yet
- [ ] 2.2 `ChatLayout`/`Composer`: while streaming, show a Stop control; wire it to an `AbortController` that cancels the fetch and re-enables the composer, keeping partial text
- [ ] 2.3 Verify backend tolerates client disconnect (no partial assistant row persisted); add/confirm a note in handler if needed

## 3. Markdown + copy

- [ ] 3.1 `npm install react-markdown remark-gfm` (after approval); note in `frontend/README.md`
- [ ] 3.2 `MessageBubble`: render assistant content with `react-markdown` + `remark-gfm` (no raw HTML), style headings/lists/links/inline+fenced code; user messages stay plain
- [ ] 3.3 Copy-to-clipboard control on assistant messages with a brief "copied" confirmation

## 4. Visual polish + theming

- [ ] 4.0 Set up shadcn/ui: `@/` path alias (tsconfig + vite), `cn()` util, `components.json`; map shadcn tokens to our warm palette; add Button/Tooltip/DropdownMenu
- [ ] 4.1 Adopt `lucide-react` icons (send, plus, menu, close, copy, check, stop, sun/moon); replace the `↑ + ☰ ✕` glyphs
- [ ] 4.2 `Composer`: fix the textarea scrollbar (overflow hidden until content exceeds max height); refine paddings/rounding
- [ ] 4.3 Refine spacing, typography, and the assistant avatar across bubbles/sidebar for a cleaner, calmer layout
- [ ] 4.4 `index.css` + a `ThemeToggle`: `data-theme` on `<html>` + localStorage persistence, light/dark overrides, no theme flash on load

## 5. Verify + docs

- [ ] 5.1 `npm run build` + `npm run lint` green; backend `uv run pytest` still green
- [ ] 5.2 Manual: send a markdown-heavy prompt — smooth reveal, thinking indicator, stop mid-stream, copy, theme toggle, mobile drawer, no input scrollbar
- [ ] 5.3 Update `frontend/README.md` (deps, streaming/thinking/stop/theme behavior)
