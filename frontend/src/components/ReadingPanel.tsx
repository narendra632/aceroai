import { useCallback, useEffect, useState } from "react";
import { Newspaper } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import * as api from "@/lib/api";
import type { Heard, Reading, Source } from "@/lib/api";

/* Where the system reads from, and everything it heard named.
 *
 * ⚠ **Every instrument every source names is recorded** — held or not, acted on or not,
 * dismissed or not. Judge a channel on the ideas you acted on and you are measuring your own
 * filter rather than the channel: forty companies named, three looked at, one that worked
 * reads as 33% instead of 2.5%. The skipped ideas are the denominator and they cannot be
 * reconstructed afterwards.
 *
 * ⚠ **Approving a source widens what is READ, never what is acted on.** A suggestion whose
 * evidence is only commentary still fails its sourcing gate, whatever the commentary said.
 */

const TIER_LABEL: Record<number, string> = {
  1: "filing",
  2: "press",
  3: "commentary",
};

/* Tier is a claim about how much weight the evidence can carry, so it is shown as a word
   rather than a number — "tier 3" means nothing to someone scanning the page. */
function Tier({ tier }: { tier: number }) {
  const tone =
    tier === 1
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
      : tier === 2
        ? "border-border bg-muted/40 text-muted-foreground"
        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-500";
  return (
    <span className={`rounded-full border px-1.5 py-0.5 text-[11px] ${tone}`}>
      {TIER_LABEL[tier] ?? "unknown"}
    </span>
  );
}

function Stance({ stance }: { stance: string }) {
  if (stance === "MENTION_ONLY") return null;
  const tone =
    stance === "BULL"
      ? "text-emerald-700 dark:text-emerald-400"
      : stance === "BEAR"
        ? "text-rose-700 dark:text-rose-400"
        : "text-muted-foreground";
  return <span className={`text-[11px] font-medium ${tone}`}>{stance.toLowerCase()}</span>;
}

function when(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function SourceRow({
  source,
  onApprove,
  onToggle,
  busy,
}: {
  source: Source;
  onApprove: (id: string) => void;
  onToggle: (id: string, next: boolean) => void;
  busy: boolean;
}) {
  const unapproved = source.approved_at == null;
  return (
    <li className="flex flex-wrap items-start gap-x-2 gap-y-1 border-t border-border px-3 py-2.5 first:border-t-0">
      <div className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
          {source.name}
          <Tier tier={source.trust_tier} />
          {!source.is_active && (
            <span className="text-[11px] text-muted-foreground">(off)</span>
          )}
        </span>
        {source.notes && (
          <span className="block text-xs text-muted-foreground">{source.notes}</span>
        )}
      </div>
      {unapproved ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => onApprove(source.id)}
          className="rounded-lg border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
        >
          Start reading it
        </button>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={() => onToggle(source.id, !source.is_active)}
          className="text-xs text-muted-foreground underline underline-offset-2 disabled:opacity-50"
        >
          {source.is_active ? "switch off" : "switch on"}
        </button>
      )}
    </li>
  );
}

function HeardRow({ item }: { item: Heard }) {
  return (
    <li className="border-t border-border px-3 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm font-medium">{item.symbol}</span>
        {/* ⚠ Shown, never filtered on. A reading list that hid what you already own would
            hide every piece of bad news about it — the half that actually costs money. */}
        {item.is_held && (
          <span className="rounded-full border border-border bg-muted/40 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            held
          </span>
        )}
        <Stance stance={item.stance} />
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <Tier tier={item.trust_tier} />
          {item.source}
          {when(item.published_at) && <>· {when(item.published_at)}</>}
        </span>
      </div>
      {item.excerpt && (
        <p className="mt-1 text-xs text-muted-foreground">
          {item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2 hover:text-foreground"
            >
              {item.excerpt}
            </a>
          ) : (
            item.excerpt
          )}
        </p>
      )}
    </li>
  );
}

export default function ReadingPanel() {
  const [data, setData] = useState<Reading | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getReading()
      .then(setData)
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (failed || !data) return null;

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await run();
      load();
    } finally {
      setBusy(false);
    }
  };

  const waiting = data.awaiting_approval;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <Newspaper className="size-3.5 text-muted-foreground" />
          What it reads
          <InfoTip label="Why every mention is kept">
            Every company a source names is written down, whether or not you
            looked at it. Judging a source only on the ideas you acted on
            measures your own filter instead — forty names, three looked at, one
            that worked reads as 33% rather than 2.5%, and the skipped ones
            cannot be reconstructed later.
          </InfoTip>
          {waiting > 0 && (
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-700 dark:text-amber-500">
              {waiting} waiting for you
            </span>
          )}
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
        <>
          <div className="rounded-xl border border-border bg-card">
            <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
              Sources. A filing is the company's own word; commentary is not — a
              suggestion resting on commentary alone is refused whatever it
              said, so approving a channel widens what is read, never what is
              acted on.
            </p>
            <ul>
              {data.sources.map((s) => (
                <SourceRow
                  key={s.id}
                  source={s}
                  busy={busy}
                  onApprove={(id) => act(() => api.approveSource(id))}
                  onToggle={(id, next) => act(() => api.setSourceActive(id, next))}
                />
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-border bg-card">
            <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
              Said in the last month.
            </p>
            {data.heard.length === 0 ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">
                Nothing yet has named a company you track. That is a finding
                about the sources rather than a fault — it is what a mention
                register is for.
              </p>
            ) : (
              <ul>
                {data.heard.map((h, i) => (
                  <HeardRow key={`${h.symbol}-${h.published_at}-${i}`} item={h} />
                ))}
              </ul>
            )}
          </div>

          {data.attribution.some((a) => a.named > 0) && (
            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead className="bg-muted/30 text-xs">
                  <tr>
                    <th scope="col" className="px-3 py-2 text-left font-medium">
                      Source
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Named
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Took a side
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">
                      Right so far
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.attribution
                    .filter((a) => a.named > 0)
                    .map((a) => (
                      <tr key={a.source} className="border-t border-border align-top">
                        <th scope="row" className="px-3 py-2.5 text-left font-medium">
                          {a.source}
                          <span className="mt-0.5 block">
                            <Tier tier={a.trust_tier} />
                          </span>
                        </th>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {a.named}
                          <span className="block text-xs text-muted-foreground">
                            {a.became_proposals} reached a suggestion
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {a.directional}
                          {a.pending > 0 && (
                            <span className="block text-xs text-muted-foreground">
                              {a.pending} not settled
                            </span>
                          )}
                        </td>
                        {/* ⚠ "—" until there are enough settled calls. A hit rate over six
                            reads exactly like one over six hundred, and nothing on a page can
                            tell the reader which they are seeing unless it is withheld. */}
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          {a.hit_rate.value == null ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            `${Math.round(Number(a.hit_rate.value) * 100)}%`
                          )}
                          <span className="block max-w-[16rem] text-xs font-normal text-muted-foreground">
                            {a.hit_rate.detail}
                          </span>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
