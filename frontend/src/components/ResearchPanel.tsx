import { useCallback, useEffect, useState } from "react";
import { Telescope } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { QueueLine, ResearchQueue } from "@/lib/api";

/* Companies something named, that you neither hold nor watch.
 *
 * ⚠ **This is the half that makes it a research assistant.** Without it the system can only
 * ever say hold, trim or sell — a research analyst that can only comment on what you already
 * own is a bookkeeper with opinions.
 *
 * ⚠ **Nothing here is a recommendation.** A company reaches this list because a source named
 * it, and a source naming something is a lead, never an instruction. A suggestion resting on
 * commentary alone is still refused by the sourcing gate whatever the commentary said.
 */

const TIER_LABEL: Record<number, string> = { 1: "filing", 2: "press", 3: "commentary" };

function Tier({ tier }: { tier: number }) {
  const tone =
    tier === 1
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
      : tier === 2
        ? "border-border bg-muted/40 text-muted-foreground"
        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-500";
  return (
    <span className={`rounded-full border px-1.5 py-0.5 text-[11px] ${tone}`}>
      {TIER_LABEL[tier] ?? "unknown"}
    </span>
  );
}

/* ⚠ Age is shown in words rather than a date, because the question this panel has to answer
   at a glance is "has this been sitting here too long" — which the weekly review asks by
   name — and a date makes the reader do that arithmetic themselves. */
function age(days: number) {
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  return `${Math.round(days / 30)} months ago`;
}

function Row({
  line,
  busy,
  onPromote,
  onDismiss,
}: {
  line: QueueLine;
  busy: boolean;
  onPromote: (line: QueueLine) => void;
  onDismiss: (line: QueueLine) => void;
}) {
  return (
    <li className="border-t border-border px-3 py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-sm font-semibold">{line.symbol}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{line.name}</span>
        <Tier tier={line.best_trust_tier} />
      </div>

      <p className="mt-0.5 text-xs text-muted-foreground">
        named by {line.named_by ?? "an unnamed source"} · first seen {age(line.age_days)}
        {/* ⚠ Repetition is shown because it is what the ordering rests on. */}
        {line.mention_count > 1 && ` · mentioned ${line.mention_count} times`}
      </p>

      {line.excerpt && (
        <p className="mt-1.5 border-l-2 border-border pl-2 text-xs italic text-muted-foreground">
          {line.excerpt}
        </p>
      )}

      {line.status === "DISMISSED" ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Not taken up — {line.dismissed_reason}
        </p>
      ) : line.status === "PROMOTED" ? (
        <p className="mt-2 text-xs text-muted-foreground">Now followed.</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => onPromote(line)}
            className="rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
          >
            Look at it
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDismiss(line)}
            className="rounded-lg px-2.5 py-1 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground disabled:opacity-50"
          >
            Not interested
          </button>
        </div>
      )}
    </li>
  );
}

export default function ResearchPanel() {
  const [data, setData] = useState<ResearchQueue | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [dismissing, setDismissing] = useState<QueueLine | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(() => {
    api
      .getResearchQueue()
      .then(setData)
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (failed || !data) return null;

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await run();
      load();
    } finally {
      setBusy(false);
    }
  };

  const confirmDismiss = async () => {
    if (!dismissing || reason.trim().length < 3) return;
    const target = dismissing;
    const why = reason.trim();
    setDismissing(null);
    setReason("");
    await act(() => api.dismissCandidate(target.id, why));
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Telescope className="size-3.5 text-muted-foreground" />
          Worth a look
          <InfoTip label="Where these come from">
            Companies a source named that you neither hold nor watch. They are
            leads, not recommendations — a suggestion resting on commentary
            alone is refused by the rules whatever the commentary said. Nothing
            here is priced or scored until you ask for it.
          </InfoTip>
          {data.lines.length > 0 && (
            <span className="rounded-full border border-border bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground">
              {data.lines.length}
            </span>
          )}
        </h2>
        <button
          type="button"
          className="text-xs text-muted-foreground underline underline-offset-2"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "hide" : "show"}
        </button>
      </div>

      {open && (
        <div className="rounded-xl border border-border bg-card">
          {data.lines.length === 0 ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              Nothing waiting. Sources are being read against{" "}
              {data.universe_size.toLocaleString()} listed companies — a company
              lands here the moment one of them names it.
            </p>
          ) : (
            <ul>
              {data.lines.map((line) => (
                <Row
                  key={line.id}
                  line={line}
                  busy={busy}
                  onPromote={(l) => act(() => api.promoteCandidate(l.id))}
                  onDismiss={(l) => {
                    setDismissing(l);
                    setReason("");
                  }}
                />
              ))}
            </ul>
          )}
        </div>
      )}

      {/* ⚠ A reason is required, by the database rather than by this form. It is the only
          record of what kinds of idea keep being refused — the data that eventually says
          something about your own filter. */}
      {dismissing && (
        <div className="rounded-xl border border-border bg-card p-3">
          <p className="text-sm font-medium">
            Not taking up {dismissing.symbol} — why?
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Kept so the system can eventually tell you what kinds of idea you
            keep turning down.
          </p>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            autoFocus
            placeholder="too expensive, outside the framework, governance…"
            className="mt-2 w-full rounded-lg border border-border bg-background p-2 text-sm"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy || reason.trim().length < 3}
              onClick={confirmDismiss}
              className="rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
            >
              Record it
            </button>
            <button
              type="button"
              onClick={() => setDismissing(null)}
              className="rounded-lg px-2.5 py-1 text-xs text-muted-foreground underline underline-offset-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
