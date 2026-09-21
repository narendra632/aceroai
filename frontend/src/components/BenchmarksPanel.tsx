import { useEffect, useState } from "react";
import { Scale } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { Benchmarks } from "@/lib/api";

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
  { days: 30, label: "1m" },
  { days: 90, label: "3m" },
  { days: 365, label: "1y" },
];

function pct(raw: string | null) {
  if (raw == null) return null;
  const value = Number(raw) * 100;
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function tone(a: string | null, b: string | null) {
  if (a == null || b == null) return "";
  return Number(a) >= Number(b)
    ? "text-emerald-700 dark:text-emerald-400"
    : "text-rose-700 dark:text-rose-400";
}

export default function BenchmarksPanel() {
  const [days, setDays] = useState(365);
  const [data, setData] = useState<Benchmarks | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

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

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Scale className="size-3.5 text-muted-foreground" />
          Against the alternative
          <InfoTip label="What it is compared with">
            An index fund, not an index — you cannot buy an index, and a fund's
            NAV includes its dividends and charges the fee a real alternative
            would have charged. That makes it slightly harder to beat than the
            headline index, which is the honest direction.
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
          <div className="flex flex-wrap items-center gap-1.5">
            {WINDOWS.map((w) => (
              <button
                key={w.days}
                type="button"
                onClick={() => setDays(w.days)}
                className={`rounded-lg border px-2 py-0.5 text-xs ${
                  days === w.days
                    ? "border-border bg-muted font-medium"
                    : "border-transparent text-muted-foreground hover:bg-muted/50"
                }`}
              >
                {w.label}
              </button>
            ))}
            {/* ⚠ The window is printed, always. Beating an index over a month is noise, and a
                figure without its span invites being read as a verdict. */}
            <span className="ml-auto text-xs text-muted-foreground">
              {data.start} to {data.end}
            </span>
          </div>

          <table className="w-full text-sm">
            <tbody>
              <tr className="border-t border-border">
                <th scope="row" className="py-2 text-left font-medium">
                  Your book
                  {Number(data.weights.IN ?? 0) > 0 && (
                    <span className="block text-xs font-normal text-muted-foreground">
                      {Math.round(Number(data.weights.IN) * 100)}% India ·{" "}
                      {Math.round(Number(data.weights.US) * 100)}% US
                    </span>
                  )}
                </th>
                <td
                  className={`py-2 text-right tabular-nums ${tone(
                    data.portfolio_pct,
                    data.blended_pct,
                  )}`}
                >
                  {/* ⚠ "—" rather than 0. A book that could not be valued across the window
                      has no return, and zero is a different claim entirely. */}
                  {pct(data.portfolio_pct) ?? (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>

              <tr className="border-t border-border">
                <th scope="row" className="py-2 text-left font-medium">
                  The same mix, in index funds
                  <span className="block text-xs font-normal text-muted-foreground">
                    weighted the way your equities are
                  </span>
                </th>
                <td className="py-2 text-right tabular-nums">
                  {pct(data.blended_pct) ?? <span className="text-muted-foreground">—</span>}
                </td>
              </tr>

              {data.lines.map((line) => (
                <tr key={line.key} className="border-t border-border align-top">
                  <th scope="row" className="py-2 text-left font-normal text-muted-foreground">
                    {line.name}
                    <span className="block max-w-sm text-xs">{line.proxy_for}</span>
                  </th>
                  <td className="py-2 text-right tabular-nums text-muted-foreground">
                    {pct(line.change_pct) ?? (
                      <span title={line.detail}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* ⚠ Beside the figures, never instead of them. The portfolio's own return genuinely
              includes crypto and funds; quietly excluding them would be picking the flattering
              subset. */}
          {data.caveat && (
            <p className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-800 dark:text-amber-400">
              {data.caveat}
            </p>
          )}

          {!data.readable && (
            <p className="text-xs text-muted-foreground">{data.detail}</p>
          )}

          <p className="text-xs text-muted-foreground">
            One window is not a verdict. The criterion written down in advance
            asks for twelve months across at least two different market
            conditions — this is here to be watched, not to be concluded from.
          </p>
        </div>
      )}
    </section>
  );
}
