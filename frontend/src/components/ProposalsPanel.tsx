import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, History, Lightbulb, ShieldAlert, ShieldX, Target } from "lucide-react";

import { Callout, Chip, Meter, Quiet, Section } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Proposal, ProposalsView } from "@/lib/api";
import { formatDateFull, formatRupees } from "@/lib/format";
import { ACTION_WORDS, GATE_WORDS, QUADRANT } from "@/lib/investments";

/* What the system suggests, and what its own rules refused.
 *
 * ⚠ **Nothing here moves any money.** Approving updates the paper book the system's own
 * decisions build up; what you do in life is your word, entered like any other transaction.
 *
 * Three things are rendered that a tidier screen would hide, and each is the point:
 *
 *   - **Refusals.** A rule whose cost is invisible is a rule nobody can evaluate. They are
 *     grouped — forty rows of "the price" said one thing forty times — and closed, because
 *     they are for judging the rules, not for acting on today.
 *   - **What would prove it wrong**, beside the argument rather than behind it. A thesis shown
 *     without its invalidation conditions reads as a recommendation.
 *   - **Evenings that suggested nothing.** A system that only leaves a trace on the days it
 *     acted can never be measured against the days it should have.
 *
 * The prediction record ("how it is doing") moved to the Scorecard: it answers whether the
 * reasoning works, which is a monthly question, and this tab is for what needs deciding now.
 */

/** ⚠ `children` renders between what is live and what already happened. The leads and themes
 *  belong to "decide now" and the refusals and past decisions to "judge the rules later", and
 *  one fetch serves both halves — so the panel frames the others rather than being stacked
 *  above them, which put forty refusals between the suggestions and the leads. */
