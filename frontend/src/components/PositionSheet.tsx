import { AlertTriangle, Clock } from "lucide-react";

import { Sheet, SheetContent } from "@/components/ui/sheet";
import { ListSkeleton } from "@/components/ui/states";
import type { HoldingDetail } from "@/lib/api";
import {
  formatDateFull,
  formatDay,
  formatPrice,
  formatQuantity,
  formatRupees,
  formatSignedPct,
} from "@/lib/format";
import {
  ASSET_LABELS,
  directionClass,
  directionGlyph,
  longTermText,
  num,
  unpricedReason,
} from "@/lib/investments";

/* One holding, in full.
 *
 * This panel exists because the columns that matter most do not fit in a row: which lots
 * are open and when each crosses into long-term, what a sale would actually realise and
 * how it splits by holding period, and — on a foreign holding — how much of the gain is
 * the asset and how much is the rupee.
 */

function Row({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-right">
        <span
          className={`text-sm font-medium tabular-nums ${className ?? ""}`}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {value}
        </span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-border pt-4 first:border-t-0 first:pt-0">
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

type Props = {
  symbol: string | null;
  detail: HoldingDetail | null;
  loading: boolean;
  onClose: () => void;
};

export default function PositionSheet({ symbol, detail, loading, onClose }: Props) {
  const holding = detail?.holding;

  return (
    <Sheet open={symbol != null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        title={holding ? `${holding.symbol} · ${holding.name}` : (symbol ?? "Holding")}
        description="Lots, holding periods, and what a sale would mean"
      >
        {loading || !detail || !holding ? (
          <ListSkeleton rows={4} />
        ) : (
          <div className="space-y-5">
            {holding.suspicious_move && (
              <div
                role="alert"
                className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
              >
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
                <p>
                  The price {holding.suspicious_move.direction}{" "}
                  <strong>{formatSignedPct(holding.suspicious_move.change, 1)}</strong> in{" "}
                  {holding.suspicious_move.gap_days} day
                  {holding.suspicious_move.gap_days === 1 ? "" : "s"} on{" "}
                  {formatDay(holding.suspicious_move.on)}. That is large for a price move —
                  check whether a <strong>split or bonus</strong> needs recording. An
                  unrecorded corporate action shows up here as a loss that never happened.
                </p>
              </div>
            )}

            <Section title="Position">
              <Row label="Held" value={formatQuantity(holding.quantity)} />
              <Row
                label="Average cost"
                value={formatPrice(holding.average_cost, holding.currency)}
                hint={holding.lots === 1 ? "one lot" : `${holding.lots} lots`}
              />
              <Row label="Invested" value={formatRupees(holding.cost_basis_inr)} />
              {holding.mark ? (
                <>
                  <Row
                    label="Last price"
                    value={formatPrice(holding.mark.price, holding.currency)}
                    hint={`${holding.mark.age_text}${holding.mark.is_stale ? " · stale" : ""} · ${holding.mark.source.toLowerCase()}`}
                  />
                  <Row label="Value" value={formatRupees(holding.market_value_inr)} />
                  <Row
                    label="Unrealised"
                    className={directionClass(holding.unrealised_inr)}
                    value={`${directionGlyph(holding.unrealised_inr)} ${formatRupees(holding.unrealised_inr)}`}
                    hint={formatSignedPct(holding.unrealised_pct) + " on cost"}
                  />
                </>
              ) : (
                <p className="mt-2 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
                  {unpricedReason(holding)} — so this holding has no value here. It is
                  excluded from the portfolio total rather than counted as zero.
                </p>
              )}
              {num(holding.realised_inr) !== 0 && (
                <Row
                  label="Realised"
                  className={directionClass(holding.realised_inr)}
                  value={formatRupees(holding.realised_inr)}
                />
              )}
              <Row label="Charges paid" value={formatRupees(holding.charges_inr)} />
              {num(holding.prepaid_tax_inr) !== 0 && (
                <Row
                  label="Tax withheld"
                  value={formatRupees(holding.prepaid_tax_inr)}
                  hint="creditable — not a cost"
                />
              )}
            </Section>

            <Section title="Lots">
              {/* Oldest first, because that is the order FIFO consumes them — the same order
                  a sale will actually relieve. */}
              <ul className="space-y-2">
                {detail.lots.map((lot, i) => (
                  <li
                    key={`${lot.trade_date}-${i}`}
                    className="rounded-lg border border-border px-3 py-2 text-sm"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium">{formatDay(lot.trade_date)}</span>
                      <span className="tabular-nums text-muted-foreground">
                        {formatQuantity(lot.quantity)} @{" "}
                        {formatPrice(lot.unit_cost, holding.currency)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                      <Clock className="size-3" />
                      {lot.long_term_on == null ? (
                        <span>never becomes long-term</span>
                      ) : lot.is_long_term ? (
                        <span className="text-emerald-700 dark:text-emerald-400">
                          long-term since {formatDateFull(lot.long_term_on)}
                        </span>
                      ) : (
                        <span>
                          {lot.days_remaining} days to long-term ·{" "}
                          {formatDateFull(lot.long_term_on)}
                        </span>
                      )}
                      <span className="ml-auto">{formatRupees(lot.cost_inr)}</span>
                    </div>
                  </li>
                ))}
              </ul>
              {holding.asset_class === "CRYPTO" && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Crypto never becomes long-term. It is taxed at a flat 30%, and under
                  s.115BBH a loss on it cannot be set against any other gain — which is why
                  it is kept out of the portfolio totals rather than netted into them.
                </p>
              )}
            </Section>

            {detail.if_sold_now && (
              <Section title="If you sold it all now">
                <Row
                  label="At"
                  value={formatPrice(detail.if_sold_now.at_price, holding.currency)}
                  hint={`${formatQuantity(detail.if_sold_now.quantity)} units`}
                />
                <Row
                  label="Realised"
                  className={directionClass(detail.if_sold_now.realised_inr)}
                  value={formatRupees(detail.if_sold_now.realised_inr)}
                />
                <Row
                  label="Long-term part"
                  value={formatRupees(detail.if_sold_now.long_term_inr)}
                />
                <Row
                  label="Short-term part"
                  value={formatRupees(detail.if_sold_now.short_term_inr)}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  {detail.if_sold_now.bases_agree ? (
                    <>
                      Selling the whole holding relieves the entire cost basis, so{" "}
                      <strong>FIFO and weighted average give the same total</strong> — your
                      broker will show this figure too. They diverge on a partial sale, where
                      which lots go first starts to matter.
                    </>
                  ) : (
                    <>
                      FIFO says {formatRupees(detail.if_sold_now.realised_inr)}; weighted
                      average says{" "}
                      {formatRupees(detail.if_sold_now.weighted_average_realised_inr)}. Tax
                      uses FIFO; broker apps display the average.
                    </>
                  )}{" "}
                  This is a gain figure, not a tax figure.
                </p>
              </Section>
            )}

            {detail.currency_split && (
              <Section title="How much of it is the rupee">
                <Row
                  label="The asset"
                  className={directionClass(detail.currency_split.local)}
                  value={formatSignedPct(detail.currency_split.local)}
                />
                <Row
                  label="The currency"
                  className={directionClass(detail.currency_split.fx)}
                  value={formatSignedPct(detail.currency_split.fx)}
                />
                <Row
                  label="Together"
                  className={directionClass(detail.currency_split.total_inr)}
                  value={formatSignedPct(detail.currency_split.total_inr)}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  Separated on purpose. Without it, a weakening rupee looks like a good
                  decision.
                </p>
              </Section>
            )}

            <Section title="Transactions">
              <ul className="space-y-1.5">
                {detail.transactions.map((t) => (
                  <li
                    key={t.id}
                    className={`flex items-baseline justify-between gap-3 text-sm ${
                      t.superseded_by_id ? "text-muted-foreground line-through" : ""
                    }`}
                  >
                    <span>
                      {t.txn_type.toLowerCase()} {formatQuantity(t.quantity)} @{" "}
                      {formatPrice(t.price, t.currency)}
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {formatDay(t.trade_date)}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>

            <Section title="Prices recorded">
              {detail.observations.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  None yet. Prices arrive with the market feed; until then this holding shows
                  what it cost and not what it is worth.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {detail.observations.map((o) => (
                    <li
                      key={`${o.observed_at}-${o.source}`}
                      className="flex items-baseline justify-between gap-3 text-sm"
                    >
                      <span className="tabular-nums">
                        {formatPrice(o.price, o.currency)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {formatDay(o.observed_at.slice(0, 10))} · {o.source.toLowerCase()}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <p className="pt-2 text-xs text-muted-foreground">
              {ASSET_LABELS[holding.asset_class]}
              {longTermText(holding) ? ` · ${longTermText(holding)}` : ""}
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
