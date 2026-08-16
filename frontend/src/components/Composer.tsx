import { type KeyboardEvent, forwardRef, useImperativeHandle, useLayoutEffect, useRef } from "react";
import { ArrowUp, Brain, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Matches MAX_INPUT_CHARS on the backend, which rejects anything longer. */
const MAX_CHARS = 16000;
const WARN_AT = MAX_CHARS - 2000;

export type ComposerHandle = { focus: () => void };

/* The draft text and the "think harder" flag are owned by AppShell, not by this
   component. Composer unmounts when you switch to Tasks or Journal, so local state
   here meant a half-written message was silently lost on the way back. */

const Composer = forwardRef<
  ComposerHandle,
  {
    text: string;
    onTextChange: (v: string) => void;
    deep: boolean;
    onDeepChange: (v: boolean) => void;
    onSend: (text: string, deep: boolean) => void;
    onStop: () => void;
    busy: boolean;
  }
>(function Composer({ text, onTextChange, deep, onDeepChange, onSend, onStop, busy }, ref) {
  const inner = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => inner.current?.focus() }));

  useLayoutEffect(() => {
    const el = inner.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 200);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > 200 ? "auto" : "hidden";
  }, [text]);

  const tooLong = text.length > MAX_CHARS;

  function submit() {
    const value = text.trim();
    if (!value || busy || tooLong) return;
    onSend(value, deep);
    onTextChange("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="border-t border-border bg-background px-4 py-3">
      <div className="mx-auto flex w-full max-w-2xl items-end gap-2">
        <textarea
          ref={inner}
          rows={1}
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message aceroai…"
          aria-label="Message"
          className={cn(
            "max-h-52 flex-1 resize-none overflow-hidden rounded-2xl border bg-card px-4 py-3",
            "text-foreground outline-none focus:ring-2 focus:ring-ring/30",
            tooLong ? "border-destructive focus:border-destructive" : "border-border focus:border-ring",
          )}
        />
        <Button
          onClick={() => onDeepChange(!deep)}
          size="icon-lg"
          variant={deep ? "default" : "secondary"}
          aria-pressed={deep}
          aria-label="Think harder (deeper reasoning)"
          title="Think harder — deeper reasoning, a little slower"
          className="rounded-full"
        >
          <Brain />
        </Button>
        {busy ? (
          <Button
            onClick={onStop}
            size="icon-lg"
            variant="secondary"
            aria-label="Stop generating"
            className="rounded-full"
          >
            <Square className="fill-current" />
          </Button>
        ) : (
          <Button
            onClick={submit}
            disabled={!text.trim() || tooLong}
            size="icon-lg"
            aria-label="Send message"
            className="rounded-full"
          >
            <ArrowUp />
          </Button>
        )}
      </div>

      {/* Shown on every screen size — phones are where "Enter sends" is least obvious,
          so hiding this on mobile was exactly backwards. */}
      <p
        className={cn(
          "mx-auto mt-1.5 max-w-2xl text-center text-xs",
          tooLong ? "text-destructive" : "text-faint",
        )}
      >
        {tooLong
          ? `${text.length.toLocaleString()} / ${MAX_CHARS.toLocaleString()} characters — too long to send`
          : text.length > WARN_AT
            ? `${text.length.toLocaleString()} / ${MAX_CHARS.toLocaleString()} characters`
            : deep
              ? "Think harder is on — replies reason more deeply"
              : "Enter to send · Shift+Enter for a new line"}
      </p>
    </div>
  );
});

export default Composer;
