import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
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
  const [open, setOpen] = useState(false);

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

  const lines = [...data.lines].sort(
    (a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind),
  );
  const started = lines.some(
    (l) => l.kind !== "REAL" && l.positions > 0,
  );

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <BookOpen className="size-3.5 text-muted-foreground" />
          The books
          <InfoTip label="Why there are several">
            None of these is a subset of another. Your real book holds things
            Acero never suggested; its paper books hold suggestions you approved
            but may not have acted on; the what-if books hold what never
            happened at all. Merging them would lose whichever question was not
            asked.
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

      {!started && open && (
        <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
          Only the real book has anything in it so far. The others fill as
          suggestions are made and decided — the comparison starts meaning
          something once there is something to compare.
        </p>
      )}

      {open && (
        <>
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-xs">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    Book
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Put in
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Worth now
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Difference
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.kind} className="border-t border-border align-top">
                    <th scope="row" className="px-3 py-2.5 text-left font-medium">
                      {l.name}
                      <span className="block max-w-xs text-xs font-normal text-muted-foreground">
                        {l.purpose}
                      </span>
                    </th>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {formatRupees(l.invested_inr)}
                      <span className="block text-xs text-muted-foreground">
                        {l.positions}{" "}
                        {l.positions === 1 ? "position" : "positions"}
                      </span>
                    </td>
                    {/* ⚠ "—" where even one holding lacks a price. A partial total steps
                        whenever coverage changes, and nobody can tell that apart from the
                        book actually moving. */}
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {l.value_inr == null ? "—" : formatRupees(l.value_inr)}
                    </td>
                    <td
                      className={`px-3 py-2.5 text-right tabular-nums ${
                        l.gain_inr ? directionClass(l.gain_inr) : ""
                      }`}
                    >
                      {l.gain_inr == null ? "—" : formatRupees(l.gain_inr)}
                      {l.gain_pct != null && (
                        <span className="block text-xs">
                          {formatSignedPct(l.gain_pct)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.unaided.length > 0 && (
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm font-medium">
                Bought without being suggested
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data.unaided.join(", ")} — your own judgement, unaided. This is
                the one category a single merged ledger would have discarded,
                and over time it is the direct comparison against the machine.
              </p>
            </div>
          )}

          {/* ⚠ Said in the interface, not just in a code comment. The warning is about the
              reader rather than the data, and it applies every time this is opened. */}
          <p className="text-xs text-muted-foreground">
            Read these together, on a schedule — never after a name that got
            away. A rejected idea that rose is far more memorable than one that
            fell, and a what-if ledger read casually trains worse judgement, not
            better.
          </p>
        </>
      )}
    </section>
  );
}
