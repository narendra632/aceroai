import { useEffect, useState } from "react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { ScheduleFa } from "@/lib/api";
import { formatDateFull, formatQuantity, formatRupees } from "@/lib/format";

/* Schedule FA — what a foreign holding has to be declared with.
 *
 * Every resident holding a foreign security reports it, with **no minimum threshold**: one
 * fractional share is reportable, and the penalties for omitting it are severe. What the
 * return asks for, per security, is the acquisition date, the initial value, the **peak
 * value during the calendar year**, the closing value, and anything received.
 *
 * The peak is why this exists in software rather than in a spreadsheet. It is the highest
 * the holding was worth on *any* day, so it can only be known by something that recorded
 * what it was worth on every day — which the price feeds now do. Nothing here is stored;
 * this is a reading of that record.
 *
 * ⚠ Two honesty rules run through the rendering, and neither is decoration:
 *
 *   - **Coverage is shown.** A peak over 40 observed days of a 365-day year is the peak of
 *     those 40 days. Where the year is not fully covered the card says so, because a maximum
 *     over an unstated subset is a figure pretending to more authority than it has.
 *   - **The rate is named as the wrong one.** The return requires SBI's TT buying rate for
 *     the relevant date; these figures use the rate the feed recorded. Every number carries
 *     the day it came from so the right rate can be looked up. Presenting these as
 *     filing-ready would be the more convenient lie.
 */

export default function ForeignHoldings() {
  const [data, setData] = useState<ScheduleFa | null>(null);
  const [year, setYear] = useState<number | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getScheduleFa(year)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setFailed(false);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  // Absent rather than empty: a book with no foreign holding has nothing to declare, and a
  // card saying so on every visit is a card that trains its reader to skip that region.
  if (failed || !data || data.years_available.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            Foreign holdings — Schedule FA
            <InfoTip label="What Schedule FA is">
              Every Indian resident holding a foreign security declares it in
              Schedule FA of their return, with no minimum threshold — one
              fractional share counts. The period is the calendar year, not the
              financial year, which is why these figures appear nowhere else on
              this page.
            </InfoTip>
          </h2>
          <p className="text-xs text-muted-foreground">
            1 January – 31 December {data.year}
            {data.period_end < `${data.year}-12-31` ? " (so far)" : ""}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Year
          <select
            value={data.year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
          >
            {data.years_available.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      </div>

      {data.holdings.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Nothing foreign was held in {data.year}.
        </p>
      ) : (
        data.holdings.map((h) => (
          <div
            key={h.symbol}
            className="rounded-xl border border-border bg-card p-4"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-medium">
                {h.symbol}
                <span className="ml-2 font-normal text-muted-foreground">
                  {h.name}
                </span>
              </p>
              <p className="text-xs text-muted-foreground">
                acquired {formatDateFull(h.acquired_on)} ·{" "}
                {formatQuantity(h.closing_quantity)} held at the year end
              </p>
            </div>

            <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Figure label="Initial value" value={formatRupees(h.initial_inr)}>
                what was paid, charges included
              </Figure>
              <Figure
                label="Peak value"
                value={h.peak_inr ? formatRupees(h.peak_inr) : "—"}
              >
                {h.peak_on ? `highest on ${formatDateFull(h.peak_on)}` : "—"}
              </Figure>
              <Figure
                label="Closing value"
                value={h.closing_inr ? formatRupees(h.closing_inr) : "—"}
              >
                {h.closing_on ? `as at ${formatDateFull(h.closing_on)}` : "—"}
              </Figure>
              <Figure
                label="Received"
                value={formatRupees(h.gross_income_inr)}
              >
                {Number(h.gross_proceeds_inr) !== 0
                  ? `plus ${formatRupees(h.gross_proceeds_inr)} from sales`
                  : "dividends and credits"}
              </Figure>
            </dl>

            {!h.is_complete && (
              <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                Priced on {h.days_valued} of the period's {h.days_in_period}{" "}
                days, so the peak is the highest of those days rather than of
                the whole year.
              </p>
            )}
          </div>
        ))
      )}

      <p className="text-xs text-muted-foreground">
        ⚠ Converted at the rate recorded with each price, not at SBI's TT buying
        rate, which is what the return requires. Every figure names its day so
        the right rate can be looked up for it.
      </p>
    </section>
  );
}

function Figure({
  label,
  value,
  children,
}: {
  label: string;
  value: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className="text-sm font-semibold"
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </dd>
      <dd className="text-xs text-muted-foreground">{children}</dd>
    </div>
  );
}
