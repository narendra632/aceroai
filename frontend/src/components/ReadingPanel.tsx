import { useCallback, useEffect, useState } from "react";
import { BarChart3, Ear, Radio, Plus } from "lucide-react";

import { Callout, Chip, Quiet, Section } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import * as api from "@/lib/api";
import type { Heard, Reading, Source } from "@/lib/api";
import { TIER } from "@/lib/investments";

/* Where the system reads from, what it heard, and whether each source has been worth it.
 *
 * ⚠ **Its own tab now.** It used to be a collapsed panel at the bottom of the framework, with
 * "1 waiting for you" as a badge nobody could see until they had opened it — for the one part
 * of the research half the user now manages himself, adding and switching channels.
 *
 * ⚠ **Every instrument every source names is recorded** — held or not, acted on or not. Judge a
 * channel on the ideas you acted on and you are measuring your own filter rather than the
 * channel: forty companies named, three looked at, one that worked reads as 33% instead of
 * 2.5%. The skipped ideas are the denominator and they cannot be reconstructed afterwards.
 *
 * ⚠ **Approving a source widens what is READ, never what is acted on.** A suggestion whose
 * evidence is only commentary still fails its sourcing gate, whatever the commentary said.
 */

function Tier({ tier }: { tier: number }) {
  const t = TIER[tier] ?? { label: "unknown", tone: "neutral" as const };
  return <Chip tone={t.tone}>{t.label}</Chip>;
}

function Stance({ stance }: { stance: string }) {
  if (stance === "MENTION_ONLY") return null;
  return (
    <Chip tone={stance === "BULL" ? "good" : stance === "BEAR" ? "bad" : "neutral"}>
      {stance === "BULL" ? "for it" : stance === "BEAR" ? "against it" : stance.toLowerCase()}
    </Chip>
  );
}

function when(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
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
    <li
      id={`item-${source.id}`}
      className={`flex scroll-mt-4 flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 ${
        unapproved ? "bg-caution/5" : ""
      }`}
    >
      <div className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium">{source.name}</span>
          <Tier tier={source.trust_tier} />
          {unapproved ? (
            <Chip tone="caution">waiting for you</Chip>
          ) : source.is_active ? (
            <Chip tone="good">reading</Chip>
          ) : (
            <Chip>off</Chip>
          )}
        </span>
        {source.notes && (
          <span className="mt-0.5 block text-xs text-muted-foreground">{source.notes}</span>
        )}
      </div>
      {unapproved ? (
        <Button size="sm" disabled={busy} onClick={() => onApprove(source.id)}>
          Start reading it
        </Button>
      ) : (
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          {source.is_active ? "On" : "Off"}
          <Switch
            checked={source.is_active}
            disabled={busy}
            onCheckedChange={(next) => onToggle(source.id, next)}
            aria-label={`Read ${source.name}`}
          />
        </label>
      )}
    </li>
  );
}

/* Adding a channel.
 *
 * ⚠ **This exists because the first channels were measurably the wrong ones.** Read on 24 Sep
 * 2026: across twelve recent uploads they named zero NSE-listed companies between them. A
 * finding is only useful if the thing it is about can be changed — so changing it lives here,
 * next to the evidence, rather than in a seed script only one person can run.
 *
 * ⚠ Paste anything. The channel id the uploads feed needs is not something anyone has to hand;
 * what people have is the address bar. */
function AddChannel({
  onAdd,
  busy,
}: {
  onAdd: (pasted: string, notes: string) => Promise<void>;
  busy: boolean;
}) {
  const [pasted, setPasted] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pasted.trim()) return;
    setError(null);
    try {
      await onAdd(pasted.trim(), notes.trim());
      setPasted("");
      setNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "that channel could not be added");
    }
  };

  const field =
    "min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 py-2 text-sm outline-none focus:ring-2 focus:ring-ring";

  return (
    <form onSubmit={submit} className="border-t border-border bg-muted/20 px-4 py-3">
      <p className="text-xs font-semibold">Add a YouTube channel</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          placeholder="youtube.com/@channel, a handle, or a channel id"
          aria-label="Channel link or handle"
          className={field}
        />
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Why it is worth reading (optional)"
          aria-label="Why it is worth reading"
          className={field}
        />
        <Button type="submit" size="sm" variant="outline" disabled={busy || !pasted.trim()}>
          <Plus className="size-3.5" /> Add
        </Button>
      </div>
      {error && <p className="mt-1.5 text-xs text-bad">{error}</p>}
      <p className="mt-1.5 text-xs text-muted-foreground">
        It arrives switched off and waits above for you to start reading it.
      </p>
    </form>
  );
}

