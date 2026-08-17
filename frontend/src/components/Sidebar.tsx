import { type KeyboardEvent, useMemo, useState } from "react";
import {
  Activity,
  BookOpen,
  Brain,
  Check,
  ListTodo,
  LogOut,
  MessageSquare,
  Moon,
  Pencil,
  Plus,
  Search,
  Settings as SettingsIcon,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import type { ComponentType } from "react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";
import type { Session } from "@/lib/api";
import { cn } from "@/lib/utils";

export type View = "chat" | "tasks" | "journal" | "knowledge" | "insights" | "settings";

const NAV: { view: View; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { view: "chat", label: "Chat", icon: MessageSquare },
  { view: "tasks", label: "Tasks", icon: ListTodo },
  { view: "journal", label: "Journal", icon: BookOpen },
  { view: "knowledge", label: "Knowledge", icon: Brain },
  { view: "insights", label: "Insights", icon: Activity },
  { view: "settings", label: "Settings", icon: SettingsIcon },
];

const DAY_MS = 86_400_000;

/** Group conversations the way a person thinks about them, not as one flat list. */
function bucketOf(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = today.getTime();
  if (d.getTime() >= start) return "Today";
  if (d.getTime() >= start - DAY_MS) return "Yesterday";
  if (d.getTime() >= start - 7 * DAY_MS) return "Previous 7 days";
  if (d.getTime() >= start - 30 * DAY_MS) return "Previous 30 days";
  return "Older";
}

const BUCKET_ORDER = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];

type Props = {
  email: string;
  view: View;
  sessions: Session[];
  currentId: string | null;
  open: boolean;
  onNavigate: (view: View) => void;
  onSelect: (id: string) => void;
  onDelete: (session: Session) => void;
  onRename: (id: string, title: string) => void;
  onNewChat: () => void;
  onClose: () => void;
  onLogout: () => void;
};

export default function Sidebar({
  email,
  view,
  sessions,
  currentId,
  open,
  onNavigate,
  onSelect,
  onDelete,
  onRename,
  onNewChat,
  onClose,
  onLogout,
}: Props) {
  const { theme, toggle } = useTheme();
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const groups = useMemo(() => {
    const term = filter.trim().toLowerCase();
    const matched = term
      ? sessions.filter((s) => (s.title ?? "").toLowerCase().includes(term))
      : sessions;
    const by = new Map<string, Session[]>();
    for (const s of matched) {
      const b = bucketOf(s.last_active_at);
      by.set(b, [...(by.get(b) ?? []), s]);
    }
    return BUCKET_ORDER.filter((b) => by.has(b)).map((b) => [b, by.get(b)!] as const);
  }, [sessions, filter]);

  function commitRename(id: string) {
    const title = draft.trim();
    if (title) onRename(id, title);
    setEditing(null);
  }

  function onRenameKey(e: KeyboardEvent<HTMLInputElement>, id: string) {
    if (e.key === "Enter") commitRename(id);
    if (e.key === "Escape") setEditing(null);
  }

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} aria-hidden />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-border bg-secondary transition-transform duration-200 md:static md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <span className="text-lg font-semibold tracking-tight">aceroai</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close menu"
              className="md:hidden"
            >
              <X />
            </Button>
          </div>
        </div>

        <nav className="flex flex-col gap-1 px-3">
          {NAV.map(({ view: v, label, icon: Icon }) => (
            <button
              key={v}
              onClick={() => onNavigate(v)}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition",
                v === view
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60",
              )}
            >
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </nav>

        {view === "chat" && (
          <>
            <div className="mt-4 space-y-2 px-3">
              <Button variant="outline" onClick={onNewChat} className="w-full justify-start gap-2">
                <Plus /> New chat
              </Button>
              {sessions.length > 5 && (
                <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2.5">
                  <Search className="size-3.5 shrink-0 text-muted-foreground" />
                  <input
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Search chats"
                    aria-label="Search conversations"
                    className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none"
                  />
                </div>
              )}
            </div>

            <div className="no-scrollbar mt-2 flex-1 overflow-y-auto px-3 pb-3">
              {sessions.length === 0 ? (
                <p className="px-2 py-4 text-sm text-faint">No conversations yet.</p>
              ) : groups.length === 0 ? (
                <p className="px-2 py-4 text-sm text-faint">No chats match that.</p>
              ) : (
                groups.map(([bucket, items]) => (
                  <div key={bucket} className="mb-3">
                    <h3 className="px-2 py-1 text-[11px] font-medium tracking-wide text-faint uppercase">
                      {bucket}
                    </h3>
                    <ul className="space-y-1">
                      {items.map((s) => (
                        <li key={s.id} className="group relative">
                          {editing === s.id ? (
                            <div className="flex items-center gap-1 rounded-lg bg-background px-2 py-1">
                              <input
                                autoFocus
                                value={draft}
                                onChange={(e) => setDraft(e.target.value)}
                                onKeyDown={(e) => onRenameKey(e, s.id)}
                                onBlur={() => commitRename(s.id)}
                                aria-label="Conversation name"
                                className="min-w-0 flex-1 bg-transparent py-1 text-sm outline-none"
                              />
                              <button
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => commitRename(s.id)}
                                aria-label="Save name"
                                className="grid size-7 shrink-0 place-items-center rounded-md text-primary hover:bg-accent"
                              >
                                <Check className="size-4" />
                              </button>
                            </div>
                          ) : (
                            <>
                              <button
                                onClick={() => onSelect(s.id)}
                                onDoubleClick={() => {
                                  setEditing(s.id);
                                  setDraft(s.title ?? "");
                                }}
                                title={s.title ?? "Untitled"}
                                className={cn(
                                  "w-full truncate rounded-lg py-2.5 pr-16 pl-3 text-left text-sm transition",
                                  s.id === currentId
                                    ? "bg-accent text-accent-foreground"
                                    : "text-muted-foreground hover:bg-accent/60",
                                )}
                              >
                                {s.title ?? "Untitled"}
                              </button>
                              <div
                                className={cn(
                                  "absolute top-1/2 right-1 flex -translate-y-1/2 items-center",
                                  "opacity-0 transition group-hover:opacity-100 focus-within:opacity-100",
                                  "max-md:opacity-60",
                                )}
                              >
                                <button
                                  onClick={() => {
                                    setEditing(s.id);
                                    setDraft(s.title ?? "");
                                  }}
                                  aria-label={`Rename "${s.title ?? "Untitled"}"`}
                                  title="Rename"
                                  className="touch-target grid size-7 place-items-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground"
                                >
                                  <Pencil className="size-3.5" />
                                </button>
                                <button
                                  onClick={() => onDelete(s)}
                                  aria-label={`Delete "${s.title ?? "Untitled"}"`}
                                  title="Delete"
                                  className="touch-target grid size-7 place-items-center rounded-md text-muted-foreground transition hover:bg-destructive/15 hover:text-destructive"
                                >
                                  <Trash2 className="size-3.5" />
                                </button>
                              </div>
                            </>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )}
            </div>
          </>
        )}

        <div className="mt-auto flex items-center justify-between border-t border-border px-4 py-3">
          <span className="truncate text-xs text-faint" title={email}>
            {email}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onLogout}
            aria-label="Sign out"
            className="text-muted-foreground"
          >
            <LogOut />
          </Button>
        </div>
      </aside>
    </>
  );
}