export default function ProposalsPanel({
  onChanged,
  children,
}: {
  onChanged?: () => void;
  children?: React.ReactNode;
}) {
  const [data, setData] = useState<ProposalsView | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  if (failed) {
    return (
      <div className="space-y-4">
        <Callout tone="caution" title="Suggestions could not be loaded">
          The rest of the page is unaffected. Reload to try again.
        </Callout>
        {children}
      </div>
    );
  }
  // ⚠ No early return while loading: the leads below render in the same place either way, so
  // they are not unmounted and fetched twice when the suggestions arrive.
  const recent = data?.recent ?? [];
  const refused = recent.filter((p) => p.status === "BLOCKED");
  const settled = recent.filter((p) => p.status === "APPROVED" || p.status === "REJECTED");

  async function decide(p: Proposal, outcome: "APPROVE" | "REJECT", reason: string) {
    setBusy(p.id);
    setError(null);
    try {
      await api.decideProposal(p.id, outcome, reason);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {/* ⚠ Above everything, including live suggestions. A fired condition means a thesis you
          hold money against has been contradicted by the facts — and being told when that
          happens is the entire reason the condition was written down in advance. */}
      {data?.fired.map((f) => (
        <Callout
          key={f.id}
          id={`item-${f.id}`}
          tone="bad"
          title={
            <>
              {f.symbol}: something that would prove the idea wrong has happened
            </>
          }
        >
          <p className="text-foreground">{f.description}</p>
          <p className="mt-1 text-xs">
            {f.metric_key} is now {String(f.evidence.value ?? "?")}, against the{" "}
            {String(f.evidence.threshold ?? "?")} written down when the position was taken
            {f.fired_at ? ` · ${formatDateFull(f.fired_at)}` : ""}. Decide whether the reason you
            hold it still stands.
          </p>
        </Callout>
      ))}

      {data && (
        <Section
          icon={Lightbulb}
          title="Suggestions"
          count={data.open.length}
          countTone="accent"
          collapsible={false}
          summary={
            <>
              Checked every evening — {data.runs_recorded} evening
              {data.runs_recorded === 1 ? "" : "s"} so far
              {data.last_run_at ? `, last on ${formatDateFull(data.last_run_at)}` : ""}. Nothing is
              bought or sold for you.
            </>
          }
          flush={data.open.length > 0}
        >
          {data.open.length === 0 ? (
            <Quiet>
              Nothing suggested right now. That is the usual answer, and usually the right one —
              the quiet evenings are recorded too, so they can be counted later.
            </Quiet>
          ) : (
            <div className="divide-y divide-border">
              {data.open.map((p) => (
                <Card
                  key={p.id}
                  proposal={p}
                  busy={busy === p.id}
                  onDecide={(outcome, reason) => decide(p, outcome, reason)}
                />
              ))}
            </div>
          )}
        </Section>
      )}

      {error && (
        <p className="text-sm text-bad" role="alert">
          {error}
        </p>
      )}

      {children}

      {refused.length > 0 && <Refused refused={refused} />}

      {settled.length > 0 && (
        <Section
          icon={History}
          memory="decisions.decided"
          defaultOpen={false}
          title="Decided"
          summary={`${settled.length} recent · ${
            settled.filter((p) => p.status === "APPROVED").length
          } approved, ${settled.filter((p) => p.status === "REJECTED").length} rejected`}
          flush
        >
          <ul className="divide-y divide-border">
            {settled.map((p) => (
              <li key={p.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2.5">
                <span className="text-sm font-medium">{p.symbol}</span>
                <span className="text-xs text-muted-foreground">
                  {ACTION_WORDS[p.action] ?? p.action}
                </span>
                <Chip tone={p.status === "APPROVED" ? "good" : "neutral"}>
                  {p.status.toLowerCase()}
                </Chip>
                {p.decision_reason && (
                  <span className="w-full text-xs text-muted-foreground">
                    “{p.decision_reason}”
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

/** What the rules refused, grouped so the pattern is readable.
 *
 *  ⚠ Kept, and shown on request — a rule you never see the cost of is a rule you cannot tell
 *  is working. But forty lines of the same refusal is not information, it is a wall, and the
 *  question it answers is "which rule, and for whom", which a grouping answers at a glance. */
function Refused({ refused }: { refused: Proposal[] }) {
  const byRule = new Map<string, number>();
  const latest = new Map<string, Proposal>();
  for (const p of refused) {
    const rule = p.blocked_by ?? "unknown";
    byRule.set(rule, (byRule.get(rule) ?? 0) + 1);
    // `recent` arrives newest first, so the first seen per company is its latest refusal.
    if (!latest.has(p.symbol)) latest.set(p.symbol, p);
  }
  const rules = [...byRule.entries()].sort((a, b) => b[1] - a[1]);
  const [top] = rules;

  return (
    <Section
      icon={ShieldX}
      memory="decisions.refused"
      defaultOpen={false}
      title="Refused by the rules"
      summary={`${refused.length} refusals across ${latest.size} ${
        latest.size === 1 ? "company" : "companies"
      } · mostly ${GATE_WORDS[top[0]] ?? top[0]}`}
      tip="Kept so the rules can be judged too. Most refusals are the price rule saying a good company costs too much right now — that is the rules working."
    >
      <div className="space-y-4">
        <div>
          <p className="mb-2 text-xs font-medium">Which rule</p>
          <ul className="space-y-1.5">
            {rules.map(([rule, n]) => (
              <li key={rule} className="grid grid-cols-[10rem_1fr] items-center gap-3 text-xs">
                <span className="truncate text-muted-foreground">{GATE_WORDS[rule] ?? rule}</span>
                <Meter
                  value={n}
                  max={refused.length}
                  label={`${GATE_WORDS[rule] ?? rule}: ${n} refusals`}
                  tone="neutral"
                  text={String(n)}
                  width="w-full max-w-64"
                />
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium">Latest, per company</p>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {[...latest.values()].map((p) => (
              <li key={p.id} className="px-3 py-2 text-xs">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{p.symbol}</span>
                  <Chip>{GATE_WORDS[p.blocked_by ?? ""] ?? p.blocked_by}</Chip>
                </span>
                <span className="mt-1 block text-muted-foreground">
                  {p.gates.find((g) => g.gate === p.blocked_by)?.detail}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
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
  const confidence = Math.round(Number(p.confidence) * 100);
  const box = QUADRANT[p.quadrant ?? ""];

  return (
    <article id={`item-${p.id}`} className="scroll-mt-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold">{p.symbol}</span>
            <Chip tone="accent">{ACTION_WORDS[p.action] ?? p.action}</Chip>
            {box && <Chip tone={box.tone}>{box.label}</Chip>}
          </p>
          {p.target_amount_inr && (
            <p className="mt-1 text-sm tabular-nums">
              {formatRupees(p.target_amount_inr)}
              {p.target_qty ? ` · ${p.target_qty} shares` : ""}
              <span className="text-muted-foreground"> · over {p.horizon_days} days</span>
            </p>
          )}
        </div>
        <div className="text-right">
          <Meter
            value={confidence}
            max={100}
            label="How confident it is"
            text={`${confidence}%`}
            tone={confidence >= 70 ? "good" : "caution"}
          />
          <p className="mt-0.5 text-xs text-muted-foreground">confident</p>
        </div>
      </div>

      {/* The argument, exactly as recorded. Never re-worded on display: what the system said is
          the thing being judged later. */}
      <p className="mt-3 whitespace-pre-line text-sm leading-relaxed">{p.thesis}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {p.triggers.length > 0 && (
          <div>
            <p className="flex items-center gap-1.5 text-xs font-semibold">
              <ShieldAlert className="size-3.5 text-caution" aria-hidden="true" />
              What would prove it wrong
            </p>
            <ul className="mt-1.5 space-y-1 text-xs text-muted-foreground">
              {p.triggers.map((t) => (
                <li key={t.id}>
                  {t.description}{" "}
                  <span className="text-faint">(by {formatDateFull(t.window_until)})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {p.claims.length > 0 && (
          <div>
            <p className="flex items-center gap-1.5 text-xs font-semibold">
              <Target className="size-3.5 text-info" aria-hidden="true" />
              What it predicts will happen
            </p>
            <ul className="mt-1.5 space-y-1 text-xs text-muted-foreground">
              {p.claims.map((c) => (
                <li key={c.id}>{c.claim_text}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {p.reflexivity_flags_yes > 0 && (
          <Chip tone="caution" icon={AlertTriangle}>
            {p.reflexivity_flags_yes} red flag{p.reflexivity_flags_yes === 1 ? "" : "s"} against it
          </Chip>
        )}
        {price && (
          <span className="text-xs text-muted-foreground">
            Suggested at {formatRupees(price)} — that price is frozen onto this record.
          </span>
        )}
      </div>

      <div className="mt-4 rounded-lg bg-muted/40 p-3">
        {/* ⚠ Required, not optional. The reason in your own words is the data that eventually
            shows what kinds of suggestion you keep turning down. */}
        <label htmlFor={`why-${p.id}`} className="text-xs font-medium">
          Your decision, and why — in your own words
        </label>
        <textarea
          id={`why-${p.id}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={2}
          placeholder="Required. e.g. the price is fine but I already hold enough of this theme"
          className="mt-1.5 w-full rounded-md border border-border bg-background px-2.5 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={busy || !reason.trim()} onClick={() => onDecide("APPROVE", reason)}>
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
          <span className="text-xs text-muted-foreground">
            Approving moves no money — buy it yourself, then record it.
          </span>
        </div>
      </div>
    </article>
  );
}
