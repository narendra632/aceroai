import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Info } from "lucide-react";

import { Button } from "@/components/ui/button";
import ServerVitals from "./ServerVitals";

import {
  Bars,
  Legend,
  Sparkline,
  StackedArea,
  type Series,
} from "@/components/ui/chart";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Waterfall } from "@/components/ui/waterfall";
import {
  USD_TO_INR,
  formatINR,
  formatMs,
  formatUSD,
  localDayKey,
} from "@/lib/format";
import * as api from "@/lib/api";
import type { InsightsOverview, TurnRow } from "@/lib/api";
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

/* Every kind of call, so the chart's total matches the headline total.
 *
 * `job` was missing until scheduled work started costing real money, and its absence was
 * the quiet kind: the stacked area simply did not draw a series it had no entry for, so the
 * chart understated spend while the tile above it did not. A chart that disagrees with the
 * number beside it is worse than no chart. */
const SERIES: Series[] = [
  { key: "chat", label: "Replies", color: "var(--series-1)" },
  { key: "embed", label: "Recall", color: "var(--series-2)" },
  { key: "memory_extract", label: "Learning", color: "var(--series-3)" },
  { key: "job", label: "Scheduled", color: "var(--series-4)" },
];

/** Recent calls shown at once. A heavy day can produce hundreds; the rest load on demand
 *  rather than making the page scroll forever. */
const TURN_PAGE = 20;

/* `caption` spells the period out in words beside the heading. The button says "30d";
 * the caption says "last 30 days". Together they answer the question the border is there
 * to raise — over what period? — without the reader having to decode an abbreviation and
 * then remember it applies to this box and not the one above. */
