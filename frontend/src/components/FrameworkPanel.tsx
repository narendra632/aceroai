import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronRight } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Framework, Mapping } from "@/lib/api";

/* Where each company sits in the framework, and what that is worth.
 *
 * ⚠ **The approve button is the most important control in this module**, and it is easy to
 * mistake for paperwork. The structural score is the one place the system makes a claim
 * about national importance, and a machine that reads enough news will eventually talk
 * itself into believing an unrelated small-cap is strategically essential. The guard is that
 * a mapping scores **zero** until a person agrees with it. So this screen is not a settings
 * page — it is the gate, and every unapproved row is a company the system is deliberately
 * refusing to score.
 *
 * Two distinctions are rendered rather than flattened, because collapsing either would print
 * something untrue:
 *
 *   - **"—" (not applicable) is not "0".** SpaceX scores nothing because the framework asks
 *     what INDIA must build, not because it failed a test.
 *   - **"at least 4" is not "4".** His notes establish the crossing count for eight
 *     bottlenecks and leave the rest unstated; a floor shown as a finding would mark a
 *     company narrow for a documentation reason.
 */

const ATTENTION_LABEL: Record<api.FrameworkAttention["kind"], string> = {
  UNMAPPED: "not in the framework yet",
  UNAPPROVED: "waiting for you",
  EXPIRED: "needs re-confirming",
  BREADTH_FLOOR: "breadth may be understated",
  NO_MULTIPLE: "no fair multiple",
};

export default function FrameworkPanel() {
  const [data, setData] = useState<Framework | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remapping, setRemapping] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.getFramework());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Absent rather than empty. A book with no framework installed has nothing to say here,
  // and an empty panel on every visit is a region readers learn to skip.
  if (failed || !data) return null;

  const waiting = data.attention.filter(
    (a) => a.kind === "UNAPPROVED" || a.kind === "UNMAPPED" || a.kind === "EXPIRED",
  );

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      await load();
      setRemapping(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            Framework
            <InfoTip label="What the framework does">
              Ten things India must build, the bottlenecks in the way, and which companies
              clear them. A company scores nothing here until you agree it belongs — the
              system may suggest, it may not decide.
            </InfoTip>
          </h2>
          <p className="text-xs text-muted-foreground">
            version {data.version} · {data.mappings.length} companies ·{" "}
            {data.bottlenecks.length} bottlenecks
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen((v) => !v)}>
          {open ? (
            <ChevronDown className="size-3.5" />
          ) : (
            <ChevronRight className="size-3.5" />
          )}
          {open ? "Hide" : "Show"}
        </Button>
      </div>

      {/* ⚠ Shown whether or not the panel is expanded. An unapproved mapping is a company
          the system cannot score, and that has to be visible without being hunted for. */}
      {waiting.length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
          <p className="flex items-center gap-1.5 text-sm font-medium">
            <AlertTriangle className="size-4 text-amber-600 dark:text-amber-400" />
            {waiting.length}{" "}
            {waiting.length === 1 ? "company needs" : "companies need"} your
            agreement
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Each is scoring zero until you confirm it belongs where the framework
            puts it. That is the guard, not a fault: a machine may suggest that a
            company clears a national bottleneck, and the suggestion is worth
            nothing until you agree.
          </p>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {waiting.map((a) => (
              <li
                key={`${a.symbol}-${a.kind}`}
                className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {a.symbol} · {ATTENTION_LABEL[a.kind]}
              </li>
            ))}
          </ul>
          {!open && (
            <Button
              size="sm"
              className="mt-3"
              onClick={() => setOpen(true)}
            >
              Review them
            </Button>
          )}
        </div>
      )}

      {open && (
        <ul className="space-y-2">
          {data.mappings.map((m) => (
            <li
              key={m.id}
              className="rounded-xl border border-border bg-card p-4"
            >
              <Row
                mapping={m}
                bottlenecks={data.bottlenecks}
                busy={busy === m.id}
                remapping={remapping === m.id}
                onRemapToggle={() =>
                  setRemapping(remapping === m.id ? null : m.id)
                }
                onApprove={() => run(m.id, () => api.approveMapping(m.id))}
                onRemap={(b, off) =>
                  run(m.id, () =>
                    api.remapInstrument(m.id, {
                      b_bottleneck: off ? null : b,
                      off_framework: off,
                    }),
                  )
                }
              />
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function Row({
  mapping: m,
  bottlenecks,
  busy,
  remapping,
  onRemapToggle,
  onApprove,
  onRemap,
}: {
  mapping: Mapping;
  bottlenecks: api.Bottleneck[];
  busy: boolean;
  remapping: boolean;
  onRemapToggle: () => void;
  onApprove: () => void;
  onRemap: (b: string, off: boolean) => void;
}) {
  const [choice, setChoice] = useState(m.b_bottleneck ?? "");
  const approved = m.approved_at != null;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {m.symbol}
            <span className="ml-2 font-normal text-muted-foreground">
              {m.name}
            </span>
            {!m.is_held && (
              <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs font-normal text-muted-foreground">
                watchlist
              </span>
            )}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {m.off_framework
              ? "outside the framework"
              : `${m.b_bottleneck} · ${m.bottleneck_name}`}
          </p>
        </div>

        {/* ⚠ "—" for not-applicable, never 0. They are different answers. */}
        <div className="text-right">
          <p
            className="text-lg font-semibold"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {m.score.total == null ? "—" : `${m.score.total}/10`}
          </p>
          <p className="text-xs text-muted-foreground">
            {approved ? "structural score" : "not yet scoring"}
          </p>
        </div>
      </div>

      {m.rationale && (
        <p className="mt-2 text-sm text-muted-foreground">{m.rationale}</p>
      )}

      {m.score.unavailable_because && (
        <p className="mt-2 text-xs text-muted-foreground">
          {m.score.unavailable_because}
        </p>
      )}

      {approved && m.score.total != null && (
        <dl className="mt-3 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
          {m.score.components.map((c) => (
            <div key={c.name} className="flex items-baseline gap-2">
              <dt className="w-24 shrink-0 capitalize text-muted-foreground">
                {c.name}
              </dt>
              <dd className="font-medium tabular-nums">
                {c.points}/{c.available}
              </dd>
              <dd className="truncate text-muted-foreground" title={c.detail}>
                {c.detail}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {m.score.breadth_is_floor && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 size-3 shrink-0" />
          The crossing count is a floor. Your notes establish it for eight
          bottlenecks and leave this one unstated, so the score may be
          understated — it is not a ceiling.
        </p>
      )}

      {m.multiple_is_fallback && !m.off_framework && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
          {m.multiple_why} — any margin of safety from it is a guess.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {!approved && (
          <Button size="sm" disabled={busy} onClick={onApprove}>
            {busy ? "Saving…" : "Agree"}
          </Button>
        )}
        {approved && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Check className="size-3" />
            agreed
            {m.review_after ? ` · review after ${m.review_after}` : ""}
          </span>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={onRemapToggle}
        >
          {remapping ? "Cancel" : "Move it"}
        </Button>
      </div>

      {remapping && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-3">
          <select
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="">— choose a bottleneck —</option>
            {bottlenecks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.id} · {b.name} (blocks {b.crosses.length})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={busy || !choice}
            onClick={() => onRemap(choice, false)}
          >
            Move
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onRemap("", true)}
          >
            Outside the framework
          </Button>
        </div>
      )}
    </>
  );
}
