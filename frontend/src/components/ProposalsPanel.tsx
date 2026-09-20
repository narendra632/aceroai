import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ShieldX } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Proposal, ProposalsView } from "@/lib/api";
import { formatDateFull, formatRupees } from "@/lib/format";

/* What the system suggests, and what its own rules refused.
 *
 * ⚠ **Nothing here moves any money.** Approving updates the paper book the system's own
 * decisions build up; what you do in life is your word, entered like any other transaction.
 * The gap between those two books is one of the most interesting numbers this produces, and
 * merging them would destroy it.
 *
 * Three things are rendered that a tidier screen would hide, and each is the point:
 *
 *   - **Refusals.** A rule whose cost is invisible is a rule nobody can evaluate. Seeing what
 *     the rails blocked is the only way to judge whether they protect or merely obstruct.
 *   - **What would prove it wrong**, beside the argument rather than behind it. A thesis
 *     shown without its invalidation conditions reads as a recommendation.
 *   - **Evenings that suggested nothing.** A system that only leaves a trace on the days it
 *     acted can never be measured against the days it should have.
 */

const ACTION: Record<string, string> = {
  INITIATE: "start a position",
  ADD: "add to it",
  HOLD: "hold",
  TRIM: "trim",
  EXIT: "sell out",
  ACCUMULATE_POOL: "set money aside — one share costs more than the ceiling",
};

const GATE: Record<string, string> = {
  G1_framework: "its place in the framework",
  G2_quadrant: "business and price together",
  G3_margin_of_safety: "the price",
  G4_invalidation: "what would prove it wrong",
  G6_cooling_off: "raised too soon after a refusal",
  G7_corporate_action: "an unrecorded corporate action",
  G8_price_age: "the price is too old",
  G9_volume: "enough suggestions for now",
  G11_confidence: "not confident enough to be worth your time",
};

