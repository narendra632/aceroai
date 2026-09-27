import { useCallback, useEffect, useState } from "react";
import { Telescope } from "lucide-react";

import { Callout, Chip, Meter, Quiet, Section } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { QueueLine, ResearchQueue } from "@/lib/api";
import { ageText, TIER } from "@/lib/investments";

/* Companies something named, that you neither hold nor watch.
 *
 * ⚠ **This is the half that makes it a research assistant.** Without it the system can only
 * ever say hold, trim or sell — a research analyst that can only comment on what you already
 * own is a bookkeeper with opinions.
 *
 * ⚠ **Nothing here is a recommendation.** A company reaches this list because a source named
 * it, and a source naming something is a lead, never an instruction. A suggestion resting on
 * commentary alone is still refused by the sourcing gate whatever the commentary said.
 */

/* ⚠ Earned AND available, always both. "4" says nothing on its own — four of four is
   excellent and four of ten is mediocre, and the difference is whether the filings were read. */
function Quality({ line }: { line: QueueLine }) {
  if (line.quality_available == null) return null;
  const available = Number(line.quality_available);
  if (available === 0) {
    return <span className="text-muted-foreground">not enough filed data to score it yet</span>;
  }
  return (
    <span className="inline-flex items-center gap-2">
      <span className="text-muted-foreground">Business</span>
      <Meter
        value={Number(line.quality_earned ?? 0)}
        max={available}
        label="Business quality, of what could be scored"
      />
    </span>
  );
}

function Row({
  line,
  busy,
  onAnalyse,
  onPromote,
  onDismiss,
}: {
  line: QueueLine;
  busy: boolean;
  onAnalyse: (line: QueueLine) => void;
  onPromote: (line: QueueLine) => void;
  onDismiss: (line: QueueLine, why: string) => Promise<void>;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const tier = TIER[line.best_trust_tier] ?? { label: "unknown", tone: "neutral" as const };

  return (
    <li id={`item-${line.id}`} className="scroll-mt-4 px-4 py-3.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-base font-semibold">{line.symbol}</span>
        <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{line.name}</span>
        <Chip tone={tier.tone}>{tier.label}</Chip>
      </div>

      <p className="mt-0.5 text-xs text-muted-foreground">
        Named by {line.named_by ?? "an unnamed source"} · first seen {ageText(line.age_days)}
        {/* ⚠ Repetition is shown because it is what the ordering rests on. */}
        {line.mention_count > 1 && ` · named ${line.mention_count} times`}
      </p>

      {line.excerpt && (
        <p className="mt-2 line-clamp-3 border-l-2 border-border pl-2.5 text-xs italic text-muted-foreground">
          {line.excerpt}
        </p>
      )}

      {/* What reading its filings turned up. ⚠ Absent until something has actually been read —
          a score shown before then would be a score of nothing. */}
      {line.proposed_bottleneck && (
        <div className="mt-2.5 space-y-1.5 rounded-lg bg-muted/40 p-2.5 text-xs">
          <p>
            Would sit on <strong>{line.proposed_bottleneck}</strong>
            {line.bottleneck_name && ` — ${line.bottleneck_name}`}
            {/* ⚠ Said out loud, because an unapproved mapping scores ZERO and a reader who did
                not know that would read a low score as a verdict on the company. */}
            <span className="text-muted-foreground"> · proposed, scores nothing until you agree</span>
          </p>
          {line.bottleneck_why && <p className="text-muted-foreground">{line.bottleneck_why}</p>}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Quality line={line} />
            {line.price && (
              <span className="text-muted-foreground">
                last ₹{Number(line.price).toLocaleString("en-IN")}
              </span>
            )}
          </p>
        </div>
      )}

      {line.status === "DISMISSED" ? (
        <p className="mt-2 text-xs text-muted-foreground">Not taken up — {line.dismissed_reason}</p>
      ) : line.status === "PROMOTED" ? (
        <p className="mt-2 text-xs text-muted-foreground">Now followed.</p>
      ) : dismissing ? (
        /* ⚠ The reason opens under the row it is about. It used to open at the bottom of the
           whole list, where the connection between "Not interested" and the box asking why
           was lost on anyone with more than two leads. */
        <div className="mt-2.5 rounded-lg border border-border bg-background p-2.5">
          <label htmlFor={`dismiss-${line.id}`} className="text-xs font-medium">
            Not taking up {line.symbol} — why?
          </label>
          <textarea
            id={`dismiss-${line.id}`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            autoFocus
            placeholder="too expensive, outside the framework, governance…"
            className="mt-1.5 w-full rounded-md border border-border bg-card p-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <div className="mt-2 flex gap-2">
            <Button
              size="sm"
              disabled={busy || reason.trim().length < 3}
              onClick={async () => {
                await onDismiss(line, reason.trim());
                setDismissing(false);
              }}
            >
              Record it
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDismissing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2.5 flex flex-wrap gap-2">
          {/* ⚠ Two separate acts, and the labels say which is which. Reading its filings costs
              a handful of requests once; following it costs them every day for as long as you
              keep it. */}
          {line.status === "QUEUED" && (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onAnalyse(line)}>
              Read its filings
            </Button>
          )}
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onPromote(line)}>
            Follow it
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            disabled={busy}
            onClick={() => {
              setReason("");
              setDismissing(true);
            }}
          >
            Not interested
          </Button>
        </div>
      )}
    </li>
  );
}

export default function ResearchPanel({
  reloadKey = 0,
  onChanged,
}: {
  reloadKey?: number;
  onChanged?: () => void;
}) {
  const [data, setData] = useState<ResearchQueue | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getResearchQueue()
      .then((d) => {
        setData(d);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  if (failed) {
    return (
      <Callout tone="caution" title="The research queue could not be loaded">
        Reload to try again.
      </Callout>
    );
  }
  if (!data) return null;

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await run();
      load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      id="worth-a-look"
      icon={Telescope}
      memory="decisions.leads"
      title="Worth a look"
      count={data.lines.length}
      summary="Companies a source named that you don't follow yet — leads, never recommendations"
      tip="Reading its filings places it in the framework and scores it, once. Following it adds it to the daily price loop and to Companies."
      flush={data.lines.length > 0}
    >
      {data.lines.length === 0 ? (
        <Quiet icon={Telescope}>
          Nothing waiting. Sources are read against {data.universe_size.toLocaleString()} listed
          companies — one lands here the moment a source names it.
        </Quiet>
      ) : (
        <>
          <ul className="divide-y divide-border">
            {data.lines.map((line) => (
              <Row
                key={line.id}
                line={line}
                busy={busy}
                onAnalyse={(l) => act(() => api.analyseCandidate(l.id))}
                onPromote={(l) => act(() => api.promoteCandidate(l.id))}
                onDismiss={(l, why) => act(() => api.dismissCandidate(l.id, why))}
              />
            ))}
          </ul>
          {error && (
            <p className="px-4 pb-3 text-sm text-bad" role="alert">
              {error}
            </p>
          )}
        </>
      )}
    </Section>
  );
}
