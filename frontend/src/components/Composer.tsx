import { type KeyboardEvent, useLayoutEffect, useRef, useState } from "react";

export default function Composer({
  onSend,
  busy,
}: {
  onSend: (text: string) => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // auto-grow the textarea up to a cap
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  function submit() {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="border-t border-line bg-paper px-4 py-3">
      <div className="mx-auto flex w-full max-w-2xl items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message aceroai…"
          className="max-h-52 flex-1 resize-none rounded-2xl border border-line bg-surface px-4 py-3 text-ink outline-none focus:border-clay"
        />
        <button
          onClick={submit}
          disabled={busy || !text.trim()}
          aria-label="Send"
          className="grid h-11 w-11 flex-none place-items-center rounded-full bg-clay text-white transition hover:bg-clay-strong disabled:opacity-40"
        >
          ↑
        </button>
      </div>
      <p className="mx-auto mt-1.5 hidden max-w-2xl text-center text-xs text-faint sm:block">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
