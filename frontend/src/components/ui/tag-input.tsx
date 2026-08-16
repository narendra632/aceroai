import { type KeyboardEvent, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/* Tags as removable chips instead of a raw comma-separated string.
   The old field made you type the separator, gave no sign a tag was registered, and
   offered no way to see which tags already exist — so the same idea ended up spelled
   three ways. Suggestions come from tags already in use, which is what keeps them
   consistent over time. */

type Props = {
  value: string[];
  onChange: (tags: string[]) => void;
  /** Tags already used elsewhere, offered as suggestions. */
  suggestions?: string[];
  placeholder?: string;
  className?: string;
};

export default function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder = "Add a tag…",
  className,
}: Props) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    const term = draft.trim().toLowerCase();
    if (!term) return [];
    return suggestions
      .filter((s) => s.toLowerCase().includes(term) && !value.includes(s))
      .slice(0, 5);
  }, [draft, suggestions, value]);

  function add(tag: string) {
    const clean = tag.trim().replace(/^#/, "").toLowerCase();
    if (!clean || value.includes(clean)) {
      setDraft("");
      return;
    }
    onChange([...value, clean]);
    setDraft("");
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // Enter and comma both commit, so muscle memory from the old comma field still works
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <div className={cn("relative", className)}>
      <div
        onClick={() => inputRef.current?.focus()}
        className={cn(
          "flex min-h-11 flex-wrap items-center gap-1.5 rounded-lg border border-border",
          "bg-background px-2 py-1.5 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30",
        )}
      >
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-full bg-secondary py-1 pr-1 pl-2.5 text-xs text-secondary-foreground"
          >
            #{tag}
            <button
              type="button"
              onClick={() => onChange(value.filter((t) => t !== tag))}
              aria-label={`Remove tag ${tag}`}
              className="grid size-5 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => draft && add(draft)}
          placeholder={value.length ? "" : placeholder}
          aria-label="Add a tag"
          className="min-w-24 flex-1 bg-transparent px-1 text-sm outline-none"
        />
      </div>

      {matches.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
          {matches.map((s) => (
            <li key={s}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus so onBlur doesn't double-add
                  add(s);
                }}
                className="w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
              >
                #{s}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
