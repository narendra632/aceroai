import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import DatePicker from "@/components/ui/date-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetFooter } from "@/components/ui/sheet";
import type { Task } from "@/lib/api";

/* The detail panel for one task.
 *
 * This is where `notes` and `snoozed_until` finally become visible. Both have been in
 * the schema and writable by the assistant since tasks shipped, but had no interface at
 * all — so Acero could set a note the user could never read. A list row has nowhere
 * sensible to put them (cramming them in is what produced the truncated "Med" dropdown),
 * which is why editing lives in a panel rather than inline.
 */

const PRIORITIES = [
  { value: "1", label: "High" },
  { value: "2", label: "Medium" },
  { value: "3", label: "Low" },
];

const STATUSES = [
  { value: "todo", label: "To do" },
  { value: "in_progress", label: "In progress" },
  { value: "done", label: "Done" },
  { value: "dropped", label: "Dropped" },
];

/** ISO → the local "YYYY-MM-DDTHH:mm" the picker speaks. Never via toISOString(),
 *  which shifts to UTC and can show the wrong day. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

type Props = {
  task: Task | null;
  onClose: () => void;
  onSave: (id: string, patch: Partial<Task>) => Promise<void>;
  onDelete: (task: Task) => void;
};

export default function TaskSheet({ task, onClose, onSave, onDelete }: Props) {
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [priority, setPriority] = useState("2");
  const [status, setStatus] = useState<Task["status"]>("todo");
  const [due, setDue] = useState("");
  const [snooze, setSnooze] = useState("");
  const [saving, setSaving] = useState(false);

  // Re-seed whenever a different task is opened.
  useEffect(() => {
    if (!task) return;
    setTitle(task.title);
    setNotes(task.notes ?? "");
    setPriority(String(task.priority));
    setStatus(task.status);
    setDue(toLocalInput(task.due_at));
    setSnooze(toLocalInput(task.snoozed_until));
  }, [task]);

  if (!task) return null;

  const dirty =
    title !== task.title ||
    notes !== (task.notes ?? "") ||
    priority !== String(task.priority) ||
    status !== task.status ||
    due !== toLocalInput(task.due_at) ||
    snooze !== toLocalInput(task.snoozed_until);

  async function save() {
    if (!task || !title.trim()) return;
    setSaving(true);
    try {
      await onSave(task.id, {
        title: title.trim(),
        notes: notes.trim() || null,
        priority: Number(priority),
        status,
        due_at: due ? new Date(due).toISOString() : null,
        snoozed_until: snooze ? new Date(snooze).toISOString() : null,
      });
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent title="Task" description="Edit this task's details">
        <div className="space-y-4 pt-1">
          <div>
            <label htmlFor="task-title" className="text-sm font-medium">
              Title
            </label>
            <input
              id="task-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
            />
          </div>

          <div>
            <label htmlFor="task-notes" className="text-sm font-medium">
              Notes
            </label>
            <textarea
              id="task-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder="Anything worth remembering about this…"
              className="mt-1.5 w-full resize-y rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className="text-sm font-medium">Priority</span>
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger className="mt-1.5 w-full" aria-label="Priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITIES.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <span className="text-sm font-medium">Status</span>
              <Select value={status} onValueChange={(v) => setStatus(v as Task["status"])}>
                <SelectTrigger className="mt-1.5 w-full" aria-label="Status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div>
            <span className="text-sm font-medium">Due</span>
            <DatePicker value={due} onChange={setDue} placeholder="No due date" className="mt-1.5 w-full" />
          </div>

          <div>
            <span className="text-sm font-medium">Snoozed until</span>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Hides it from what's urgent until this time.
            </p>
            <DatePicker
              value={snooze}
              onChange={setSnooze}
              placeholder="Not snoozed"
              className="mt-1.5 w-full"
            />
          </div>

          <SheetFooter>
            <Button onClick={save} disabled={!dirty || !title.trim() || saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                onDelete(task);
                onClose();
              }}
              className="ml-auto text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="size-4" /> Delete
            </Button>
          </SheetFooter>
        </div>
      </SheetContent>
    </Sheet>
  );
}