const RANGES = [
  { label: "7d", days: 7, caption: "last 7 days" },
  { label: "30d", days: 30, caption: "last 30 days" },
  { label: "90d", days: 90, caption: "last 90 days" },
  { label: "All", days: undefined, caption: "everything recorded" },
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
    <div className="rounded-lg border border-border/60 bg-muted/40 p-3">
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
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [openTurn, setOpenTurn] = useState<api.TurnDetail | null>(null);
  const [loadingTurn, setLoadingTurn] = useState(false);
  const [turnLimit, setTurnLimit] = useState(TURN_PAGE);
  const [loadingMoreTurns, setLoadingMoreTurns] = useState(false);
  const [moreTurns, setMoreTurns] = useState(false);

  const load = useCallback(() => {
    setStatus("loading");
    Promise.all([
      api.getInsights({ days: range.days, allTime: range.days === undefined }),
      api.listTurns(TURN_PAGE),
    ])
      .then(([overview, recent]) => {
        setData(overview);
        setTurns(recent);
        // A full page means there is probably another behind it.
        setMoreTurns(recent.length === TURN_PAGE);
        setTurnLimit(TURN_PAGE);
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
      const key = localDayKey(cursor);
      out.push({ day: key, values: byDay.get(key) ?? {} });
      cursor.setDate(cursor.getDate() + 1);
    }
    return out;
  }, [data]);

  const dailyTotals = useMemo(
    () =>
      chartData.map((d) => Object.values(d.values).reduce((a, b) => a + b, 0)),
    [chartData],
  );

  async function loadMoreTurns() {
    setLoadingMoreTurns(true);
    try {
      const next = turnLimit + TURN_PAGE;
      const rows = await api.listTurns(next);
      setTurns(rows);
      setTurnLimit(next);
      setMoreTurns(rows.length === next);
    } catch {
      setMoreTurns(false);
    } finally {
      setLoadingMoreTurns(false);
    }
  }

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
      {/* No page header here: the shell's own header names this screen. What used to be a
          title bar is now the row below, which pairs the live server readings with the
          range control — the two things this page needs above the fold. */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {/* ⚠ Two boxes, and the pair of them is the point.
            
            Each carries its own heading naming ITS OWN TIME: "Server · right now" against
            "Cost and speed · last 30 days". The range control lives inside the second one,
            on that heading line, so it is unmistakably scoped to the box it sits in.

            The alternative — one range control floating above both — is what this replaced,
            and it silently invited the reading that a disk percentage was also a 30-day
            figure. Two self-contained boxes make the distinction structural instead of
            something the reader has to infer. */}
        <ServerVitals className="mb-4" />

        {/* The period box. Rendered in EVERY state, deliberately: the range control lives
            inside it, and a control that disappears while its own data is loading is a
            control you cannot use at the one moment you want to change your mind. */}
        <section className="rounded-xl border border-border bg-card p-3 sm:p-4">
          <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-2 px-0.5">
            <h2 className="text-sm font-medium">Cost and speed</h2>
            <span className="text-xs text-muted-foreground">
              {range.caption}
            </span>
            <div className="ml-auto flex shrink-0 rounded-lg border border-border p-0.5">
              {RANGES.map((r) => (
                <button
                  key={r.label}
                  onClick={() => setRange(r)}
                  aria-pressed={range.label === r.label}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-sm transition-colors",
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

          {status === "loading" ? (
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-[5.5rem] rounded-lg" />
              ))}
            </div>
          ) : status === "error" ? (
            <ErrorState
              title="Couldn't load your usage"
              detail="This is a connection problem, not an absence of activity."
              onRetry={load}
            />
          ) : s && s.calls === 0 ? (
            <EmptyState
              icon={Activity}
              title="Nothing recorded yet"
              hint="Every model call is measured from now on. Send a message and it appears here."
            />
          ) : (
            s && (
              <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
                <Tile
                  label="Estimated spend"
                  value={formatUSD(Number(s.cost_usd))}
                  hint={
                    // Rupees at a fixed rate — a convenience, not an authoritative
                    // conversion, so it is marked approximate.
                    `≈ ${formatINR(Number(s.cost_usd))} · ` +
                    (s.unpriced > 0
                      ? `${s.unpriced} call${s.unpriced > 1 ? "s" : ""} unpriced`
                      : `${s.calls} calls`)
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
            )
          )}
        </section>

        {status === "ready" && s && s.calls > 0 && (
          <div className="mt-6 space-y-6">
            <>
              {backgroundShare > 0 && (
                <div className="flex items-start gap-3 rounded-xl border border-border bg-muted/40 p-4 text-sm">
                  <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <p className="text-muted-foreground">
                    <strong className="font-medium text-foreground">
                      {pct(backgroundShare)} of this spend is work you never see
                    </strong>{" "}
                    — recalling what Acero knows before it answers, learning
                    from the turn afterwards, and the summaries it writes on a
                    schedule.
                  </p>
                </div>
              )}

              <section className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="text-sm font-medium">Spend over time</h2>
                  <Legend series={SERIES} />
                </div>
                <StackedArea
                  data={chartData}
                  series={SERIES}
                  className="mt-3"
                />
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
                      // Marked in place rather than explained in a paragraph below.
                      tag: m.pinned ? "Fixed" : undefined,
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
                  <h2 className="text-sm font-medium">
                    Providers, side by side
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Replies only. Embeddings are excluded — they always run on a
                    fixed model.
                  </p>
                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-xs text-muted-foreground">
                          <th className="pb-2 font-medium">Provider</th>
                          <th className="pb-2 text-right font-medium">
                            Per reply
                          </th>
                          <th className="pb-2 text-right font-medium">
                            Typical
                          </th>
                          <th className="pb-2 text-right font-medium">
                            Failures
                          </th>
                        </tr>
                      </thead>
                      <tbody style={{ fontVariantNumeric: "tabular-nums" }}>
                        {data.by_provider.map((p) => (
                          <tr
                            key={p.provider}
                            className="border-t border-border"
                          >
                            <td className="py-2 capitalize">{p.provider}</td>
                            <td className="py-2 text-right">
                              {formatUSD(Number(p.cost_per_call))}
                            </td>
                            <td className="py-2 text-right">
                              {formatMs(p.p50_ms)}
                            </td>
                            <td className="py-2 text-right">
                              {pct(p.error_rate)}
                            </td>
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
                          {t.cost_usd == null
                            ? "—"
                            : formatUSD(Number(t.cost_usd))}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                {moreTurns && (
                  <div className="mt-3 text-center">
                    <Button
                      variant="outline"
                      onClick={() => void loadMoreTurns()}
                      disabled={loadingMoreTurns}
                    >
                      {loadingMoreTurns ? "Loading…" : "Load more"}
                    </Button>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Showing the {turns.length} most recent
                    </p>
                  </div>
                )}
              </section>

              <footer className="space-y-1 text-xs text-muted-foreground">
                <p>
                  <strong className="font-medium text-foreground">
                    All costs are estimates.
                  </strong>{" "}
                  Providers bill through accounts this app cannot see. Figures
                  use price list <code>{data.pricing_version}</code>, fixed at
                  the time of each call. Rupees converted at ${"₹"}
                  {USD_TO_INR} per US dollar.
                </p>
              </footer>
            </>
          </div>
        )}
      </div>

      <Sheet
        open={openTurn != null || loadingTurn}
        onOpenChange={(o) => !o && setOpenTurn(null)}
      >
        <SheetContent title="Where the time went">
          {loadingTurn && <Skeleton className="h-40 w-full" />}
          {openTurn && (
            <div className="space-y-4 py-1">
              <dl className="space-y-1.5 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">What it was</dt>
                  <dd>
                    {KIND_LABEL[openTurn.turn.kind] ?? openTurn.turn.kind}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Model</dt>
                  <dd className="text-right">{openTurn.turn.model ?? "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Tokens</dt>
                  <dd style={{ fontVariantNumeric: "tabular-nums" }}>
                    {openTurn.turn.tokens_in ?? "—"} in ·{" "}
                    {openTurn.turn.tokens_out ?? "—"} out
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
                    <dd className="text-destructive">
                      {openTurn.turn.error_type}
                    </dd>
                  </div>
                )}
              </dl>

              <div className="border-t border-border pt-4">
                <Waterfall
                  spans={openTurn.spans}
                  totalMs={openTurn.turn.duration_ms}
                />
              </div>

              {/* Shown only when memory contributed. After hybrid recall, recalling
                  nothing is a normal outcome rather than a hole in the data — an empty
                  list here would read as "we lost it". */}
              {openTurn.recalled.length > 0 && (
                <div className="border-t border-border pt-4">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">
                    {openTurn.recalled.length === 1
                      ? "1 memory used"
                      : `${openTurn.recalled.length} memories used`}
                  </p>
                  <ul className="space-y-2">
                    {openTurn.recalled.map((f) => (
                      <li key={f.id} className="text-sm leading-snug">
                        {f.fact}
                        <span className="mt-0.5 block text-[11px] text-faint">
                          {f.category}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
