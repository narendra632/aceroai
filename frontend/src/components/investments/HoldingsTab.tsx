import { AlertTriangle, LineChart, Wallet } from "lucide-react";

import CorporateActions from "@/components/CorporateActions";
import { InfoTip } from "@/components/InfoTip";
import { RANGES, type RangeKey, type SortKey } from "@/components/investments/holdings";
import { Callout, Chip, Section } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import { Lines, StackedBar, Legend, type Series } from "@/components/ui/chart";
import { EmptyState } from "@/components/ui/states";
import type { Curve, Holding, InvestmentSummary } from "@/lib/api";
import {
  formatDateFull,
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
  sourceLabel,
} from "@/lib/investments";
import { cn } from "@/lib/utils";

/* What you own and what it is worth — the tab opened most days.
 *
 * ⚠ One summary card, not seven blocks. The first version gave invested, value, unrealised and
 * realised a card each, then crypto its own card, then each return its own card, then the
 * allocation its own section with a per-holding bar list that repeated the table below it. A
 * daily glance had to read seven boxes to learn one thing — what is it worth — and the one
 * number that mattered was the same size as the other six.
 *
 * Three honesty rules survive the redesign unchanged, because they are about the numbers:
 *
 *   - **A figure that cannot be computed is named, never zeroed.** An unpriced holding shows no
 *     value and says why, and a total that excludes holdings lists them beside it.
 *   - **Crypto sits apart.** Under s.115BBH its losses offset nothing, so it is counted in the
 *     book but never netted into a single gain.
 *   - **Nothing is interpolated.** The value line exists only on days every holding had an
 *     observed price, and the chart states the range it covers.
 */

const CURVE_SERIES: Series[] = [
  { key: "invested", label: "Invested", color: "var(--series-2)" },
  { key: "value", label: "Value", color: "var(--series-1)" },
];

/** What the chart says about its own coverage.
 *
 *  ⚠ Reports the COUNT of valued days, not just the first and last. Coverage can have a hole
 *  in the middle — buy something and leave it unpriced for a week — and naming only the
 *  endpoints would claim a continuity the data does not have. */
function curveNote(curve: Curve | null): string {
  if (!curve || curve.covered_days === 0) {
    return "Only the invested line so far — value history starts once prices are recorded.";
  }
  if (curve.covered_days === curve.total_days) {
    return "Value is known for every day shown, from recorded prices.";
  }
  return `Value is known for ${curve.covered_days} of these ${curve.total_days} days, between ${curve.covered_from} and ${curve.covered_to}; nothing is drawn across the gaps.`;
}

/** A sortable column header.
 *
 *  ⚠ Declared at module scope, not inside the view. A component defined inside another is a
 *  new type on every render, so React remounts it — and this one contains the button you just
 *  pressed, which would lose focus on every sort and break sorting by keyboard.
 *
 *  ⚠ `align` maps to whole class names rather than being interpolated. Tailwind extracts
 *  classes by scanning source text, so `text-${align}` produces no CSS at all. */
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
        onClick={() => onSort({ key: sortKey, desc: active ? !sort.desc : true })}
      >
        {label}
        <span aria-hidden className={active ? "" : "opacity-0"}>
          {sort.desc ? "▾" : "▴"}
        </span>
      </button>
    </th>
  );
}

/** A holding's share of what could be valued, as a thin bar and a percentage.
 *
 *  ⚠ A share of the PRICED whole. The division is for a width and a rounded percentage only —
 *  nothing here is money, which always arrives from the server as an exact string. */
