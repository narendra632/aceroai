import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Info } from "lucide-react";

import { Bars, Legend, Sparkline, StackedArea, type Series } from "@/components/ui/chart";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Waterfall } from "@/components/ui/waterfall";
import { formatMs, formatUSD } from "@/lib/format";
import * as api from "@/lib/api";
import type { InsightsOverview, TurnRow, TurnSpan } from "@/lib/api";
import { cn } from "@/lib/utils";

/* What the assistant costs, and where its time goes.
 *
 * Strictly read-only: nothing on this page changes anything, which is what makes it safe
 * to open, reload and leave open.
 *
 * The single most useful thing here is that spend is split by WHAT THE CALL WAS FOR. One
 * message is not one model call — it is a reply, plus an embedding to recall context, plus
 * a second model call to learn from the turn. Only the reply was ever visible before.
 */

const SERIES: Series[] = [
  { key: "chat", label: "Replies", color: "var(--series-1)" },
  { key: "embed", label: "Recall", color: "var(--series-2)" },
  { key: "memory_extract", label: "Learning", color: "var(--series-3)" },
];

const RANGES = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: undefined },
];

function pct(n: number): string {
  return `${(n * 100).toFixed(n < 0.1 ? 1 : 0)}%`;
}

function whenFrom(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const KIND_LABEL: Record<string, string> = {
  chat: "Reply",
  embed: "Recall",
  memory_extract: "Learning",
  job: "Scheduled",
};

function Tile({
  label,
  value,
  hint,
  spark,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  spark?: number[];
  tone?: "warn";
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        {spark && spark.length > 1 && <Sparkline values={spark} />}
      </div>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold",
          tone === "warn" && "text-destructive",
        )}
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default function InsightsView() {
  const [range, setRange] = useState<(typeof RANGES)[number]>(RANGES[1]);
  const [data, setData] = useState<InsightsOverview | null>(null);
  const [turns, setTurns] = useState<TurnRow[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [openTurn, setOpenTurn] = useState<{ turn: TurnRow; spans: TurnSpan[] } | null>(null);
  const [loadingTurn, setLoadingTurn] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([
      api.getInsights({ days: range.days, allTime: range.days === undefined }),
      api.listTurns(40),
    ])
      .then(([overview, recent]) => {
        setData(overview);
        setTurns(recent);
        setStatus("ready");
      })
      .catch(() => setStatus("error"));
  }, [range]);

  useEffect(load, [load]);

  // Days are sparse in the API response (a day with no calls has no row), so fill the
  // gaps — a line that skips empty days implies activity that never happened.
  const chartData = useMemo(() => {
    if (!data) return [];
    const byDay = new Map<string, Record<string, number>>();
    for (const p of data.series) {
      const bucket = byDay.get(p.day) ?? {};
      bucket[p.kind] = (bucket[p.kind] ?? 0) + Number(p.cost_usd);
      byDay.set(p.day, bucket);
    }
    const days = [...byDay.keys()].sort();
    if (days.length === 0) return [];
    const out: { day: string; values: Record<string, number> }[] = [];
    const cursor = new Date(`${days[0]}T00:00:00`);
    const last = new Date(`${days[days.length - 1]}T00:00:00`);
    while (cursor <= last) {
      const key = cursor.toISOString().slice(0, 10);
      out.push({ day: key, values: byDay.get(key) ?? {} });
      cursor.setDate(cursor.getDate() + 1);
    }
    return out;
  }, [data]);

  const dailyTotals = useMemo(
    () => chartData.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0)),
    [chartData],
  );

  async function openWaterfall(id: string) {
    setLoadingTurn(true);
    try {
      setOpenTurn(await api.getTurn(id));
    } catch {
      setOpenTurn(null);
    } finally {
      setLoadingTurn(false);
    }
  }

  const s = data?.summary;
  const backgroundShare = useMemo(() => {
    if (!data) return 0;
    const total = data.series.reduce((sum, p) => sum + Number(p.cost_usd), 0);
    const background = data.series
      .filter((p) => p.kind !== "chat")
      .reduce((sum, p) => sum + Number(p.cost_usd), 0);
    return total > 0 ? background / total : 0;
  }, [data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">Insights</h1>
            <p className="text-sm text-muted-foreground">
              What Acero costs, how fast it is, and what goes wrong.
            </p>
          </div>
          <div className="flex shrink-0 rounded-lg border border-border p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.label}
                onClick={() => setRange(r)}
                aria-pressed={range.label === r.label}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                  range.label === r.label
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {status === "loading" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-64 rounded-xl" />
          </div>
        )}

        {status === "error" && (
          <ErrorState
            title="Couldn't load your usage"
            detail="This is a connection problem, not an absence of activity."
            onRetry={load}
          />
        )}

        {status === "ready" && s && (
          <div className="space-y-6">
            {s.calls === 0 ? (
              <EmptyState
                icon={Activity}
                title="Nothing recorded yet"
                hint="Every model call is measured from now on. Send a message and it appears here."
              />
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <Tile
                    label="Estimated spend"
                    value={formatUSD(Number(s.cost_usd))}
                    hint={
                      s.unpriced > 0
                        ? `${s.unpriced} call${s.unpriced > 1 ? "s" : ""} with no known price`
                        : `${s.calls} calls`
                    }
                    spark={dailyTotals}
                  />
                  <Tile
                    label="Typical reply"
                    value={formatMs(s.p50_ms)}
                    hint={
                      s.p50_ttft_ms != null
                        ? `first word after ${formatMs(s.p50_ttft_ms)}`
                        : undefined
                    }
                  />
                  <Tile
                    label="Slowest 5%"
                    value={formatMs(s.p95_ms)}
                    hint="p95, not an average"
                  />
                  <Tile
                    label="Failures"
                    value={pct(s.error_rate)}
                    hint={`${s.failed} of ${s.calls}`}
                    tone={s.error_rate > 0.05 ? "warn" : undefined}
                  />
                </div>

                {backgroundShare > 0 && (
                  <div className="flex items-start gap-3 rounded-xl border border-border bg-muted/40 p-4 text-sm">
                    <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <p className="text-muted-foreground">
                      <strong className="font-medium text-foreground">
                        {pct(backgroundShare)} of this spend is work you never see
                      </strong>{" "}
                      — recalling what Acero knows before it answers, and a second model
                      call afterwards to learn from the turn. Both were billed and
                      uncounted until now.
                    </p>
                  </div>
                )}

                <section className="rounded-xl border border-border bg-card p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h2 className="text-sm font-medium">Spend over time</h2>
                    <Legend series={SERIES} />
                  </div>
                  <StackedArea data={chartData} series={SERIES} className="mt-3" />
                </section>

                <div className="grid gap-4 lg:grid-cols-2">
                  <section className="rounded-xl border border-border bg-card p-4">
                    <h2 className="text-sm font-medium">Where the money goes</h2>
                    <Bars
                      className="mt-3"
                      data={data.by_model.map((m) => ({
                        label: m.model ?? "unknown",
                        value: Number(m.cost_usd),
                        hint: `${m.calls}×`,
                      }))}
                    />
                  </section>

                  <section className="rounded-xl border border-border bg-card p-4">
                    <h2 className="text-sm font-medium">What goes wrong</h2>
                    {data.errors.length === 0 ? (
                      <p className="mt-3 text-sm text-muted-foreground">
                        No failures in this period.
                      </p>
                    ) : (
                      <Bars
                        className="mt-3"
                        format={(n) => `${n}`}
                        data={data.errors.map((e) => ({
                          label: e.error_type,
                          value: e.count,
                        }))}
                      />
                    )}
                  </section>
                </div>

                {data.by_provider.length > 1 && (
                  <section className="rounded-xl border border-border bg-card p-4">
                    <h2 className="text-sm font-medium">Providers, side by side</h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Replies only — embeddings are pinned to one provider regardless of
                      your choice, so counting them would blame it for work the setting
                      never touched.
                    </p>
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted-foreground">
                            <th className="pb-2 font-medium">Provider</th>
                            <th className="pb-2 text-right font-medium">Per reply</th>
                            <th className="pb-2 text-right font-medium">Typical</th>
                            <th className="pb-2 text-right font-medium">Failures</th>
                          </tr>
                        </thead>
                        <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
                          {data.by_provider.map((p) => (
                            <tr key={p.provider} className="border-t border-border">
                              <td className="py-2 capitalize">{p.provider}</td>
                              <td className="py-2 text-right">
                                {formatUSD(Number(p.cost_per_call))}
                              </td>
                              <td className="py-2 text-right">{formatMs(p.p50_ms)}</td>
                              <td className="py-2 text-right">{pct(p.error_rate)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}

                <section className="rounded-xl border border-border bg-card p-4">
                  <h2 className="text-sm font-medium">Recent calls</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Select one to see where its time went.
                  </p>
                  <ul className="mt-3 divide-y divide-border">
                    {turns.map((t) => (
                      <li key={t.id}>
                        <button
                          onClick={() => void openWaterfall(t.id)}
                          className={cn(
                            "flex w-full items-center gap-3 py-2 text-left text-sm",
                            "transition-colors hover:bg-accent/40",
                            "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                          )}
                        >
                          {!t.ok && (
                            <AlertTriangle
                              className="size-3.5 shrink-0 text-destructive"
                              aria-label="failed"
                            />
                          )}
                          <span className="w-20 shrink-0 text-muted-foreground">
                            {KIND_LABEL[t.kind] ?? t.kind}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-muted-foreground">
                            {whenFrom(t.started_at)}
                          </span>
                          <span
                            className="shrink-0"
                            style={{ fontVariantNumeric: "tabular-nums" }}
                          >
                            {formatMs(t.duration_ms)}
                          </span>
                          <span
                            className="w-20 shrink-0 text-right text-muted-foreground"
                            style={{ fontVariantNumeric: "tabular-nums" }}
                          >
                            {t.cost_usd == null ? "—" : formatUSD(Number(t.cost_usd))}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>

                <footer className="space-y-1 text-xs text-muted-foreground">
                  <p>
                    <strong className="font-medium text-foreground">
                      All costs are estimates.
                    </strong>{" "}
                    Both providers bill through accounts this app cannot see. Figures use
                    price list <code>{data.pricing_version}</code>, frozen at the moment
                    each call was recorded, so a later price change never rewrites history.
                  </p>
                  {data.data_start && (
                    <p>Recording began {whenFrom(data.data_start)}. Nothing before that exists.</p>
                  )}
                </footer>
              </>
            )}
          </div>
        )}
      </div>

      <Sheet open={openTurn != null || loadingTurn} onOpenChange={(o) => !o && setOpenTurn(null)}>
        <SheetContent title="Where the time went">
          {loadingTurn && <Skeleton className="h-40 w-full" />}
          {openTurn && (
            <div className="space-y-4 py-1">
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">What it was</dt>
                  <dd>{KIND_LABEL[openTurn.turn.kind] ?? openTurn.turn.kind}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Model</dt>
                  <dd className="text-right">{openTurn.turn.model ?? "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Tokens</dt>
                  <dd style={{ fontVariantNumeric: "tabular-nums" }}>
                    {openTurn.turn.tokens_in ?? "—"} in · {openTurn.turn.tokens_out ?? "—"} out
                    {openTurn.turn.tokens_thinking
                      ? ` · ${openTurn.turn.tokens_thinking} thinking`
                      : ""}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Estimated cost</dt>
                  <dd style={{ fontVariantNumeric: "tabular-nums" }}>
                    {openTurn.turn.cost_usd == null
                      ? "no known price"
                      : formatUSD(Number(openTurn.turn.cost_usd))}
                  </dd>
                </div>
                {!openTurn.turn.ok && (
                  <div className="flex justify-between gap-4">
                    <dt className="text-muted-foreground">Failed with</dt>
                    <dd className="text-destructive">{openTurn.turn.error_type}</dd>
                  </div>
                )}
              </dl>

              <div className="border-t border-border pt-4">
                <Waterfall spans={openTurn.spans} totalMs={openTurn.turn.duration_ms} />
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
