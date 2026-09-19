import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Wallet } from "lucide-react";

import PositionSheet from "@/components/PositionSheet";
import TransactionEntry from "@/components/TransactionEntry";
import { Button } from "@/components/ui/button";
import { Legend, Lines, StackedBar, type Series } from "@/components/ui/chart";
import {
  EmptyState,
  ErrorState,
  ListSkeleton,
  Skeleton,
} from "@/components/ui/states";
import * as api from "@/lib/api";
import type {
  Curve,
  Holding,
  HoldingDetail,
  InvestmentSummary,
  InvestmentTransaction,
} from "@/lib/api";
import {
  formatPrice,
  formatQuantity,
  formatRupees,
  formatSignedPct,
} from "@/lib/format";
import {
  ASSET_COLORS,
  ASSET_LABELS,
  ASSET_ORDER,
  directionClass,
  directionGlyph,
  groupByAssetClass,
  longTermText,
  num,
} from "@/lib/investments";

/* The portfolio, as something you look at.
 *
 * Three rules run through every part of this screen, and they are all about honesty rather
 * than layout:
 *
 *   - **A figure that cannot be computed is named, never zeroed.** An unpriced holding
 *     shows no value and says why; a total that excludes holdings lists them right beside
 *     it, at the same size — a caveat below the fold is a caveat nobody reads.
 *   - **Crypto sits apart.** Under s.115BBH its losses offset nothing, so netting it into
 *     one portfolio figure would show a position the tax code does not permit.
 *   - **Nothing is interpolated.** The value line exists only on days where every holding
 *     had an observed price, and the chart states the range it covers.
 */

const RANGES = [
  { key: "3m", label: "3M", days: 90 },
  { key: "6m", label: "6M", days: 182 },
  { key: "1y", label: "1Y", days: 365 },
  { key: "all", label: "All", days: null },
] as const;

const CURVE_SERIES: Series[] = [
  { key: "invested", label: "Invested", color: "var(--series-2)" },
  { key: "value", label: "Value", color: "var(--series-1)" },
];

type SortKey = "symbol" | "cost" | "value" | "gain";

/** What the chart says about its own coverage.
 *
 *  ⚠ Reports the COUNT of valued days, not just the first and last. Coverage can have a
 *  hole in the middle — buy something and leave it unpriced for a week — and naming only
 *  the endpoints would claim a continuity the data does not have. */
function curveNote(curve: Curve | null): string {
  if (!curve || curve.covered_days === 0) {
    return "Only the invested line so far. Value history starts once prices are recorded, which arrives with the market feed — nothing here is guessed in the meantime.";
  }
  if (curve.covered_days === curve.total_days) {
    return "Value is known for every day shown, from recorded prices.";
  }
  return `Value is known for ${curve.covered_days} of these ${curve.total_days} days, between ${curve.covered_from} and ${curve.covered_to}. The gaps are days when a holding had no recorded price, and nothing is drawn across them.`;
}

function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: string;
  hint?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={`mt-1 text-xl font-semibold ${className ?? ""}`}
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </p>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

/** A sortable column header.
 *
 *  ⚠ Declared at module scope, not inside the view. A component defined inside another
 *  component is a new type on every render, so React remounts it — and this one contains
 *  the button you just pressed, which would lose focus on every sort. That breaks sorting
 *  by keyboard completely, and silently.
 *
 *  ⚠ `align` maps to whole class names rather than being interpolated. Tailwind extracts
 *  classes by scanning source text, so `text-${align}` produces no CSS at all.
 */
function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "right",
}: {
  label: string;
  sortKey: SortKey;
  sort: { key: SortKey; desc: boolean };
  onSort: (next: { key: SortKey; desc: boolean }) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  return (
    <th
      scope="col"
      className={`px-3 py-2 font-medium ${align === "left" ? "text-left" : "text-right"}`}
      aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
    >
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-foreground"
        onClick={() =>
          onSort({ key: sortKey, desc: active ? !sort.desc : true })
        }
      >
        {label}
        <span aria-hidden className={active ? "" : "opacity-0"}>
          {sort.desc ? "▾" : "▴"}
        </span>
      </button>
    </th>
  );
}

