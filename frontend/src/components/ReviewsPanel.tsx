import { useEffect, useState } from "react";
import { CalendarCheck } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { InvestmentReview } from "@/lib/api";

/* What was true at the end of a week, a month, a quarter.
 *
 * ⚠ **The artefact actually worth reading.** The daily notifications are operational; this is
 * where the thinking accumulates. It is read on a schedule, which is why it is collapsed by
 * default — dipping into it after a name that got away trains worse judgement, not better.
 *
 * ⚠ **Every figure here was true when it was written and is never recomputed.** A review
 * regenerated later with today's data would show a position that recovered as never having
 * fallen, and a prediction that failed as never having been made.
 */

function when(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function money(raw: string) {
  return `₹${Number(raw).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/* ⚠ A measure with no sample renders as its own sentence, never as a blank or a dash. A blank
   is read as zero by anyone scanning; "0 of 20 resolved claims needed before this means
   anything" cannot be. */
function Measure({ m }: { m: InvestmentReview["content"]["measures"][number] }) {
  const label = m.name.replace(/_/g, " ");
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-t border-border py-1.5 first:border-t-0">
      <span className="text-xs capitalize">{label}</span>
      {m.value == null ? (
        <span className="text-xs text-muted-foreground">{m.detail}</span>
      ) : (
        <span className="text-xs">
          <strong>{Math.round(Number(m.value) * 100)}%</strong>
          <span className="text-muted-foreground"> — {m.detail}</span>
        </span>
      )}
    </li>
  );
}

function One({ review }: { review: InvestmentReview }) {
  const c = review.content;
  const decided = Object.entries(c.decisions.counts);

  return (
    <details className="border-t border-border px-3 py-2.5 first:border-t-0">
      <summary className="cursor-pointer list-none">
        <span className="text-sm font-medium">{review.headline}</span>
        <span className="block text-xs text-muted-foreground">
          {when(review.period_start)} – {when(review.period_end)}
        </span>
      </summary>

      <div className="mt-3 space-y-3 text-xs">
        {/* What you decided, in your own words — the data that eventually says what kinds of
            suggestion you keep turning down. */}
        {decided.length > 0 && (
          <div>
            <p className="font-medium">Decisions</p>
            <ul className="mt-1 space-y-1">
              {c.decisions.decisions.map((d, i) => (
                <li key={i} className="text-muted-foreground">
                  <span className="text-foreground">
                    {d.outcome.toLowerCase()} {d.action.toLowerCase()}
                  </span>{" "}
                  — “{d.reason}”
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ⚠ The rails are reported too. A refusal nobody is shown is a rule nobody can ever
            ask whether it was protecting or merely obstructing. */}
        {c.blocked.length > 0 && (
          <p className="text-muted-foreground">
            The rules refused {c.blocked.length}:{" "}
            {c.blocked.map((b) => b.blocked_by ?? "unknown").join(", ")}
          </p>
        )}

        {/* ⚠ The most useful thing a weekly review carries, and invisible to anything that
            reports only firings. */}
        {c.approaching.length > 0 && (
          <div>
            <p className="font-medium">Close to firing, not fired</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground">
              {c.approaching.map((t, i) => (
                <li key={i}>
                  {t.description} — now {t.value}, threshold {t.threshold}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-muted-foreground">
          Research queue: {c.queue.waiting} waiting
          {c.queue.stale.length > 0 && (
            <>
              {" "}
              · sitting too long:{" "}
              {c.queue.stale.map((s) => `${s.symbol} (${s.age_days}d)`).join(", ")}
            </>
          )}
        </p>

        {/* ⚠ Unspent is stated plainly. The budget is a ceiling, not a target, and framing
            unspent money as a shortfall would be arguing for activity. */}
        <p className="text-muted-foreground">
          Budget {money(c.budget.budget_inr)} · committed {money(c.budget.committed_inr)} ·{" "}
          {money(c.budget.unspent_inr)} not spent, which is a legitimate outcome.
        </p>

        <div>
          <p className="font-medium">How it is doing</p>
          <ul className="mt-1">
            {c.measures.map((m) => (
              <Measure key={m.name} m={m} />
            ))}
          </ul>
        </div>

        {c.sources && c.sources.length > 0 && (
          <div>
            <p className="font-medium">Sources</p>
            <ul className="mt-1 space-y-0.5 text-muted-foreground">
              {c.sources.map((s) => (
                <li key={s.source}>
                  {s.source} — named {s.named},{" "}
                  {s.hit_rate == null
                    ? s.detail
                    : `${Math.round(Number(s.hit_rate) * 100)}% right over ${s.n}`}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

export default function ReviewsPanel() {
  const [data, setData] = useState<InvestmentReview[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getInvestmentReviews()
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed || !data) return null;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <CalendarCheck className="size-3.5 text-muted-foreground" />
          Looking back
          <InfoTip label="What these are">
            Written on Saturdays, at month end and at quarter end, from the
            facts as they were on that day. They are never recomputed — a review
            regenerated later would show a position that recovered as never
            having fallen, and the most interesting part of a review is the part
            that turned out to be wrong.
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
        <div className="rounded-xl border border-border bg-card">
          {data.length === 0 ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">
              The first one arrives on Saturday morning. No market is open then,
              nothing is urgent, and the week is complete — which is the whole
              reason it happens at that hour.
            </p>
          ) : (
            data.map((review) => <One key={review.id} review={review} />)
          )}
        </div>
      )}
    </section>
  );
}
