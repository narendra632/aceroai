import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Check, Pencil, Search, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/states";
import TagInput from "@/components/ui/tag-input";
import { useOptimisticList } from "@/hooks/useOptimisticList";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { JournalEntry } from "@/lib/api";
import { cn } from "@/lib/utils";

const MOODS = ["😔", "😕", "😐", "🙂", "😄"]; // index + 1 = mood value
const PAGE = 25;

function dateLabel(entryDate: string): string {
  // entry_date is a plain YYYY-MM-DD; pin to local midnight so it isn't shifted.
  return new Date(`${entryDate}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function MoodPicker({
  value,
  onChange,
  size = "default",
}: {
  value: number | null;
  onChange: (m: number | null) => void;
  size?: "default" | "sm";
}) {
  return (
    <div className="flex items-center gap-1">
      {MOODS.map((m, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onChange(value === i + 1 ? null : i + 1)}
          aria-label={`Mood ${i + 1} of 5`}
          aria-pressed={value === i + 1}
          className={cn(
            "grid place-items-center rounded-lg transition",
            size === "sm" ? "size-8 text-base" : "size-11 text-lg",
            value === i + 1 ? "bg-accent" : "opacity-70 hover:bg-accent/60",
          )}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

export default function JournalView() {
  const [content, setContent] = useState("");
  const [mood, setMood] = useState<number | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState(""); // debounced
  const [limit, setLimit] = useState(PAGE);

  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState({ content: "", mood: null as number | null, tags: [] as string[] });

  const toast = useToast();

  // Debounce so a search doesn't fire a request per keystroke.
  useEffect(() => {
    const id = setTimeout(() => {
      setQuery(search.trim());
      setLimit(PAGE);
    }, 250);
    return () => clearTimeout(id);
  }, [search]);

  const load = useCallback(() => api.listJournal({ q: query || undefined, limit }), [query, limit]);
  const list = useOptimisticList<JournalEntry>(load, [query, limit]);

  // Suggestions come from what is already on screen — enough to keep tags consistent
  // without another endpoint.
  const knownTags = useMemo(
    () => [...new Set(list.items.flatMap((e) => e.tags))].sort(),
    [list.items],
  );

  async function add() {
    const c = content.trim();
    if (!c || saving) return;
    setSaving(true);
    try {
      const created = await api.addJournalEntry({ content: c, mood, tags });
      list.setItems((items) => [created, ...items]);
      setContent("");
      setMood(null);
      setTags([]);
    } catch {
      toast.error("Could not save that entry");
    } finally {
      setSaving(false);
    }
  }

  function remove(entry: JournalEntry) {
    void (async () => {
      const ok = await list.mutate({
        optimistic: (items) => items.filter((e) => e.id !== entry.id),
        request: () => api.deleteJournalEntry(entry.id),
        errorMessage: "Could not delete the entry",
      });
      if (ok) {
        toast.undo("Entry deleted", async () => {
          await list.mutate({
            optimistic: (items) =>
              [entry, ...items].sort(
                (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
              ),
            request: () => api.restoreJournalEntry(entry.id),
            errorMessage: "Could not restore the entry",
          });
        });
      }
    })();
  }

  function startEdit(entry: JournalEntry) {
    setEditing(entry.id);
    setDraft({ content: entry.content, mood: entry.mood, tags: entry.tags });
  }

  async function saveEdit(entry: JournalEntry) {
    const c = draft.content.trim();
    if (!c) return;
    const ok = await list.mutate({
      optimistic: (items) =>
        items.map((e) =>
          e.id === entry.id ? { ...e, content: c, mood: draft.mood, tags: draft.tags } : e,
        ),
      request: () =>
        api.updateJournalEntry(entry.id, { content: c, mood: draft.mood, tags: draft.tags }),
      errorMessage: "Could not update the entry",
    });
    if (ok) toast.success("Entry updated");
    setEditing(null);
  }

  const canLoadMore = list.items.length >= limit;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-4 hidden text-xl font-semibold tracking-tight md:block">Journal</h1>

        {/* composer */}
        <div className="mb-5 rounded-xl border border-border bg-card p-3">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={3}
            placeholder="What happened today? How are you feeling?"
            className="w-full resize-none bg-transparent px-1 py-1 outline-none"
          />
          <div className="mt-2 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <MoodPicker value={mood} onChange={setMood} />
              <Button onClick={add} disabled={!content.trim() || saving} className="ml-auto">
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
            <TagInput value={tags} onChange={setTags} suggestions={knownTags} />
          </div>
        </div>

        {/* search */}
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-border bg-background px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search your journal…"
            aria-label="Search the journal"
            className="min-w-0 flex-1 bg-transparent py-2.5 text-sm outline-none"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              aria-label="Clear search"
              className="touch-target grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-accent"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        {list.status === "loading" ? (
          <ListSkeleton rows={3} />
        ) : list.status === "error" ? (
          <ErrorState
            title="Couldn't load your journal"
            detail="The server didn't respond. Nothing you've written is lost."
            onRetry={list.reload}
          />
        ) : list.items.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title={query ? "No entries match that" : "No entries yet"}
            hint={
              query
                ? "Try a different word — search matches the text of an entry."
                : "Write your first above, or ask Acero to log one for you."
            }
          />
        ) : (
          <>
            <ul className="space-y-3">
              {list.items.map((e) => {
                const isEditing = editing === e.id;
                return (
                  <li
                    key={e.id}
                    className="group rounded-xl border border-border bg-card px-4 py-3"
                  >
                    <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>
                        {dateLabel(e.entry_date)}
                        {!isEditing && e.mood ? ` · ${MOODS[e.mood - 1]}` : ""}
                      </span>
                      {!isEditing && (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => startEdit(e)}
                            aria-label="Edit entry"
                            className="text-muted-foreground opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-60"
                          >
                            <Pencil />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => remove(e)}
                            aria-label="Delete entry"
                            className="text-muted-foreground opacity-0 transition hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-60"
                          >
                            <Trash2 />
                          </Button>
                        </div>
                      )}
                    </div>

                    {isEditing ? (
                      <div className="space-y-2">
                        <textarea
                          value={draft.content}
                          onChange={(ev) => setDraft({ ...draft, content: ev.target.value })}
                          rows={4}
                          className="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
                        />
                        <MoodPicker
                          size="sm"
                          value={draft.mood}
                          onChange={(m) => setDraft({ ...draft, mood: m })}
                        />
                        <TagInput
                          value={draft.tags}
                          onChange={(t) => setDraft({ ...draft, tags: t })}
                          suggestions={knownTags}
                        />
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => saveEdit(e)} disabled={!draft.content.trim()}>
                            <Check className="size-4" /> Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="text-sm whitespace-pre-wrap wrap-break-word">{e.content}</p>
                        {e.tags.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {e.tags.map((t) => (
                              <button
                                key={t}
                                onClick={() => setSearch(t)}
                                className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
                              >
                                #{t}
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </li>
                );
              })}
            </ul>

            {canLoadMore && (
              <div className="mt-4 flex justify-center">
                <Button variant="outline" onClick={() => setLimit((n) => n + PAGE)}>
                  Load older entries
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
