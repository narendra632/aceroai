import { type KeyboardEvent, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Brain, Square } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function Composer({
  onSend,
  onStop,
  busy,
}: {
  onSend: (text: string, deep: boolean) => void;
  onStop: () => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const [deep, setDeep] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  // auto-grow up to a cap; keep overflow hidden until the cap is reached so no
  // scrollbar shows for short input
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 200);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > 200 ? "auto" : "hidden";
  }, [text]);

  function submit() {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value, deep);
    setText("");
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
          ref={ref}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message aceroai…"
          className="max-h-52 flex-1 resize-none overflow-hidden rounded-2xl border border-border bg-card px-4 py-3 text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
        />
        <Button
          onClick={() => setDeep((d) => !d)}
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
            disabled={!text.trim()}
            size="icon-lg"
            aria-label="Send message"
            className="rounded-full"
          >
            <ArrowUp />
          </Button>
        )}
      </div>
      <p className="mx-auto mt-1.5 hidden max-w-2xl text-center text-xs text-faint sm:block">
        {deep ? "Think harder is on — replies reason more deeply" : "Enter to send · Shift+Enter for a new line"}
      </p>
    </div>
  );
}
