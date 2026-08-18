import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Circle,
  CircleDashed,
  ListTodo,
  MoonStar,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import DatePicker from "@/components/ui/date-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/ui/states";
import { useOptimisticList } from "@/hooks/useOptimisticList";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { Task } from "@/lib/api";
import { cn } from "@/lib/utils";
import TaskSheet from "./TaskSheet";

const PRIORITY: Record<number, string> = { 1: "High", 2: "Medium", 3: "Low" };
const DAY_MS = 86_400_000;

type SortKey = "urgency" | "due" | "priority" | "created";

const SORTS: { value: SortKey; label: string }[] = [
  { value: "urgency", label: "Most urgent" },
  { value: "due", label: "Due date" },
  { value: "priority", label: "Priority" },
  { value: "created", label: "Recently added" },
];

/** Whole calendar days from today to `due`, ignoring clock time.
 *
 *  Rounding the raw millisecond gap is what made a task due 19 Aug at 11:00 read as
 *  "Today" when it was 23:26 on the 18th: the gap was 11.5 hours, which rounds to 0 days.
 *  "Tomorrow" is a statement about the calendar, not about elapsed hours. */
function calendarDaysUntil(due: Date): number {
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((midnight(due) - midnight(new Date())) / DAY_MS);
}

/** What to say about a task's dates.
 *
 *  A FINISHED task is never "overdue". The word means "you still owe this and the deadline
 *  has passed" — once it is done the deadline is history, and shouting a red warning at
 *  something already handled trains you to ignore the warning where it matters. Done tasks
 *  report when they were completed instead, which is the only date still worth knowing. */