export default function ProposalsPanel() {
  const [data, setData] = useState<ProposalsView | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRefused, setShowRefused] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.getProposals());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed || !data) return null;

  const refused = data.recent.filter((p) => p.status === "BLOCKED");
  const settled = data.recent.filter(
    (p) => p.status === "APPROVED" || p.status === "REJECTED",
  );

  async function decide(
    p: Proposal,
    outcome: "APPROVE" | "REJECT",
    reason: string,
  ) {
    setBusy(p.id);
    setError(null);
    try {
      await api.decideProposal(p.id, outcome, reason);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          Suggestions
          <InfoTip label="What these are">
            The system proposes; it never acts. Nothing is bought or sold by
            Acero — approving records the decision in its own paper book, and
            what you do in real life you enter yourself. The difference between
            the two is deliberately visible.
          </InfoTip>
        </h2>
        <p className="text-xs text-muted-foreground">
          {data.runs_recorded} evening{data.runs_recorded === 1 ? "" : "s"}{" "}
          recorded
          {data.last_run_at
            ? `, last on ${formatDateFull(data.last_run_at)}`
            : ""}
        </p>
      </div>

      {data.open.length === 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-sm">Nothing is suggested right now.</p>
          {/* ⚠ Said plainly rather than left blank. Proposing nothing is usually the correct
              outcome, and a screen that looks broken when the system is behaving well
              teaches the reader to distrust it. */}
          <p className="mt-1 text-xs text-muted-foreground">
            That is the usual and usually correct answer. Every evening is
            recorded either way, so the quiet ones can be counted later.
          </p>
        </div>
      )}

      {data.open.map((p) => (
        <Card
          key={p.id}
          proposal={p}
          busy={busy === p.id}
          onDecide={(outcome, reason) => decide(p, outcome, reason)}
        />
      ))}

      {settled.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-sm font-medium">Decided</p>
          <ul className="mt-2 space-y-1">
            {settled.map((p) => (
              <li key={p.id} className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{p.symbol}</span>{" "}
                {ACTION[p.action] ?? p.action} — {p.status.toLowerCase()}
                {p.decision_reason ? `: “${p.decision_reason}”` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {refused.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4">
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 text-left"
            onClick={() => setShowRefused((v) => !v)}
          >
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <ShieldX className="size-3.5 text-muted-foreground" />
              {refused.length} refused by the rules
            </span>
            <span className="text-xs text-muted-foreground">
              {showRefused ? "hide" : "show"}
            </span>
          </button>
          {/* ⚠ Shown on request, not hidden. A rule whose cost is invisible is a rule nobody
              can ever evaluate — but nor should refusals crowd out the live decisions. */}
          <p className="mt-1 text-xs text-muted-foreground">
            Kept so the rails can be judged too: a rule you never see the cost
            of is a rule you cannot tell is working.
          </p>
          {showRefused && (
            <ul className="mt-3 space-y-2">
              {refused.map((p) => (
                <li key={p.id} className="text-xs">
                  <span className="font-medium">{p.symbol}</span> —{" "}
                  {GATE[p.blocked_by ?? ""] ?? p.blocked_by}
                  <span className="block text-muted-foreground">
                    {p.gates.find((g) => g.gate === p.blocked_by)?.detail}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function Card({
  proposal: p,
  busy,
  onDecide,
}: {
  proposal: Proposal;
  busy: boolean;
  onDecide: (outcome: "APPROVE" | "REJECT", reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const price = p.price_snapshot?.price as string | undefined;

  return (
    <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">
          {p.symbol}: {ACTION[p.action] ?? p.action}
          {p.target_amount_inr && (
            <span className="ml-2 font-normal">
              {formatRupees(p.target_amount_inr)}
              {p.target_qty ? ` · ${p.target_qty} shares` : ""}
            </span>
          )}
        </p>
        <p className="text-xs text-muted-foreground">
          {Math.round(Number(p.confidence) * 100)}% confident ·{" "}
          {p.horizon_days} days · {p.quadrant}
        </p>
      </div>

      {/* The argument, exactly as recorded. Never re-worded on display: what the system said
          is the thing being judged later. */}
      <p className="mt-2 whitespace-pre-line text-sm">{p.thesis}</p>

      {price && (
        <p className="mt-2 text-xs text-muted-foreground">
          Suggested at {formatRupees(price)}, and that price is frozen onto this
          record — what the system saw is a different fact from what the market
          later did.
        </p>
      )}

      {p.triggers.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium">
            What would prove this wrong
            <InfoTip label="Why this matters">
              Each is a number, a comparison and a date, so it can actually be
              checked. “If the story changes” cannot be, which means a position
              carrying it could never be shown to be wrong.
            </InfoTip>
          </p>
          <ul className="mt-1 space-y-0.5">
            {p.triggers.map((t) => (
              <li key={t.id} className="text-xs text-muted-foreground">
                • {t.description}{" "}
                <span className="opacity-70">
                  (by {formatDateFull(t.window_until)})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.claims.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium">What it is claiming</p>
          <ul className="mt-1 space-y-0.5">
            {p.claims.map((c) => (
              <li key={c.id} className="text-xs text-muted-foreground">
                • {c.claim_text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.reflexivity_flags_yes > 0 && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="size-3" />
          {p.reflexivity_flags_yes} red flag
          {p.reflexivity_flags_yes === 1 ? "" : "s"} standing against it
        </p>
      )}

      <div className="mt-3 space-y-2">
        {/* ⚠ Required, not optional. The reason in your own words is the data that eventually
            shows what kinds of suggestion you keep turning down — the only way the system
            learns anything about its own judgement. */}
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Why — in your own words. Required."
          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        />
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={busy || !reason.trim()}
            onClick={() => onDecide("APPROVE", reason)}
          >
            {busy ? "Saving…" : "Approve"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !reason.trim()}
            onClick={() => onDecide("REJECT", reason)}
          >
            Reject
          </Button>
        </div>
      </div>
    </div>
  );
}
