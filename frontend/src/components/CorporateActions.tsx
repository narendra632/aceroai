import { useState } from "react";
import { AlertTriangle, Check, Split } from "lucide-react";

import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { CorporateAction } from "@/lib/api";
import { formatDateFull, formatQuantity } from "@/lib/format";

/* Splits and bonuses the exchange announced.
 *
 * This card sits near the top of the page, above the chart and the holdings, and that
 * placement is the point rather than a layout preference. A 1:1 bonus halves the quoted
 * price overnight; until the ledger knows about it, every figure on this page for that
 * holding says it lost half its value. The card has to be the first thing read, because the
 * number it explains is large, alarming and entirely fictional.
 *
 * ⚠ **Applying writes a real transaction.** It is a button rather than something the page
 * does quietly on open, because appending to the ledger on a reader's behalf — from a string
 * parsed out of a feed — is the one thing this module promises never to do without being
 * told. The scheduled job does apply unambiguous ones on their ex-date; this is the same
 * action, offered early or offered when the job could not read the announcement.
 */

function statusTone(status: CorporateAction["status"]): string {
  if (status === "NEEDS_REVIEW") return "border-amber-500/40 bg-amber-500/5";
  if (status === "APPLIED") return "border-border bg-card";
  return "border-border bg-card";
}

export default function CorporateActions({
  actions,
  onChange,
}: {
  actions: CorporateAction[];
  onChange: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const open = actions.filter(
    (a) => a.status === "PENDING" || a.status === "NEEDS_REVIEW",
  );
  const applied = actions.filter((a) => a.status === "APPLIED");
  if (open.length === 0 && applied.length === 0) return null;

  async function run(id: string, fn: (id: string) => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await fn(id);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3">
      {open.map((a) => (
        <div
          key={a.id}
          className={`rounded-xl border p-4 ${statusTone(a.status)}`}
        >
          <div className="flex items-start gap-2">
            {a.status === "NEEDS_REVIEW" ? (
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
            ) : (
              <Split className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {a.symbol} · {a.ratio_text ?? a.action_type.toLowerCase()}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {a.ex_date
                  ? `Ex-date ${formatDateFull(a.ex_date)}`
                  : "Ex-date not yet fixed"}{" "}
                · announced by {a.source}
              </p>

              {/* ⚠ Always shown, whether or not the ratio was read. This is the exchange's
                  own wording, and it is what a reader checks the arithmetic against. */}
              <p className="mt-2 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                {a.purpose}
              </p>

              {a.status === "NEEDS_REVIEW" ? (
                <p className="mt-2 text-sm">
                  This could not be read precisely enough to apply on its own
                  {a.note ? ` — ${a.note}` : ""}. Record the quantity change
                  yourself below, then dismiss this.
                </p>
              ) : a.quantity_before != null && a.quantity_after != null ? (
                <p className="mt-2 text-sm">
                  Your{" "}
                  <span className="font-medium tabular-nums">
                    {formatQuantity(a.quantity_before)}
                  </span>{" "}
                  becomes{" "}
                  <span className="font-medium tabular-nums">
                    {formatQuantity(a.quantity_after)}
                  </span>
                  . Nothing is paid and nothing is gained — the price falls by
                  the same proportion, so the holding is worth what it was.
                </p>
              ) : (
                <p className="mt-2 text-sm">
                  Nothing of this holding is in the book, so there is nothing to
                  adjust.
                </p>
              )}

              <div className="mt-3 flex flex-wrap gap-2">
                {a.status === "PENDING" && a.quantity_change != null && (
                  <Button
                    size="sm"
                    disabled={busy === a.id}
                    onClick={() => void run(a.id, api.applyCorporateAction)}
                  >
                    {busy === a.id ? "Applying…" : "Apply to my holding"}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy === a.id}
                  onClick={() => void run(a.id, api.dismissCorporateAction)}
                >
                  Not mine
                </Button>
              </div>
            </div>
          </div>
        </div>
      ))}

      {applied.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="flex items-center gap-1.5 text-sm font-medium">
            <Check className="size-3.5 text-muted-foreground" />
            Recently applied
          </p>
          <ul className="mt-2 space-y-1">
            {applied.map((a) => (
              <li key={a.id} className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{a.symbol}</span>{" "}
                {a.ratio_text ?? a.action_type.toLowerCase()}
                {a.ex_date ? ` on ${formatDateFull(a.ex_date)}` : ""} — the
                entry is in the history below and can be withdrawn.
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
