import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import { Section } from "@/components/investments/kit";
import * as api from "@/lib/api";
import type { Books } from "@/lib/api";
import { formatRupees, formatSignedPct } from "@/lib/format";
import { directionClass } from "@/lib/investments";

/* Every book side by side.
 *
 * ⚠ **None of these is a subset of another**, and that is the whole point. Three categories
 * exist, and a single combined ledger would silently discard the third:
 *
 *   - Acero proposed → you approved → you did it
 *   - Acero proposed → you approved → you did something else
 *   - **you bought something Acero never proposed**
 *
 * ⚠ **This panel is for reading in aggregate, on a schedule.** A rejected idea that rose is
 * far more memorable than one that fell, so a what-if ledger browsed after a name that got
 * away trains worse judgement rather than better. It is collapsed by default for that reason,
 * not to save space.
 */

/* The order matters: what is real, then what following the system would have produced, then
   the machine alone, then the benchmark, then the three what-ifs. */
const ORDER = [
  "REAL",
  "MIRROR",
  "AI_CLEAN",
  "PROPOSED_ALL",
  "SHADOW_VETO",
  "SHADOW_BUDGET",
  "SHADOW_GATE",
];

export default function BooksPanel() {
  const [data, setData] = useState<Books | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getBooks()
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed || !data) return null;

  const lines = [...data.lines].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const started = lines.some((l) => l.kind !== "REAL" && l.positions > 0);

  return (
    <Section
      icon={BookOpen}
      memory="scorecard.books"
      defaultOpen={false}
      title="The books, side by side"
      summary={
        started
          ? `${lines.length} books valued at the same prices — read together, on a schedule`
          : "Only your real book has anything in it so far; the others fill as suggestions are decided"
      }
      tip="Your real book holds things Acero never suggested; its paper books hold suggestions you approved; the what-if books hold what never happened. None is a subset of another."
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-2 text-left font-medium">
                Book
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Put in
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Worth now
              </th>
              <th scope="col" className="px-4 py-2 text-right font-medium">
                Difference
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr
                key={l.kind}
                className={`border-t border-border align-top ${l.positions === 0 ? "text-muted-foreground" : ""}`}
              >
                <th scope="row" className="px-4 py-2.5 text-left font-medium">
                  {l.name}
                  <span className="block max-w-xs text-xs font-normal text-muted-foreground">
                    {l.purpose}
                  </span>
                </th>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {formatRupees(l.invested_inr)}
                  <span className="block text-xs text-muted-foreground">
                    {l.positions} {l.positions === 1 ? "position" : "positions"}
                  </span>
                </td>
                {/* ⚠ "—" where even one holding lacks a price. A partial total steps whenever
                    coverage changes, and nobody can tell that apart from the book moving. */}
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {l.value_inr == null ? "—" : formatRupees(l.value_inr)}
                </td>
                <td
                  className={`px-4 py-2.5 text-right tabular-nums ${
                    l.gain_inr ? directionClass(l.gain_inr) : ""
                  }`}
                >
                  {l.gain_inr == null ? "—" : formatRupees(l.gain_inr)}
                  {l.gain_pct != null && (
                    <span className="block text-xs">{formatSignedPct(l.gain_pct)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 border-t border-border px-4 py-3 text-xs text-muted-foreground">
        {data.unaided.length > 0 && (
          <p>
            <strong className="font-medium text-foreground">Bought without being suggested:</strong>{" "}
            {data.unaided.join(", ")} — your own judgement, unaided, and over time the direct
            comparison against the machine.
          </p>
        )}
        {/* ⚠ Said in the interface, not just in a code comment. The warning is about the reader
            rather than the data, and it applies every time this is opened. */}
        <p>
          Read these together, on a schedule — never after a name that got away. A rejected idea
          that rose is far more memorable than one that fell.
        </p>
      </div>
    </Section>
  );
}
