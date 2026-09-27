import { useEffect, useState } from "react";
import { Globe } from "lucide-react";

import { Callout, Section } from "@/components/investments/kit";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
 *   - **Coverage is shown, against the days HELD.** A peak over 40 observed days is the peak
 *     of those 40 days, and the card says so. ⚠ Measured against the days the holding existed
 *     rather than the length of the year: "priced on 97 of 263 days" for a share bought in
 *     June reads as a hole in the record, when the truth is that it was not owned until June.
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
    <Section
      icon={Globe}
      memory="records.schedule-fa"
      title="Foreign holdings — Schedule FA"
      summary={`1 January – 31 December ${data.year}${
        data.period_end < `${data.year}-12-31` ? " (so far)" : ""
      } · what your tax return asks for each foreign holding`}
      tip="Every Indian resident holding a foreign security declares it in Schedule FA, with no minimum — one fractional share counts. It runs on the calendar year, not the financial year."
      actions={
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Year
          <Select value={String(data.year)} onValueChange={(v) => setYear(Number(v))}>
            <SelectTrigger className="h-8 w-24 text-xs" aria-label="Year">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {data.years_available.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      }
    >
      {data.holdings.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing foreign was held in {data.year}.</p>
      ) : (
        <div className="space-y-4">
          {data.holdings.map((h) => (
            <div key={h.symbol}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium">
                  {h.symbol}
                  <span className="ml-2 font-normal text-muted-foreground">{h.name}</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  acquired {formatDateFull(h.acquired_on)} ·{" "}
                  {formatQuantity(h.closing_quantity)} held at the year end · {h.days_held} of{" "}
                  {h.days_in_period} days held
                </p>
              </div>

              <dl className="mt-3 grid gap-3 rounded-lg bg-muted/40 p-3 sm:grid-cols-2 lg:grid-cols-4">
                <Figure label="Initial value" value={formatRupees(h.initial_inr)}>
                  what was paid, charges included
                </Figure>
                <Figure label="Peak value" value={h.peak_inr ? formatRupees(h.peak_inr) : "—"}>
                  {h.peak_on ? `highest on ${formatDateFull(h.peak_on)}` : "—"}
                </Figure>
                <Figure
                  label="Closing value"
                  value={h.closing_inr ? formatRupees(h.closing_inr) : "—"}
                >
                  {h.closing_on ? `as at ${formatDateFull(h.closing_on)}` : "—"}
                </Figure>
                <Figure label="Received" value={formatRupees(h.gross_income_inr)}>
                  {Number(h.gross_proceeds_inr) !== 0
                    ? `plus ${formatRupees(h.gross_proceeds_inr)} from sales`
                    : "dividends and credits"}
                </Figure>
              </dl>

              {/* ⚠ Against the days HELD, not the days in the year. The first version said
                  "priced on 97 of 263 days" for a share bought in June, which reads as a hole
                  in the record when the truth was that it was simply not owned yet. */}
              {!h.is_complete && (
                <p className="mt-2 text-xs text-caution">
                  Priced on {h.days_valued} of the {h.days_held} days it was held, so the peak is
                  the highest of those days rather than of every day you owned it.
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <Callout tone="info" title="Not filing-ready as it stands" className="mt-4">
        These use the exchange rate recorded with each price. The return wants SBI's TT buying
        rate for each date — every figure names its day so the right rate can be looked up.
      </Callout>
    </Section>
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
