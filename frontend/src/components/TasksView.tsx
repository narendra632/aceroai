import { useCallback, useEffect, useState } from "react";
import { Check, Circle, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Task } from "@/lib/api";
import { cn } from "@/lib/utils";

const PRIORITY: Record<number, string> = { 1: "High", 2: "Medium", 3: "Low" };

function dueLabel(iso: string | null): string | null {
  if (!iso) return null;
  const due = new Date(iso);
  const days = Math.round((due.getTime() - Date.now()) / 86_400_000);
  const date = due.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (days < 0) return `Overdue · ${date}`;
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return date;
}

export default function TasksView() {
  const [tab, setTab] = useState<"active" | "done">("active");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState(2);
  const [due, setDue] = useState("");

  const load = useCallback(() => {
    api.listTasks(tab === "done" ? "done" : undefined).then(setTasks);
  }, [tab]);
  useEffect(() => {
    load();
  }, [load]);

  async function add() {
    const t = title.trim();
    if (!t) return;
    await api.createTask({
      title: t,
      priority,
      due_at: due ? new Date(due).toISOString() : null,
    });
    setTitle("");
    setDue("");
    setPriority(2);
    load();
  }

  async function complete(id: string) {
    await api.completeTask(id);
    load();
  }
  async function remove(id: string) {
    await api.deleteTask(id);
    load();
  }
  async function setPri(id: string, p: number) {
    await api.updateTask(id, { priority: p });
    load();
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-4 hidden text-xl font-semibold tracking-tight md:block">Tasks</h1>

        <div className="mb-4 inline-flex rounded-lg bg-secondary p-1 text-sm">
          {(["active", "done"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-md px-3 py-1.5 capitalize transition",
                tab === t ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "active" && (
          <div className="mb-5 flex flex-col gap-2 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()}
              placeholder="Add a task…"
              className="min-w-0 flex-1 bg-transparent px-1 py-1.5 outline-none"
            />
            <div className="flex items-center gap-2">
              <input
                type="datetime-local"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                aria-label="Due date"
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-muted-foreground"
              />
              <select
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                aria-label="Priority"
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              >
                <option value={1}>High</option>
                <option value={2}>Medium</option>
                <option value={3}>Low</option>
              </select>
              <Button onClick={add} disabled={!title.trim()}>
                Add
              </Button>
            </div>
          </div>
        )}

        {tasks.length === 0 ? (
          <p className="px-1 py-10 text-center text-sm text-muted-foreground">
            {tab === "active"
              ? "Nothing on your plate. Add a task, or ask Acero to."
              : "No completed tasks yet."}
          </p>
        ) : (
          <ul className="space-y-2">
            {tasks.map((t) => {
              const label = dueLabel(t.due_at);
              return (
                <li
                  key={t.id}
                  className="flex items-start gap-3 rounded-xl border border-border bg-card px-3 py-3"
                >
                  <button
                    onClick={() => complete(t.id)}
                    disabled={t.status === "done"}
                    aria-label="Complete task"
                    className="mt-0.5 text-muted-foreground hover:text-primary disabled:opacity-60"
                  >
                    {t.status === "done" ? (
                      <Check className="size-5 text-primary" />
                    ) : (
                      <Circle className="size-5" />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <p
                      className={cn(
                        "break-words",
                        t.status === "done" && "text-muted-foreground line-through",
                      )}
                    >
                      {t.title}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      {label && (
                        <span className={cn(label.startsWith("Overdue") && "text-destructive")}>
                          {label}
                        </span>
                      )}
                      <span>{PRIORITY[t.priority] ?? "Medium"}</span>
                    </div>
                  </div>
                  {tab === "active" && (
                    <div className="flex items-center gap-1">
                      <select
                        value={t.priority}
                        onChange={(e) => setPri(t.id, Number(e.target.value))}
                        aria-label="Change priority"
                        className="rounded-md border border-border bg-background px-1.5 py-1 text-xs text-muted-foreground"
                      >
                        <option value={1}>High</option>
                        <option value={2}>Med</option>
                        <option value={3}>Low</option>
                      </select>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => remove(t.id)}
                        aria-label="Delete task"
                        className="text-muted-foreground"
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