function Weight({ share, color }: { share: number | null; color: string }) {
  if (share == null) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="relative hidden h-1.5 w-14 overflow-hidden rounded-full bg-muted lg:block">
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${Math.max(share * 100, 1.5)}%`, background: color }}
        />
      </span>
      <span className="w-9 text-right tabular-nums">{Math.round(share * 100)}%</span>
    </span>
  );
}

function Warning({ holding: h }: { holding: Holding }) {
  // An ANNOUNCED action outranks a guessed one: it says the same thing with a source behind it.
  if (h.open_action) {
    return (
      <Chip tone="caution" icon={AlertTriangle} className="mt-1">
        {h.open_action.ratio_text ?? "action"} pending
      </Chip>
    );
  }
  if (h.suspicious_move) {
    return (
      <Chip tone="caution" icon={AlertTriangle} className="mt-1">
        possible unrecorded split
      </Chip>
    );
  }
  return null;
}

export default function HoldingsTab({
  summary,
  curve,
  range,
  onRange,
  sort,
  onSort,
  onOpen,
  onChanged,
}: {
  summary: InvestmentSummary;
  curve: Curve | null;
  range: RangeKey;
  onRange: (next: RangeKey) => void;
  sort: { key: SortKey; desc: boolean };
  onSort: (next: { key: SortKey; desc: boolean }) => void;
  onOpen: (symbol: string) => void;
  onChanged: () => void;
}) {
  const { totals, holdings } = summary;
  const unpriced = holdings.filter((h) => h.market_value_inr == null);

  /* ⚠ Values come from `by_asset_class`, computed on the server. Summing holdings here to get
     a subtotal would be float arithmetic on money — the exact thing the string-typed API
     exists to prevent. `num()` below converts only for widths and a rounded share. */
  const byClass = new Map(summary.by_asset_class.map((a) => [a.asset_class, a]));
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
  const pricedTotal = allocation.reduce((sum, a) => sum + a.value, 0);
  const shareOf = (h: Holding) =>
    h.market_value_inr == null || pricedTotal <= 0 ? null : num(h.market_value_inr) / pricedTotal;
  const crypto = byClass.get("CRYPTO");

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
      const cmp = typeof av === "string" ? av.localeCompare(bv as string) : av - (bv as number);
      return sort.desc ? -cmp : cmp;
    });
  }

  return (
    <div className="space-y-4">
      {/* ⚠ Above the figures on purpose. An announced split the ledger does not know about
          makes every figure below this point wrong for that holding — by half, in the worst
          case — so the explanation has to be read first. */}
      <CorporateActions actions={summary.corporate_actions} onChange={onChanged} />

      {unpriced.length > 0 && (
        <Callout
          tone="caution"
          title={`${unpriced.length} of ${holdings.length} holdings have no price yet`}
        >
          They are left out of the totals rather than counted as zero:{" "}
          {unpriced.map((h) => h.symbol).join(", ")} — {formatRupees(summary.unpriced_cost_inr)}{" "}
          at cost.
        </Callout>
      )}

      {/* --- the summary -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
        <div className="grid gap-5 md:grid-cols-[1.2fr_1fr]">
          <div>
            <p className="text-xs text-muted-foreground">What it is worth today</p>
            {/* ⚠ `*_all_*`: the whole book, crypto included. The other totals exclude
                ring-fenced holdings so they stay comparable with each other — and pairing one
                of those with "Invested", which counts everything, reported a GAIN on a book
                that was down. */}
            <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">
              {totals.is_complete ? formatRupees(totals.market_value_all_inr) : "—"}
            </p>
            {totals.is_complete ? (
              <p
                className={cn(
                  "mt-1 text-sm font-medium tabular-nums",
                  directionClass(totals.unrealised_all_inr),
                )}
              >
                {directionGlyph(totals.unrealised_all_inr)}{" "}
                {formatRupees(totals.unrealised_all_inr)} (
                {formatSignedPct(totals.unrealised_all_pct)})
                <span className="font-normal text-muted-foreground"> on paper</span>
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                waiting on {totals.unpriced.length} price
                {totals.unpriced.length === 1 ? "" : "s"}
              </p>
            )}
            {/* ⚠ `cost_basis_inr`, not `invested_inr`. The latter counts only priced,
                non-ring-fenced holdings so it stays comparable with market value — which makes
                it ZERO on a book with no prices. */}
            <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">Put in</dt>
                <dd className="font-medium tabular-nums">{formatRupees(totals.cost_basis_inr)}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Taken out as gain</dt>
                <dd className={cn("font-medium tabular-nums", directionClass(totals.realised_inr))}>
                  {formatRupees(totals.realised_inr)}
                </dd>
              </div>
              {num(totals.ring_fenced_inr) !== 0 && crypto && (
                <div>
                  <dt className="flex items-center gap-1 text-xs text-muted-foreground">
                    Crypto, kept apart
                    <InfoTip label="Why crypto is kept apart">
                      A crypto loss can be set against nothing else under s.115BBH, so it is
                      counted in what you own but never netted into one gain.
                    </InfoTip>
                  </dt>
                  <dd className="font-medium tabular-nums">
                    {crypto.market_value_inr ? formatRupees(crypto.market_value_inr) : "unpriced"}
                    <span className={cn("ml-1.5 text-xs", directionClass(totals.ring_fenced_inr))}>
                      {directionGlyph(totals.ring_fenced_inr)}{" "}
                      {formatRupees(totals.ring_fenced_inr)}
                    </span>
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* ⚠ What each return IS stays on the card: one is per year and the other a total
              over a window, and two bare percentages invite being read as the same kind of
              number. Only the elaboration hides behind the "i". */}
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-1">
            {summary.returns.map((r) => (
              <div key={r.kind} className="rounded-lg bg-muted/40 p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {r.kind === "money_weighted" ? (
                      <>Your money, per year</>
                    ) : (
                      <>
                        Your picks,{" "}
                        {r.covers_from
                          ? `12 months to ${formatDateFull(r.covers_to ?? r.covers_from)}`
                          : "over the period"}
                      </>
                    )}
                    <span className="text-faint"> · {r.label}</span>
                  </p>
                  {r.explanation && (
                    <InfoTip label={`What ${r.label} means`}>{r.explanation}</InfoTip>
                  )}
                </div>
                {r.value != null ? (
                  <>
                    <p
                      className={cn(
                        "mt-1 text-lg font-semibold tabular-nums",
                        directionClass(r.value),
                      )}
                    >
                      {formatSignedPct(r.value)}
                    </p>
                    {r.headline && (
                      <p className="text-xs text-muted-foreground">{r.headline}</p>
                    )}
                  </>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Not available — {r.unavailable_because}.
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>

        {allocation.length > 0 && (
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs font-medium">Where the money is</p>
              {allocation.some((a) => a.key === "CRYPTO") && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  includes crypto
                  <InfoTip label="Why this includes crypto">
                    You are exposed to it, so it belongs in a picture of where the money is —
                    which is why these segments do not add up to a single netted gain.
                  </InfoTip>
                </span>
              )}
            </div>
            <StackedBar segments={allocation} format={(n) => formatRupees(String(n))} />
            <Legend
              className="mt-2"
              series={allocation.map((s) => ({
                key: s.key,
                label: `${s.label} ${s.display}`,
                color: s.color,
              }))}
            />
          </div>
        )}
      </section>

      {/* --- the holdings --------------------------------------------------------------- */}
      <Section
        icon={Wallet}
        title="Holdings"
        summary={`${holdings.length} held · tap one for its lots, prices and tax dates`}
        collapsible={false}
        flush
      >
        {holdings.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title="Nothing in this book yet"
            hint="Record a transaction in Records, or tell Acero in chat — both write to the same ledger."
          />
        ) : (
          <>
            <div className="hidden md:block">
              <table className="w-full text-sm">
                <caption className="sr-only">
                  Holdings, grouped by asset class, with cost, value, share and unrealised gain
                </caption>
                <thead className="bg-muted/40 text-xs text-muted-foreground">
                  <tr>
                    <SortHeader label="Holding" sortKey="symbol" sort={sort} onSort={onSort} align="left" />
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Last price
                    </th>
                    <SortHeader label="Put in" sortKey="cost" sort={sort} onSort={onSort} />
                    <SortHeader label="Worth" sortKey="value" sort={sort} onSort={onSort} />
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Share
                    </th>
                    <SortHeader label="Gain" sortKey="gain" sort={sort} onSort={onSort} />
                  </tr>
                </thead>
                {groupByAssetClass(holdings).map(([cls, rows]) => (
                  <tbody key={cls} className="border-t border-border">
                    <tr>
                      <th
                        scope="colgroup"
                        colSpan={6}
                        className="bg-muted/20 px-3 py-1.5 text-left text-xs font-semibold"
                      >
                        <span
                          aria-hidden="true"
                          className="mr-2 inline-block size-2 rounded-full align-middle"
                          style={{ background: ASSET_COLORS[cls] }}
                        />
                        {ASSET_LABELS[cls]}
                        <span className="ml-2 font-normal text-muted-foreground">
                          {formatRupees(byClass.get(cls)?.invested_inr)} put in
                        </span>
                      </th>
                    </tr>
                    {sortRows(rows).map((h) => (
                      <tr
                        key={h.symbol}
                        className="cursor-pointer border-t border-border hover:bg-accent/40"
                        onClick={() => onOpen(h.symbol)}
                      >
                        <th scope="row" className="px-3 py-2.5 text-left font-medium">
                          <button
                            type="button"
                            className="text-left hover:underline"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpen(h.symbol);
                            }}
                          >
                            {h.symbol}
                          </button>
                          <span className="block text-xs font-normal text-muted-foreground">
                            {formatQuantity(h.quantity)} ·{" "}
                            {longTermText(h) ?? "no long-term boundary"}
                          </span>
                          <Warning holding={h} />
                        </th>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {h.mark ? (
                            <>
                              {formatPrice(h.mark.price, h.currency)}
                              <span
                                className={cn(
                                  "block text-xs",
                                  h.mark.is_stale ? "text-caution" : "text-muted-foreground",
                                )}
                                title={`Price from ${sourceLabel(h.mark.source)}`}
                              >
                                {h.mark.age_text}
                                {h.mark.is_stale ? " · stale" : ""}
                              </span>
                            </>
                          ) : (
                            <span className="text-xs text-muted-foreground">no price yet</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {formatRupees(h.cost_basis_inr)}
                        </td>
                        <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                          {h.market_value_inr ? formatRupees(h.market_value_inr) : "—"}
                        </td>
                        <td className="px-3 py-2.5 text-right text-xs text-muted-foreground">
                          <Weight share={shareOf(h)} color={ASSET_COLORS[h.asset_class]} />
                        </td>
                        <td
                          className={cn(
                            "px-3 py-2.5 text-right tabular-nums",
                            directionClass(h.unrealised_inr),
                          )}
                        >
                          {h.unrealised_inr ? (
                            <>
                              {directionGlyph(h.unrealised_inr)} {formatRupees(h.unrealised_inr)}
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

            {/* Cards on a phone. ⚠ Not a horizontally scrolling table — that hides the columns
                that matter behind a gesture nobody performs, on the device this app is
                installed on. */}
            <ul className="divide-y divide-border md:hidden">
              {sortRows(holdings).map((h) => (
                <li key={h.symbol}>
                  <button
                    type="button"
                    onClick={() => onOpen(h.symbol)}
                    className="w-full px-3 py-3 text-left hover:bg-accent/40"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="flex items-center gap-2 font-medium">
                        <span
                          aria-hidden="true"
                          className="inline-block size-2 rounded-full"
                          style={{ background: ASSET_COLORS[h.asset_class] }}
                        />
                        {h.symbol}
                      </span>
                      <span className="font-medium tabular-nums">
                        {h.market_value_inr
                          ? formatRupees(h.market_value_inr)
                          : formatRupees(h.cost_basis_inr)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-baseline justify-between gap-3 text-xs">
                      <span className="text-muted-foreground">
                        {formatQuantity(h.quantity)} · {ASSET_LABELS[h.asset_class]}
                        {shareOf(h) != null && ` · ${Math.round((shareOf(h) ?? 0) * 100)}%`}
                      </span>
                      <span className={directionClass(h.unrealised_inr)}>
                        {h.unrealised_inr
                          ? `${directionGlyph(h.unrealised_inr)} ${formatSignedPct(h.unrealised_pct)}`
                          : "at cost — no price yet"}
                      </span>
                    </div>
                    <Warning holding={h} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {/* --- over time -------------------------------------------------------------------- */}
      <Section
        icon={LineChart}
        memory="holdings.chart"
        title="Over time"
        summary="What you put in, against what it was worth"
        actions={
          <div className="flex gap-0.5" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <Button
                key={r.key}
                size="xs"
                variant={range === r.key ? "secondary" : "ghost"}
                onClick={() => onRange(r.key)}
                aria-pressed={range === r.key}
              >
                {r.label}
              </Button>
            ))}
          </div>
        }
      >
        {curvePoints.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Nothing to plot yet — the lines start at your first transaction.
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
      </Section>
    </div>
  );
}
