import { useEffect, useState } from "react";
import { Check, CircleDashed, Target, X } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { Criterion, Verdict } from "@/lib/api";

/* The six criteria for real money.
 *
 * ⚠ **Written down in advance so they cannot be softened later.** That is the whole point:
 * committing to a standard before you know whether you will meet it is the only version of
 * the commitment worth anything, because afterwards every failed criterion has a reason, and
 * every reason is persuasive to the person who needs it to be.
 *
 * ⚠ **Three states, never two.** Not-yet-testable is rendered differently from failed, in a
 * different colour and a different icon, because an interface that collapsed them would turn
 * "we do not know" into "we fell short" — and, far worse, would let a reader who saw four
 * greys read them as four nearly-theres.
 */

function Mark({ met }: { met: boolean | null }) {
  if (met === true) {
    return (
      <Check className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" aria-label="met" />
    );
  }
  if (met === false) {
    return <X className="size-4 shrink-0 text-rose-600 dark:text-rose-400" aria-label="not met" />;
  }
  return (
    <CircleDashed
      className="size-4 shrink-0 text-muted-foreground"
      aria-label="not yet testable"
    />
  );
}

function Row({ c }: { c: Criterion }) {
  return (
    <li className="flex gap-2.5 border-t border-border py-2.5 first:border-t-0">
      <Mark met={c.met} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{c.question}</p>
        <p className="mt-0.5 text-xs">
          <span className={c.met === null ? "text-muted-foreground" : ""}>{c.value}</span>
          <span className="text-muted-foreground"> · needs {c.target}</span>
          {/* ⚠ Printed beside the figure, never below the fold. The error bar is the number
              that says a good year and a mediocre one look the same. */}
          {c.standard_error && (
            <span className="text-muted-foreground"> · ±{c.standard_error}</span>
          )}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{c.detail}</p>
      </div>
    </li>
  );
}

export default function VerdictPanel() {
  const [data, setData] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getVerdict()
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed || !data) return null;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Target className="size-3.5 text-muted-foreground" />
          Before any real money
          <InfoTip label="Why these six">
            They were written down before anyone knew whether they would be
            met. That is the only version of the commitment worth anything —
            afterwards, every failed criterion has a reason, and every reason is
            persuasive to the person who needs it to be.
          </InfoTip>
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
        <div className="space-y-2 rounded-xl border border-border bg-card p-3">
          <p className="text-sm">{data.headline}</p>

          <ul>
            {data.criteria.map((c) => (
              <Row key={c.key} c={c} />
            ))}
          </ul>

          {/* ⚠ The legend exists because the grey state is the one a reader will otherwise
              guess at, and guessing "nearly" is the flattering guess. */}
          <p className="border-t border-border pt-2 text-xs text-muted-foreground">
            <CircleDashed className="mr-1 inline size-3" aria-hidden="true" />
            means <strong>not yet testable</strong> — no sample behind it. That is
            not the same as falling short, and it is the state most of these
            will be in for a long time.
          </p>

          {data.all_met && (
            <p className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-800 dark:text-amber-400">
              Even on a clean sweep, the sane action is a small sleeve run in
              parallel for another year — not a switch.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
