import { useEffect, useState } from "react";
import { Scale } from "lucide-react";

import { Callout, Chip, Section } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Benchmarks } from "@/lib/api";
import { directionClass } from "@/lib/investments";

/* The book against what you could have bought instead.
 *
 * ⚠ **The alternative is an index FUND, not an index**, and the panel says so. An index cannot
 * be bought; a fund's NAV carries the expense ratio and tracking error a real alternative
 * would have charged, which makes it slightly harder to beat than a raw total-return index.
 * That is the honest direction for the asymmetry to run.
 *
 * ⚠ **Beating the benchmark over three months means nothing**, and the window is always
 * printed beside the figures so it cannot be read as a verdict.
 */

const WINDOWS = [
  { days: 30, label: "1M" },
  { days: 90, label: "3M" },
  { days: 365, label: "1Y" },
];

function pct(raw: string | null) {
  if (raw == null) return null;
  const value = Number(raw) * 100;
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

export default function BenchmarksPanel() {
  const [days, setDays] = useState(365);
  const [data, setData] = useState<Benchmarks | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getBenchmarks(days)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [days]);

  if (failed || !data) return null;

  const mine = data.portfolio_pct == null ? null : Number(data.portfolio_pct);
  const theirs = data.blended_pct == null ? null : Number(data.blended_pct);
  const gap = mine != null && theirs != null ? (mine - theirs) * 100 : null;

  return (
    <Section
      icon={Scale}
      memory="scorecard.benchmarks"
      title="Against the alternative"
      summary={
        gap == null
          ? "Your book against simply buying index funds — not readable over this window yet"
          : `${gap >= 0 ? "Ahead of" : "Behind"} the same mix in index funds by ${Math.abs(gap).toFixed(1)} points, ${data.start} to ${data.end}`
      }
      tip="Compared with an index FUND, not an index: a fund's price includes its fees and dividends, which is what the real alternative would have given you."
      actions={
        <div className="flex gap-0.5" role="group" aria-label="Window">
          {WINDOWS.map((w) => (
            <Button
              key={w.days}
              size="xs"
              variant={days === w.days ? "secondary" : "ghost"}
              aria-pressed={days === w.days}
              onClick={() => setDays(w.days)}
            >
              {w.label}
            </Button>
          ))}
        </div>
      }
    >
      {/* ⚠ The two numbers side by side, at the same size. The question is the comparison, and
          a book's return on its own invites being read as a verdict. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">Your book</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums ${directionClass(data.portfolio_pct)}`}>
            {/* ⚠ "—" rather than 0. A book that could not be valued across the window has no
                return, and zero is a different claim entirely. */}
            {pct(data.portfolio_pct) ?? "—"}
          </p>
          {Number(data.weights.IN ?? 0) > 0 && (
            <p className="text-xs text-muted-foreground">
              equities {Math.round(Number(data.weights.IN) * 100)}% India ·{" "}
              {Math.round(Number(data.weights.US) * 100)}% US
            </p>
          )}
        </div>
        <div className="rounded-lg bg-muted/40 p-3">
          <p className="text-xs text-muted-foreground">The same mix, in index funds</p>
          <p className={`mt-1 text-2xl font-semibold tabular-nums ${directionClass(data.blended_pct)}`}>
            {pct(data.blended_pct) ?? "—"}
          </p>
          <p className="text-xs text-muted-foreground">weighted the way your equities are</p>
        </div>
      </div>

      {gap != null && (
        <p className="mt-3 flex items-center gap-2 text-sm">
          <Chip tone={gap >= 0 ? "good" : "caution"}>
            {gap >= 0 ? "ahead" : "behind"} by {Math.abs(gap).toFixed(1)} points
          </Chip>
          <span className="text-xs text-muted-foreground">
            {data.start} to {data.end} — one window is not a verdict
          </span>
        </p>
      )}

      {data.lines.length > 0 && (
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">Each index fund on its own</caption>
          <tbody>
            {data.lines.map((line) => (
              <tr key={line.key} className="border-t border-border align-top">
                <th scope="row" className="py-2 text-left font-normal">
                  {line.name}
                  <span className="block max-w-sm text-xs text-muted-foreground">
                    {line.proxy_for}
                  </span>
                </th>
                <td className="py-2 text-right tabular-nums text-muted-foreground">
                  {pct(line.change_pct) ?? <span title={line.detail}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ⚠ Beside the figures, never instead of them. The portfolio's own return genuinely
          includes crypto and funds; quietly excluding them would be picking the flattering
          subset. */}
      {data.caveat && (
        <Callout tone="info" title="The two sides are not quite the same thing" className="mt-3">
          {data.caveat}
        </Callout>
      )}
      {!data.readable && <p className="mt-3 text-xs text-muted-foreground">{data.detail}</p>}
      <p className="mt-3 text-xs text-muted-foreground">
        The criterion written down in advance asks for twelve months across at least two different
        market conditions — this is to be watched, not concluded from.
      </p>
    </Section>
  );
}