function HeardRow({ item }: { item: Heard }) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm font-medium">{item.symbol}</span>
        {/* ⚠ Shown, never filtered on. A reading list that hid what you already own would hide
            every piece of bad news about it — the half that actually costs money. */}
        {item.is_held && <Chip tone="accent">you hold it</Chip>}
        <Stance stance={item.stance} />
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <Tier tier={item.trust_tier} />
          {item.source}
          {when(item.published_at) && <>· {when(item.published_at)}</>}
        </span>
      </div>
      {item.excerpt && (
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="underline-offset-2 hover:text-foreground hover:underline"
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

export default function ReadingPanel({ onChanged }: { onChanged?: () => void }) {
  const [data, setData] = useState<Reading | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getReading()
      .then((d) => {
        setData(d);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (failed) {
    return (
      <Callout tone="caution" title="Sources could not be loaded">
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

  // Waiting first, then what is being read, then what is switched off.
  const sources = [...data.sources].sort((a, b) => {
    const rank = (s: Source) => (s.approved_at == null ? 0 : s.is_active ? 1 : 2);
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
  const reading = data.sources.filter((s) => s.approved_at != null && s.is_active).length;
  const record = data.attribution.filter((a) => a.named > 0);

  return (
    <div className="space-y-4">
      <Section
        icon={Radio}
        title="Where it reads from"
        count={data.awaiting_approval}
        countTone="accent"
        collapsible={false}
        summary={`${reading} being read · a filing is the company's own word, commentary is not — and commentary alone can never carry a suggestion`}
        flush
      >
        <ul className="divide-y divide-border">
          {sources.map((s) => (
            <SourceRow
              key={s.id}
              source={s}
              busy={busy}
              onApprove={(id) => act(() => api.approveSource(id))}
              onToggle={(id, next) => act(() => api.setSourceActive(id, next))}
            />
          ))}
        </ul>
        <AddChannel
          busy={busy}
          onAdd={async (pasted, notes) => {
            await api.addYoutubeChannel(pasted, notes);
            load();
            onChanged?.();
          }}
        />
        {error && (
          <p className="px-4 pb-3 text-sm text-bad" role="alert">
            {error}
          </p>
        )}
      </Section>

      <Section
        icon={Ear}
        memory="sources.heard"
        title="Heard in the last month"
        count={data.heard.length}
        summary="Every company a source named — held or not, acted on or not"
        flush={data.heard.length > 0}
      >
        {data.heard.length === 0 ? (
          <Quiet icon={Ear}>
            Nothing yet has named a company you track. That is a finding about the sources rather
            than a fault — it is what this list is for.
          </Quiet>
        ) : (
          <ul className="divide-y divide-border">
            {data.heard.map((h, i) => (
              <HeardRow key={`${h.symbol}-${h.published_at}-${i}`} item={h} />
            ))}
          </ul>
        )}
      </Section>

      {record.length > 0 && (
        <Section
          icon={BarChart3}
          memory="sources.record"
          title="Each source's record"
          summary="How often what a source said turned out right — withheld until there is enough to say"
          flush
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-4 py-2 text-left font-medium">
                    Source
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Named
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Took a side
                  </th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">
                    Right so far
                  </th>
                </tr>
              </thead>
              <tbody>
                {record.map((a) => (
                  <tr key={a.source} className="border-t border-border align-top">
                    <th scope="row" className="px-4 py-2.5 text-left font-medium">
                      {a.source}
                      <span className="mt-1 block">
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
                    {/* ⚠ "—" until there are enough settled calls. A hit rate over six reads
                        exactly like one over six hundred. */}
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {a.hit_rate.value == null ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        `${Math.round(Number(a.hit_rate.value) * 100)}%`
                      )}
                      <span className="ml-auto block max-w-[16rem] text-xs font-normal text-muted-foreground">
                        {a.hit_rate.detail}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}