function dueLabel(task: Task): string | null {
  const settled = task.status === "done" || task.status === "dropped";
  if (settled) {
    if (!task.completed_at) return null;
    const on = new Date(task.completed_at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
    return `Completed · ${on}`;
  }
  if (!task.due_at) return null;
  const due = new Date(task.due_at);
  const date = due.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (due.getTime() < Date.now()) return `Overdue · ${date}`;
  const days = calendarDaysUntil(due);
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return date;
}

/** Which section a task belongs to. Mirrors the backend's urgency ordering; derived at
 *  read time and never stored (golden rule 2). */
function bucketOf(task: Task): string {
  // A finished task cannot be overdue, so it never lands in that bucket.
  if (task.status === "done" || task.status === "dropped") return "No date";
  if (!task.due_at) return "No date";
  const due = new Date(task.due_at).getTime();
  const now = Date.now();
  if (due < now) return "Overdue";
  const endOfToday = new Date();
  endOfToday.setHours(23, 59, 59, 999);
  if (due <= endOfToday.getTime()) return "Today";
  if (due <= endOfToday.getTime() + 6 * DAY_MS) return "This week";
  return "Later";
}

const BUCKET_ORDER = ["Overdue", "Today", "This week", "Later", "No date"];

function sortTasks(tasks: Task[], key: SortKey): Task[] {
  const copy = [...tasks];
  const dueTime = (t: Task) => (t.due_at ? new Date(t.due_at).getTime() : Infinity);
  switch (key) {
    case "due":
      return copy.sort((a, b) => dueTime(a) - dueTime(b));
    case "priority":
      return copy.sort((a, b) => a.priority - b.priority || dueTime(a) - dueTime(b));
    case "created":
      return copy.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    default:
      // the server already returns urgency order; keep it
      return copy;
  }
}

export default function TasksView() {
  const [tab, setTab] = useState<"active" | "done">("active");
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("2");
  const [due, setDue] = useState("");
  const [adding, setAdding] = useState(false);
  const [sort, setSort] = useState<SortKey>("urgency");
  const [open, setOpen] = useState<Task | null>(null);

  const toast = useToast();
  const list = useOptimisticList<Task>(
    () => api.listTasks(tab === "done" ? "done" : undefined),
    [tab],
  );

  async function add() {
    const t = title.trim();
    if (!t || adding) return;
    setAdding(true);
    try {
      const created = await api.createTask({
        title: t,
        priority: Number(priority),
        due_at: due ? new Date(due).toISOString() : null,
      });
      list.setItems((items) => [created, ...items]);
      setTitle("");
      setDue("");
      setPriority("2");
    } catch {
      toast.error("Could not add that task");
    } finally {
      setAdding(false);
    }
  }

  function remove(task: Task) {
    void (async () => {
      const ok = await list.mutate({
        optimistic: (items) => items.filter((t) => t.id !== task.id),
        request: () => api.deleteTask(task.id),
        errorMessage: "Could not delete the task",
      });
      // Undo rather than a confirm dialog: no friction on the intentional case, and it
      // still protects the mistake you only notice a second later.
      if (ok) {
        toast.undo("Task deleted", async () => {
          await list.mutate({
            optimistic: (items) => [task, ...items],
            request: () => api.restoreTask(task.id),
            errorMessage: "Could not restore the task",
          });
        });
      }
    })();
  }

  function complete(task: Task) {
    void list.mutate({
      optimistic: (items) => items.filter((t) => t.id !== task.id),
      request: () => api.completeTask(task.id),
      errorMessage: "Could not complete the task",
    });
  }

  function setPriorityOf(task: Task, next: string) {
    void list.mutate({
      optimistic: (items) =>
        items.map((t) => (t.id === task.id ? { ...t, priority: Number(next) } : t)),
      request: () => api.updateTask(task.id, { priority: Number(next) }),
      errorMessage: "Could not change the priority",
    });
  }

  /** Does this task still belong on the tab currently being viewed? */
  function belongsHere(task: Task): boolean {
    return tab === "done" ? task.status === "done" : task.status !== "done" && task.status !== "dropped";
  }

  async function save(id: string, patch: Partial<Task>) {
    const updated = await api.updateTask(id, patch);
    // A status change can move a task off this tab in EITHER direction — marking one
    // done removes it from Active, and re-opening a finished one removes it from Done.
    // Handling only the first direction left a re-opened task sitting on Done until
    // you switched tabs and back.
    if (belongsHere(updated)) {
      list.replace((t) => t.id === id, updated);
    } else {
      list.setItems((items) => items.filter((t) => t.id !== id));
    }
    toast.success("Task updated");
  }

  const sorted = useMemo(() => sortTasks(list.items, sort), [list.items, sort]);
  // Group only under the default ordering — an explicit sort should not be re-grouped.
  const groups = useMemo(() => {
    if (sort !== "urgency" || tab === "done") return [["", sorted] as const];
    const by = new Map<string, Task[]>();
    for (const t of sorted) {
      const b = bucketOf(t);
      by.set(b, [...(by.get(b) ?? []), t]);
    }
    return BUCKET_ORDER.filter((b) => by.has(b)).map((b) => [b, by.get(b)!] as const);
  }, [sorted, sort, tab]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-4 hidden text-xl font-semibold tracking-tight md:block">Tasks</h1>

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-lg bg-secondary p-1 text-sm">
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
          {tab === "active" && list.items.length > 1 && (
            <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
              <SelectTrigger size="sm" aria-label="Sort tasks" className="ml-auto">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORTS.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
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
              <DatePicker value={due} onChange={setDue} placeholder="Due" />
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger aria-label="Priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">High</SelectItem>
                  <SelectItem value="2">Medium</SelectItem>
                  <SelectItem value="3">Low</SelectItem>
                </SelectContent>
              </Select>
              <Button onClick={add} disabled={!title.trim() || adding}>
                Add
              </Button>
            </div>
          </div>
        )}

        {list.status === "loading" ? (
          <ListSkeleton rows={3} />
        ) : list.status === "error" ? (
          <ErrorState
            title="Couldn't load your tasks"
            detail="The server didn't respond. Your tasks are safe."
            onRetry={list.reload}
          />
        ) : list.items.length === 0 ? (
          <EmptyState
            icon={ListTodo}
            title={tab === "active" ? "Nothing on your plate" : "No completed tasks yet"}
            hint={
              tab === "active"
                ? "Add one above, or just ask Acero to remember it for you."
                : undefined
            }
          />
        ) : (
          <div className="space-y-5">
            {groups.map(([bucket, tasks]) => (
              <section key={bucket || "all"}>
                {bucket && (
                  <h2
                    className={cn(
                      "mb-2 px-1 text-xs font-medium tracking-wide uppercase",
                      bucket === "Overdue" ? "text-destructive" : "text-muted-foreground",
                    )}
                  >
                    {bucket}
                  </h2>
                )}
                <ul className="space-y-2">
                  {tasks.map((t) => {
                    const label = dueLabel(t);
                    const overdue = label?.startsWith("Overdue");
                    return (
                      <li
                        key={t.id}
                        className="group flex items-start gap-3 rounded-xl border border-border bg-card px-3 py-3 transition-colors hover:border-input"
                      >
                        <button
                          onClick={() => complete(t)}
                          disabled={t.status === "done"}
                          aria-label={`Complete "${t.title}"`}
                          className="touch-target mt-0.5 text-muted-foreground transition-colors hover:text-primary disabled:opacity-60"
                        >
                          {t.status === "done" ? (
                            <Check className="size-5 text-primary" />
                          ) : t.status === "in_progress" ? (
                            // A half-filled ring: started but not finished. The checkbox
                            // was the only status signal in the list, and it has just two
                            // states, so "in progress" was invisible unless you opened it.
                            <CircleDashed className="size-5 text-primary" />
                          ) : (
                            <Circle className="size-5" />
                          )}
                        </button>

                        <button
                          onClick={() => setOpen(t)}
                          className="min-w-0 flex-1 text-left"
                          aria-label={`Open "${t.title}"`}
                        >
                          <p
                            className={cn(
                              "wrap-break-word",
                              t.status === "done" && "text-muted-foreground line-through",
                            )}
                          >
                            {t.title}
                          </p>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            {label && (
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1",
                                  overdue && "font-medium text-destructive",
                                )}
                              >
                                {/* an icon as well as colour — colour alone is not a signal
                                    for colour-blind users */}
                                {overdue && <AlertTriangle className="size-3.5" />}
                                {label}
                              </span>
                            )}
                            {t.status === "in_progress" && (
                              <span className="rounded-md bg-secondary px-1.5 py-0.5 font-medium text-secondary-foreground">
                                In progress
                              </span>
                            )}
                            <span>{PRIORITY[t.priority] ?? "Medium"}</span>
                            {t.snoozed_until && new Date(t.snoozed_until) > new Date() && (
                              <span className="inline-flex items-center gap-1">
                                <MoonStar className="size-3.5" /> Snoozed
                              </span>
                            )}
                            {t.notes && <span className="text-faint">Has notes</span>}
                          </div>
                        </button>

                        {tab === "active" && (
                          <div className="flex items-center gap-1">
                            <Select
                              value={String(t.priority)}
                              onValueChange={(v) => setPriorityOf(t, v)}
                            >
                              <SelectTrigger size="sm" aria-label={`Priority for "${t.title}"`}>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="1">High</SelectItem>
                                <SelectItem value="2">Medium</SelectItem>
                                <SelectItem value="3">Low</SelectItem>
                              </SelectContent>
                            </Select>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              onClick={() => remove(t)}
                              aria-label={`Delete "${t.title}"`}
                              className={cn(
                                "text-muted-foreground transition hover:text-destructive",
                                // reveal on hover, but stay reachable on touch —
                                // matching Sidebar, which already solved this
                                "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
                                "max-md:opacity-60",
                              )}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>

      <TaskSheet task={open} onClose={() => setOpen(null)} onSave={save} onDelete={remove} />
    </div>
  );
}