export default function InvestmentsView() {
  const [summary, setSummary] = useState<InvestmentSummary | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [transactions, setTransactions] = useState<InvestmentTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("all");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "value",
    desc: true,
  });
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [detail, setDetail] = useState<HoldingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const since = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days;
    if (!days) return undefined;
    const d = new Date();
    d.setDate(d.getDate() - days);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }, [range]);

  /* Two loaders, not one, because these have different lifetimes.
   *
   * Changing the time range is a question about the chart alone — it must not refetch the
   * holdings and re-run the fold. Recording a transaction changes both, so that path calls
   * `load()`. Collapsing them into one function is the version that looks simpler and makes
   * every range click reload the whole portfolio. */
  const loadBook = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        api.getInvestmentSummary(),
        api.listInvestmentTransactions(),
      ]);
      setSummary(s);
      setTransactions(t);
      setFailed(false);
    } catch {
      // ⚠ Never rendered as an empty portfolio. "We couldn't load this" and "you own
      // nothing" must never look the same.
      setFailed(true);
    }
  }, []);

  const loadCurve = useCallback(async () => {
    try {
      setCurve(await api.getInvestmentHistory(since));
    } catch {
      // The chart failing is not the portfolio failing. Leave the last curve up rather
      // than blanking a page whose holdings loaded perfectly well.
      setCurve(null);
    }
  }, [since]);

  const load = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadBook(), loadCurve()]);
    setLoading(false);
  }, [loadBook, loadCurve]);

  // Two effects, so the range control genuinely only touches the chart. `loadBook` has no
  // dependencies and so runs once; `loadCurve` changes with the range and so runs again.
  useEffect(() => {
    void loadBook().finally(() => setLoading(false));
  }, [loadBook]);

  useEffect(() => {
    void loadCurve();
  }, [loadCurve]);

  useEffect(() => {
    if (!openSymbol) return;
    setDetailLoading(true);
    setDetail(null);
    api
      .getHolding(openSymbol)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [openSymbol]);

  if (loading && !summary) {
    return (
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="mx-auto max-w-5xl space-y-4 p-4">
            <div className="grid gap-3 sm:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
            <ListSkeleton rows={5} />
          </div>
        </div>
      </div>
    );
  }

  if (failed || !summary) {
    return (
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="mx-auto max-w-5xl p-4">
            <ErrorState
              title="Couldn't load your portfolio"
              detail="If this is a fresh database, the book has not been seeded yet — run app.scripts.seed_investments."
              onRetry={() => void load()}
            />
          </div>
        </div>
      </div>
    );
  }

  const { totals, holdings } = summary;
  const priced = holdings.filter((h) => h.market_value_inr != null);
  const unpriced = holdings.filter((h) => h.market_value_inr == null);

  /* ⚠ Values come from `by_asset_class`, computed on the server. Summing holdings here to
     get a subtotal would be float arithmetic on money — the exact thing the string-typed
     API exists to prevent. `num()` below converts only for segment WIDTH. */
  const byClass = new Map(
    summary.by_asset_class.map((a) => [a.asset_class, a]),
  );
  const allocation = ASSET_ORDER.flatMap((cls) => {
    const total = byClass.get(cls);
    if (!total?.market_value_inr) return [];
    return [
      {
        key: cls,
        label: ASSET_LABELS[cls],
        value: num(total.market_value_inr),
        display: formatRupees(total.market_value_inr),
        color: ASSET_COLORS[cls],
      },
    ];
  }).filter((s) => s.value > 0);
  const allocationTotal = allocation.reduce((sum, a) => sum + a.value, 0);

  const curvePoints =
    curve?.points.map((p) => ({
      day: p.day,
      values: {
        invested: num(p.invested_inr),
        value: p.value_inr == null ? null : num(p.value_inr),
      },
    })) ?? [];

  function sortRows(rows: Holding[]): Holding[] {
    const key = sort.key;
    const value = (h: Holding) =>
      key === "symbol"
        ? h.symbol
        : key === "cost"
          ? num(h.cost_basis_inr)
          : key === "value"
            ? num(h.market_value_inr)
            : num(h.unrealised_inr);
    return [...rows].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      const cmp =
        typeof av === "string"
          ? av.localeCompare(bv as string)
          : av - (bv as number);
      return sort.desc ? -cmp : cmp;
    });
  }

  return (
    /* ⚠ A two-layer wrapper, not one — and the layer split is the actual fix.
     *
     * The first attempt here was a single `flex-1 overflow-y-auto` div, which matches
     * Tasks/Journal/Settings and LOOKS complete: the sidebar lives outside this component,
     * so a view with no scroll region of its own grows the whole shell instead of scrolling
     * internally, dragging the sidebar up with it. That diagnosis was right; the fix was
     * incomplete. `overflow-y-auto` alone only clips content ONCE the box already has a
     * fixed height — it does not by itself stop a flex item's content from demanding more
     * height than its share of the row in the first place, and a box with several grid
     * sections, an SVG chart and a table is exactly the content shape that can. The result
     * was two scrollbars at once: the browser's own (because the shell genuinely grew) and
     * this div's (because it was ALSO, separately, an auto-overflow box).
     *
     * `MessageList.tsx` — the one part of this app whose content is the most unpredictable
     * (streamed, variable height, arrives while the user is reading) — already solved this
     * with `overflow-hidden` on the sizing layer and `h-full overflow-y-auto` on the
     * scrolling layer underneath it. `overflow-hidden` is a hard clip: the outer div is
     * forced to the height flexbox actually gave it, full stop, whatever its content wants.
     * The inner `h-full` then just fills that guaranteed space and scrolls within it. Copied
     * here rather than reinvented, because it is the pattern this codebase has already
     * proven against the least forgiving content on the page. */
    <div className="flex-1 overflow-hidden">
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-8 p-4 pb-16">
          {/* --- what it is worth ------------------------------------------------------- */}
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {/* ⚠ `cost_basis_inr`, not `invested_inr`. The latter counts only priced,
            non-ring-fenced holdings so it stays comparable with market value — which
            makes it ZERO on a book with no prices. Running the page for the first time
            is what caught it. */}
            <Stat
              label="Invested"
              value={formatRupees(totals.cost_basis_inr)}
            />
            <Stat
              label="Current value"
              value={
                totals.is_complete ? formatRupees(totals.market_value_inr) : "—"
              }
              hint={
                totals.is_complete
                  ? undefined
                  : `waiting on ${totals.unpriced.length} price${totals.unpriced.length === 1 ? "" : "s"}`
              }
            />
            <Stat
              label="Unrealised"
              value={
                totals.is_complete
                  ? `${directionGlyph(totals.unrealised_inr)} ${formatRupees(totals.unrealised_inr)}`
                  : "—"
              }
              className={
                totals.is_complete
                  ? directionClass(totals.unrealised_inr)
                  : undefined
              }
              hint={
                totals.is_complete
                  ? formatSignedPct(totals.unrealised_pct)
                  : undefined
              }
            />
            <Stat
              label="Realised"
              value={formatRupees(totals.realised_inr)}
              className={directionClass(totals.realised_inr)}
            />
          </section>

          {unpriced.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm font-medium">
                {unpriced.length} of {holdings.length} holdings have no price
                yet
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                They are excluded from the totals above rather than counted as
                zero, so those figures cover only part of the book. Prices
                arrive with the market feed.
              </p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {unpriced.map((h) => (
                  <li
                    key={h.symbol}
                    className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                  >
                    {h.symbol}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {num(totals.ring_fenced_inr) !== 0 && (
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm">
                <span className="font-medium">Crypto, separately:</span>{" "}
                <span className={directionClass(totals.ring_fenced_inr)}>
                  {formatRupees(totals.ring_fenced_inr)}
                </span>{" "}
                unrealised.
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Kept out of the figures above on purpose. Under s.115BBH a
                crypto loss cannot be set against any other gain — not even a
                different crypto gain, not in a later year — so a single netted
                number would show a position the tax code does not allow.
              </p>
            </div>
          )}

          {/* --- return ---------------------------------------------------------------- */}
          <section className="grid gap-3 sm:grid-cols-2">
            {summary.returns.map((r) => (
              <div
                key={r.kind}
                className="rounded-xl border border-border bg-card p-4"
              >
                <p className="text-xs text-muted-foreground">
                  {r.label} · {r.measures}
                </p>
                {r.value != null ? (
                  <p
                    className={`mt-1 text-xl font-semibold ${directionClass(r.value)}`}
                    style={{ fontVariantNumeric: "tabular-nums" }}
                  >
                    {formatSignedPct(r.value)}
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Not available — {r.unavailable_because}.
                  </p>
                )}
              </div>
            ))}
          </section>

          {/* --- allocation ------------------------------------------------------------ */}
          {allocation.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">Where the money is</h2>
              <StackedBar
                segments={allocation}
                format={(n) => formatRupees(String(n))}
              />
              <Legend
                series={allocation.map((s) => ({
                  key: s.key,
                  label: s.label,
                  color: s.color,
                }))}
              />
              {allocation.some((a) => a.key === "CRYPTO") && (
                <p className="text-xs text-muted-foreground">
                  ⚠ This includes crypto, which the totals above keep separate.
                  Both are right: you are exposed to it, so it belongs in a
                  picture of where the money is — but its gains and losses
                  cannot be netted against anything else, so it stays out of a
                  single portfolio figure. Adding these segments up will not
                  give you the number at the top of the page.
                </p>
              )}
              <ul className="space-y-1.5">
                {[...priced]
                  .sort(
                    (a, b) => num(b.market_value_inr) - num(a.market_value_inr),
                  )
                  .map((h) => (
                    <li
                      key={h.symbol}
                      className="flex items-center gap-3 text-sm"
                    >
                      <span className="w-24 shrink-0 font-medium">
                        {h.symbol}
                      </span>
                      <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                        <span
                          className="block h-full rounded-full"
                          style={{
                            width: `${(num(h.market_value_inr) / allocationTotal) * 100}%`,
                            background: ASSET_COLORS[h.asset_class],
                          }}
                        />
                      </span>
                      <span className="w-24 shrink-0 text-right tabular-nums text-muted-foreground">
                        {formatRupees(h.market_value_inr)}
                      </span>
                    </li>
                  ))}
              </ul>
              {unpriced.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Not shown, because they cannot be valued:{" "}
                  {unpriced.map((h) => h.symbol).join(", ")} — together{" "}
                  {formatRupees(summary.unpriced_cost_inr)} at cost.
                </p>
              )}
            </section>
          )}

          {/* --- over time ------------------------------------------------------------- */}
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">Over time</h2>
              <div className="flex gap-1" role="group" aria-label="Time range">
                {RANGES.map((r) => (
                  <Button
                    key={r.key}
                    size="sm"
                    variant={range === r.key ? "secondary" : "ghost"}
                    onClick={() => setRange(r.key)}
                    aria-pressed={range === r.key}
                  >
                    {r.label}
                  </Button>
                ))}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              {curvePoints.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  Nothing to plot yet — the lines start at your first
                  transaction.
                </p>
              ) : (
                <>
                  <Lines
                    data={curvePoints}
                    series={CURVE_SERIES}
                    format={(n) => formatRupees(String(n))}
                    note={curveNote(curve)}
                  />
                  <Legend series={CURVE_SERIES} className="mt-3" />
                </>
              )}
            </div>
          </section>

          {/* --- holdings -------------------------------------------------------------- */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold">Holdings</h2>
            {holdings.length === 0 ? (
              <EmptyState
                icon={Wallet}
                title="Nothing in this book yet"
                hint="Record a transaction below, or tell Acero in chat — both write to the same ledger."
              />
            ) : (
              <>
                {/* Table on a real screen. */}
                <div className="hidden overflow-hidden rounded-xl border border-border md:block">
                  <table className="w-full text-sm">
                    <caption className="sr-only">
                      Holdings, grouped by asset class, with cost, value and
                      unrealised gain
                    </caption>
                    <thead className="bg-muted/50 text-xs text-muted-foreground">
                      <tr>
                        <SortHeader
                          label="Holding"
                          sortKey="symbol"
                          sort={sort}
                          onSort={setSort}
                          align="left"
                        />
                        <th
                          scope="col"
                          className="px-3 py-2 text-right font-medium"
                        >
                          Qty
                        </th>
                        <th
                          scope="col"
                          className="px-3 py-2 text-right font-medium"
                        >
                          Last price
                        </th>
                        <SortHeader
                          label="Invested"
                          sortKey="cost"
                          sort={sort}
                          onSort={setSort}
                        />
                        <SortHeader
                          label="Value"
                          sortKey="value"
                          sort={sort}
                          onSort={setSort}
                        />
                        <SortHeader
                          label="Unrealised"
                          sortKey="gain"
                          sort={sort}
                          onSort={setSort}
                        />
                      </tr>
                    </thead>
                    {groupByAssetClass(holdings).map(([cls, rows]) => (
                      <tbody key={cls} className="border-t border-border">
                        <tr>
                          <th
                            scope="colgroup"
                            colSpan={6}
                            className="bg-muted/30 px-3 py-1.5 text-left text-xs font-semibold"
                          >
                            {ASSET_LABELS[cls]}
                            <span className="ml-2 font-normal text-muted-foreground">
                              {formatRupees(byClass.get(cls)?.invested_inr)}{" "}
                              invested
                            </span>
                          </th>
                        </tr>
                        {sortRows(rows).map((h) => (
                          <tr
                            key={h.symbol}
                            className="cursor-pointer border-t border-border hover:bg-accent/40"
                            onClick={() => setOpenSymbol(h.symbol)}
                          >
                            <th
                              scope="row"
                              className="px-3 py-2.5 text-left font-medium"
                            >
                              <button
                                type="button"
                                className="text-left hover:underline"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenSymbol(h.symbol);
                                }}
                              >
                                {h.symbol}
                              </button>
                              <span className="block text-xs font-normal text-muted-foreground">
                                {longTermText(h) ?? "no long-term boundary"}
                              </span>
                              {h.suspicious_move && (
                                <span className="mt-0.5 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                                  <AlertTriangle className="size-3" />
                                  possible unrecorded split
                                </span>
                              )}
                            </th>
                            <td className="px-3 py-2.5 text-right tabular-nums">
                              {formatQuantity(h.quantity)}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums">
                              {h.mark ? (
                                <>
                                  {formatPrice(h.mark.price, h.currency)}
                                  <span className="block text-xs text-muted-foreground">
                                    {h.mark.age_text}
                                    {h.mark.is_stale ? " · stale" : ""}
                                  </span>
                                </>
                              ) : (
                                <span className="text-xs text-muted-foreground">
                                  no price yet
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums">
                              {formatRupees(h.cost_basis_inr)}
                            </td>
                            <td className="px-3 py-2.5 text-right tabular-nums">
                              {h.market_value_inr
                                ? formatRupees(h.market_value_inr)
                                : "—"}
                            </td>
                            <td
                              className={`px-3 py-2.5 text-right tabular-nums ${directionClass(h.unrealised_inr)}`}
                            >
                              {h.unrealised_inr ? (
                                <>
                                  {directionGlyph(h.unrealised_inr)}{" "}
                                  {formatRupees(h.unrealised_inr)}
                                  <span className="block text-xs">
                                    {formatSignedPct(h.unrealised_pct)}
                                  </span>
                                </>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    ))}
                  </table>
                </div>

                {/* Cards on a phone. ⚠ Not a horizontally scrolling table — that hides the
                columns that matter behind a gesture nobody performs, on the device this
                app is installed on. */}
                <ul className="space-y-2 md:hidden">
                  {sortRows(holdings).map((h) => (
                    <li key={h.symbol}>
                      <button
                        type="button"
                        onClick={() => setOpenSymbol(h.symbol)}
                        className="w-full rounded-xl border border-border bg-card p-3 text-left"
                      >
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="font-medium">{h.symbol}</span>
                          <span className="tabular-nums">
                            {h.market_value_inr
                              ? formatRupees(h.market_value_inr)
                              : formatRupees(h.cost_basis_inr)}
                          </span>
                        </div>
                        <div className="mt-1 flex items-baseline justify-between gap-3 text-xs">
                          <span className="text-muted-foreground">
                            {formatQuantity(h.quantity)} ·{" "}
                            {ASSET_LABELS[h.asset_class]}
                          </span>
                          <span className={directionClass(h.unrealised_inr)}>
                            {h.unrealised_inr
                              ? `${directionGlyph(h.unrealised_inr)} ${formatSignedPct(h.unrealised_pct)}`
                              : "at cost — no price yet"}
                          </span>
                        </div>
                        {h.suspicious_move && (
                          <p className="mt-1 flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400">
                            <AlertTriangle className="size-3" /> possible
                            unrecorded split
                          </p>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <TransactionEntry
            transactions={transactions}
            loading={loading}
            onChanged={() => void load()}
          />

          <PositionSheet
            symbol={openSymbol}
            detail={detail}
            loading={detailLoading}
            onClose={() => setOpenSymbol(null)}
          />
        </div>
      </div>
    </div>
  );
}
