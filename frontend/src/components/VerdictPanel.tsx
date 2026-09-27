import { useEffect, useState } from "react";
import { Check, CircleDashed, Target, X } from "lucide-react";

import { Callout, Section } from "@/components/investments/kit";
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
      <Check className="size-4 shrink-0 text-good" aria-label="met" />
    );
  }
  if (met === false) {
    return <X className="size-4 shrink-0 text-bad" aria-label="not met" />;
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
    <li className="flex gap-3 py-3 first:pt-0 last:pb-0">
      <Mark met={c.met} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{c.question}</p>
        <p className="mt-0.5 text-xs">
          <span className={c.met === null ? "text-muted-foreground" : "font-medium"}>
            {c.value}
          </span>
          <span className="text-muted-foreground"> · needs {c.target}</span>
          {/* ⚠ Printed beside the figure, never below the fold. The error bar is the number
              that says a good year and a mediocre one look the same. */}
          {c.standard_error && <span className="text-muted-foreground"> · ±{c.standard_error}</span>}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">{c.detail}</p>
      </div>
    </li>
  );
}

export default function VerdictPanel() {
  const [data, setData] = useState<Verdict | null>(null);
  const [failed, setFailed] = useState(false);

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
    <Section
      icon={Target}
      memory="scorecard.verdict"
      title="Before any real money"
      summary={
        <>
          {data.met} of {data.criteria.length} met
          {data.failed > 0 && ` · ${data.failed} not met`}
          {data.untested > 0 && ` · ${data.untested} not testable yet`} — written down in advance so
          they cannot be softened later
        </>
      }
    >
      <ul className="divide-y divide-border">
        {data.criteria.map((c) => (
          <Row key={c.key} c={c} />
        ))}
      </ul>

      {/* ⚠ The legend exists because the grey state is the one a reader will otherwise guess
          at, and guessing "nearly" is the flattering guess. */}
      <p className="mt-3 flex items-start gap-1.5 border-t border-border pt-3 text-xs text-muted-foreground">
        <CircleDashed className="mt-px size-3.5 shrink-0" aria-hidden="true" />
        <span>
          <strong className="font-medium text-foreground">Not testable yet</strong> means there is
          no sample behind it. That is not falling short, and it is where most of these will sit
          for a long time.
        </span>
      </p>

      {data.all_met && (
        <Callout tone="info" title="Even on a clean sweep" className="mt-3">
          The sane action is a small sleeve run in parallel for another year — not a switch.
        </Callout>
      )}
    </Section>
  );
}
