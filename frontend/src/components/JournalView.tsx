import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { JournalEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

const MOODS = ["😔", "😕", "😐", "🙂", "😄"]; // index + 1 = mood value

function dateLabel(entryDate: string): string {
  // entry_date is a plain YYYY-MM-DD; pin to local midnight so it isn't shifted.
  return new Date(`${entryDate}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export default function JournalView() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [content, setContent] = useState("");
  const [mood, setMood] = useState<number | null>(null);
  const [tags, setTags] = useState("");

  function load() {
    api.listJournal().then(setEntries);
  }
  useEffect(load, []);

  async function add() {
    const c = content.trim();
    if (!c) return;
    const tagList = tags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    await api.addJournalEntry({ content: c, mood, tags: tagList });
    setContent("");
    setMood(null);
    setTags("");
    load();
  }

  async function remove(id: string) {
    await api.deleteJournalEntry(id);
    load();
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-4 hidden text-xl font-semibold tracking-tight md:block">Journal</h1>

        <div className="mb-6 rounded-xl border border-border bg-card p-3">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={3}
            placeholder="What happened today? How are you feeling?"
            className="w-full resize-none bg-transparent px-1 py-1 outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1">
              {MOODS.map((m, i) => (
                <button
                  key={i}
                  onClick={() => setMood(mood === i + 1 ? null : i + 1)}
                  aria-label={`Mood ${i + 1} of 5`}
                  aria-pressed={mood === i + 1}
                  className={cn(
                    "grid size-9 place-items-center rounded-lg text-lg transition",
                    mood === i + 1 ? "bg-accent" : "opacity-70 hover:bg-accent/60",
                  )}
                >
                  {m}
                </button>
              ))}
            </div>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="tags, comma-separated"
              className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            />
            <Button onClick={add} disabled={!content.trim()}>
              Save
            </Button>
          </div>
        </div>

        {entries.length === 0 ? (
          <p className="px-1 py-10 text-center text-sm text-muted-foreground">
            No entries yet. Write your first, or ask Acero to log one.
          </p>
        ) : (
          <ul className="space-y-3">
            {entries.map((e) => (
              <li key={e.id} className="rounded-xl border border-border bg-card px-4 py-3">
                <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    {dateLabel(e.entry_date)}
                    {e.mood ? ` · ${MOODS[e.mood - 1]}` : ""}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={() => remove(e.id)}
                    aria-label="Delete entry"
                    className="text-muted-foreground"
                  >
                    <Trash2 />
                  </Button>
                </div>
                <p className="text-sm break-words whitespace-pre-wrap">{e.content}</p>
                {e.tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {e.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
