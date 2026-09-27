import { useEffect, useState } from "react";
import { Crosshair } from "lucide-react";

import { Meter, Section } from "@/components/investments/kit";
import * as api from "@/lib/api";
import type { Measure } from "@/lib/api";

/* Is its reasoning any good — the prediction record.
 *
 * ⚠ Moved here from the Decisions tab. It answers whether the thinking works, which is a
 * question for the monthly sit-down; beside the suggestions it read as a verdict on tonight's
 * idea, and a line of four "—"s under every suggestion taught its reader to skip the block.
 *
 * ⚠ **A measure waiting for its sample is drawn as progress, never as a blank.** A blank reads
 * as zero to anyone scanning; "3 of 20 needed", with a bar a sixth full, cannot be. And the
 * figure is still withheld until the sample is there — a rate over six outcomes reads exactly
 * like one over six hundred, and showing it with a caveat would still be read as a finding.
 */

const QUESTION: Record<string, string> = {
  claim_accuracy: "Do the things it predicts come true?",
  calibration: "When it says 80%, is it right 80% of the time?",
  trigger_discipline: "When something disproved an idea, did anything happen?",
  decision_record: "How often did you agree with it?",
};

function value(m: Measure): string {
  if (m.value == null) return "—";
  if (m.name === "calibration") return `Brier ${Number(m.value).toFixed(3)}`;
  return `${Math.round(Number(m.value) * 100)}%`;
}

function Row({ m }: { m: Measure }) {
  const waiting = m.value == null && m.needed != null;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <p className="text-sm font-medium">{QUESTION[m.name] ?? m.name.replace(/_/g, " ")}</p>
        {waiting ? (
          <Meter
            value={m.n}
            max={m.needed ?? 1}
            label="Outcomes so far, of those needed"
            tone="info"
            text={`${m.n} of ${m.needed}`}
            width="w-24"
          />
        ) : (
          <span className="text-sm font-semibold tabular-nums">{value(m)}</span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{m.detail}</p>
    </li>
  );
}

export default function MeasuresPanel() {
  const [measures, setMeasures] = useState<Measure[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getProposals()
      .then((d) => !cancelled && setMeasures(d.measures))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!measures || measures.length === 0) return null;
  const reporting = measures.filter((m) => m.value != null).length;

  return (
    <Section
      icon={Crosshair}
      memory="scorecard.measures"
      title="How its predictions are doing"
      summary={
        reporting === 0
          ? "Every idea writes down checkable predictions; nothing is scored until enough have come due"
          : `${reporting} of ${measures.length} measures have enough behind them to report`
      }
      tip="Thirty-odd decisions a year say nothing statistical for years. But each idea makes several checkable predictions, so this becomes answerable in months."
    >
      <ul className="divide-y divide-border">
        {measures.map((m) => (
          <Row key={m.name} m={m} />
        ))}
      </ul>
    </Section>
  );
}
