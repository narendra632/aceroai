import { useEffect, useState } from "react";
import { BadgeCheck, BadgeX, History, MessageSquareText, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetFooter } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/states";
import * as api from "@/lib/api";
import type { Fact, FactDetail } from "@/lib/api";

/* One fact, in full.
 *
 * This panel is the answer to "where did you get that?". Every fact here was *inferred*
 * by a language model from something you said, and an inference can be wrong — so a
 * memory you cannot trace, correct, or retire is a liability rather than a feature.
 *
 * Editing the text does not overwrite: the old belief is retired and linked, so the
 * panel can show what it used to think. That is why `previous` exists.
 */

const CATEGORIES = [
  { value: "preference", label: "Preference" },
  { value: "health", label: "Health" },
  { value: "work", label: "Work" },
  { value: "finance", label: "Finance" },
  { value: "relationship", label: "Relationship" },
  { value: "other", label: "Other" },
];

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

type Props = {
  factId: string | null;
  onClose: () => void;
  onSaved: (fact: Fact, supersededId: string | null) => void;
  onConfirmed: (fact: Fact) => void;
  onForget: (fact: Fact) => void;
  onOpenSession: (sessionId: string) => void;
};

export default function FactSheet({
  factId,
  onClose,
  onSaved,
  onConfirmed,
  onForget,
  onOpenSession,
}: Props) {
  const [detail, setDetail] = useState<FactDetail | null>(null);
  const [text, setText] = useState("");
  const [category, setCategory] = useState("other");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!factId) return;
    let alive = true;
    setStatus("loading");
    setError(null);
    api
      .getFact(factId)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setText(d.fact);
        setCategory(d.category);
        setStatus("ready");
      })
      .catch(() => alive && setStatus("error"));
    return () => {
      alive = false;
    };
  }, [factId]);

  const dirty = detail != null && (text.trim() !== detail.fact || category !== detail.category);

  async function save() {
    if (!detail || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      const patch: { fact?: string; category?: string } = {};
      if (text.trim() !== detail.fact) patch.fact = text.trim();
      if (category !== detail.category) patch.category = category;
      const saved = await api.updateFact(detail.id, patch);
      // A text change supersedes, so the id changes and the old row leaves the list.
      onSaved(saved, saved.id !== detail.id ? detail.id : null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that change");
    } finally {
      setSaving(false);
    }
  }

  async function toggleConfirmed() {
    if (!detail) return;
    const next = detail.source !== "stated";
    setSaving(true);
    setError(null);
    try {
      const saved = await api.setFactConfirmed(detail.id, next);
      onConfirmed(saved);
      setDetail({ ...detail, ...saved });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change that");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={factId != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent title="Fact details">
        {status === "loading" && (
          <div className="space-y-3 py-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-9 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}

        {status === "error" && (
          <p role="alert" className="py-2 text-sm text-destructive">
            Couldn't load this fact. Close and try again.
          </p>
        )}

        {status === "ready" && detail && (
          <div className="space-y-5 py-1">
            <div className="space-y-2">
              <label htmlFor="fact-text" className="text-sm font-medium">
                What Acero believes
              </label>
              <textarea
                id="fact-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
              />
              <p className="text-xs text-muted-foreground">
                Rewording this retires the old version rather than erasing it — you'll
                still be able to see what changed. Saving also marks it confirmed, since
                you wrote it.
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Category</label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <dl className="space-y-2 border-t border-border pt-4 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">How it was learned</dt>
                <dd className="text-right">
                  {detail.source === "stated" ? "You confirmed it" : "Acero inferred it"}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Confidence</dt>
                <dd>{Math.round(detail.confidence * 100)}%</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Learned</dt>
                <dd>{formatDay(detail.valid_from)}</dd>
              </div>
            </dl>

            {detail.source_session_id ? (
              <Button
                variant="outline"
                className="w-full justify-start"
                onClick={() => onOpenSession(detail.source_session_id!)}
              >
                <MessageSquareText className="size-4" />
                Open the conversation this came from
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">
                No conversation is recorded for this one — it predates provenance tracking.
              </p>
            )}

            {detail.previous && (
              <div className="rounded-lg border border-border bg-muted/40 p-3">
                <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <History className="size-3.5" /> Previously
                </p>
                <p className="mt-1 text-sm line-through decoration-muted-foreground/50">
                  {detail.previous.fact}
                </p>
              </div>
            )}

            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        )}

        {status === "ready" && detail && (
          <SheetFooter>
            <Button
              variant="ghost"
              onClick={() => {
                onForget(detail);
                onClose();
              }}
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="size-4" /> Forget
            </Button>
            <div className="flex-1" />
            <Button
              variant="outline"
              onClick={toggleConfirmed}
              disabled={saving}
              aria-pressed={detail.source === "stated"}
            >
              {detail.source === "stated" ? (
                <>
                  <BadgeX className="size-4" /> Unconfirm
                </>
              ) : (
                <>
                  <BadgeCheck className="size-4" /> Confirm
                </>
              )}
            </Button>
            <Button onClick={save} disabled={!dirty || saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}
