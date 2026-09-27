import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Building2,
  Check,
  ChevronRight,
  CircleDashed,
  Compass,
  Landmark,
  Sparkles,
} from "lucide-react";

import { Callout, Chip, Meter, Quiet, Section, type Tone } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import * as api from "@/lib/api";
import type { Bottleneck, Framework, FrameworkAttention, Mapping } from "@/lib/api";
import { FLAG_NAMES, QUADRANT } from "@/lib/investments";
import { cn } from "@/lib/utils";

/* Every company you follow, where it sits in the framework, and what that is worth.
 *
 * ⚠ **Agreeing is the most important control in this module**, and it is easy to mistake for
 * paperwork. The structural score is the one place the system makes a claim about national
 * importance, and a machine that reads enough news will eventually talk itself into believing
 * an unrelated small-cap is strategically essential. The guard is that a placement scores
 * **zero** until a person agrees with it — so the companies waiting for you come first.
 *
 * ⚠ **Every company is visible when the tab opens.** The first version showed a heading and a
 * "Show" button; the twelve companies the tab exists for were one more click away, and a
 * closed heading said nothing about them. Each company is now a row that states its two scores,
 * its verdict, its price against worth and its red flags, and opens for the full reading.
 *
 * Two distinctions are rendered rather than flattened, because collapsing either would print
 * something untrue:
 *
 *   - **"—" (not applicable) is not "0".** SpaceX scores nothing because the framework asks
 *     what INDIA must build, not because it failed a test.
 *   - **"at least 4" is not "4".** A crossing count the notes never established is a floor,
 *     and a floor shown as a finding would mark a company narrow for a documentation reason.
 */

const PART_LABEL: Record<string, string> = {
  roe: "Return on equity",
  roce: "Return on capital",
  cash_conversion: "Profit into cash",
  balance_sheet: "Debt",
  retained_earnings: "Retained earnings",
  margin_of_safety: "Price against worth",
  // ⚠ What a bank is measured on instead. Depreciation, capex and net debt describe a
  // factory; these describe a lender.
  cost_to_income: "Cost to income",
  credit_cost: "Provisions",
  funding_spread: "Funding spread",
};

const COMPONENT_LABEL: Record<string, string> = {
  breadth: "Breadth",
  timing: "Timing",
  crisis: "Crisis",
  commitment: "Commitment",
  investability: "Investability",
};

const WAITING: FrameworkAttention["kind"][] = ["UNMAPPED", "UNAPPROVED", "EXPIRED"];

type Filter = "all" | "held" | "watch" | "you";

function needsYou(m: Mapping): boolean {
  if (m.approved_at == null) return true;
  return m.review_after != null && m.review_after <= new Date().toISOString().slice(0, 10);
}

/** The margin of safety as a chip: how far the price sits from a defensible worth.
 *
 *  ⚠ A price above worth is CAUTION, never "bad": it says nothing against the company, only
 *  that it costs more than the framework will pay for it today. */
function priceChip(m: Mapping): { text: string; tone: Tone } | null {
  const part = m.quality?.parts.find((p) => p.name === "margin_of_safety");
  if (!part || part.value == null) return null;
  const v = Number(part.value);
  const pct = Math.round(Math.abs(v) * 100);
  if (v >= 0.25) return { text: `${pct}% below worth`, tone: "good" };
  if (v >= 0) return { text: `${pct}% below worth`, tone: "neutral" };
  return { text: `${pct}% above worth`, tone: "caution" };
}

function flagsChip(m: Mapping): { text: string; tone: Tone } | null {
  if (m.flags.length === 0) return null;
  const yes = m.flags.filter((f) => f.verdict === "YES").length;
  const known = m.flags.filter((f) => f.verdict !== "UNKNOWN").length;
  if (yes > 0) return { text: `${yes} red flag${yes === 1 ? "" : "s"}`, tone: "caution" };
  if (known > 0) return { text: "no red flags", tone: "neutral" };
  return null;
}

function order(a: Mapping, b: Mapping): number {
  const rank = (m: Mapping) => (needsYou(m) ? 0 : m.is_held ? 1 : 2);
  return (
    rank(a) - rank(b) ||
    Number(b.score.total ?? -1) - Number(a.score.total ?? -1) ||
    a.symbol.localeCompare(b.symbol)
  );
}

export default function FrameworkPanel({
  onChanged,
  arrival,
}: {
  onChanged?: () => void;
  /** The DOM id the "needs you" list sent the reader to, if any. */
  arrival?: string | null;
}) {
  const [data, setData] = useState<Framework | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

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

  // Sent here for a particular company: make sure the filter is not hiding it.
  useEffect(() => {
    if (arrival?.startsWith("item-")) setFilter("all");
  }, [arrival]);

  if (failed) {
    return (
      <Callout tone="caution" title="The framework could not be loaded">
        Reload to try again.
      </Callout>
    );
  }
  if (!data) return null;

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    try {
      await fn();
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "that did not work");
    } finally {
      setBusy(null);
    }
  }

  const waiting = data.attention.filter((a) => WAITING.includes(a.kind));
  const mappings = [...data.mappings].sort(order);
  const counts: Record<Filter, number> = {
    all: mappings.length,
    held: mappings.filter((m) => m.is_held).length,
    watch: mappings.filter((m) => !m.is_held).length,
    you: mappings.filter(needsYou).length,
  };
  const shown = mappings.filter((m) =>
    filter === "held"
      ? m.is_held
      : filter === "watch"
        ? !m.is_held
        : filter === "you"
          ? needsYou(m)
          : true,
  );
  const verdicts = new Map<string, number>();
  for (const m of mappings) {
    if (m.quadrant) verdicts.set(m.quadrant, (verdicts.get(m.quadrant) ?? 0) + 1);
  }

  return (
    <div className="space-y-4">
      {waiting.length > 0 && (
        <Callout
          id="needs-agreement"
          tone="caution"
          title={`${waiting.length} ${waiting.length === 1 ? "company needs" : "companies need"} you`}
        >
          <p>
            A company scores zero until you agree where it sits. That is the guard, not a fault:
            the system may suggest a company matters to India; only you can agree.
          </p>
          <ul className="mt-3 space-y-2">
            {waiting.map((a) => (
              <Waiting
                key={`${a.symbol}-${a.kind}`}
                item={a}
                bottlenecks={data.bottlenecks}
                busy={busy === a.instrument_id}
                onRun={(fn) => run(a.instrument_id ?? a.symbol, fn)}
              />
            ))}
          </ul>
        </Callout>
      )}

      <Section
        icon={Building2}
        title="Companies you follow"
        collapsible={false}
        summary={`Framework version ${data.version} · ${data.mappings.length} companies · open one for the full reading`}
        flush
      >
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Show">
            {(
              [
                ["all", "All"],
                ["held", "Held"],
                ["watch", "Watchlist"],
                ["you", "Needs you"],
              ] as const
            ).map(([key, label]) => (
              <Button
                key={key}
                size="xs"
                variant={filter === key ? "secondary" : "ghost"}
                aria-pressed={filter === key}
                onClick={() => setFilter(key)}
                disabled={counts[key] === 0 && key !== "all"}
              >
                {label} <span className="tabular-nums text-muted-foreground">{counts[key]}</span>
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Q1", "Q3", "BORDERLINE", "Q2", "Q4"]
              .filter((q) => verdicts.get(q))
              .map((q) => (
                <Chip key={q} tone={QUADRANT[q].tone} title={QUADRANT[q].label}>
                  {q === "BORDERLINE" ? "too little read" : q} × {verdicts.get(q)}
                </Chip>
              ))}
          </div>
        </div>

        {shown.length === 0 ? (
          <Quiet className="px-4 py-4">Nothing in this view.</Quiet>
        ) : (
          <ul className="divide-y divide-border">
            {shown.map((m) => (
              <Company
                key={m.id}
                mapping={m}
                bottlenecks={data.bottlenecks}
                imperatives={data.imperatives as Array<{ id: string; name: string }>}
                busy={busy === m.id}
                arrival={arrival ?? null}
                onApprove={() => run(m.id, () => api.approveMapping(m.id))}
                onRemap={(b, off) =>
                  run(m.id, () =>
                    api.remapInstrument(m.id, { b_bottleneck: off ? null : b, off_framework: off }),
                  )
                }
                onRevise={(crosses) =>
                  run(m.id, () => api.reviseCrossings(m.b_bottleneck ?? "", crosses))
                }
              />
            ))}
          </ul>
        )}
      </Section>

      {error && (
        <p className="text-sm text-bad" role="alert">
          {error}
        </p>
      )}

      <Reference framework={data} />
    </div>
  );
}

/** One company waiting for you, with what you can do about it where it is listed.
 *
 *  ⚠ The UNMAPPED case is why this exists. A company followed from the research queue before
 *  its filings were read has no place at all — the old "Review them" button opened a list it
 *  was not in, and nothing anywhere could give it one. Now it can be placed here, by hand or by
 *  asking for a suggestion; either way it then waits for agreement like every other company. */
function Waiting({
  item,
  bottlenecks,
  busy,
  onRun,
}: {
  item: FrameworkAttention;
  bottlenecks: Bottleneck[];
  busy: boolean;
  onRun: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [placing, setPlacing] = useState(false);
  const [choice, setChoice] = useState("");
  const [told, setTold] = useState<string | null>(null);
  const id = item.instrument_id;

  const open = () => {
    const el = document.getElementById(`item-${id}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.querySelector<HTMLButtonElement>("button[aria-expanded='false']")?.click();
  };

  return (
    <li id={item.kind === "UNMAPPED" ? `item-${id}` : undefined} className="scroll-mt-4 rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-foreground">
          <strong>{item.symbol}</strong>{" "}
          {item.kind === "UNMAPPED"
            ? "has no place in the framework yet"
            : item.kind === "EXPIRED"
              ? "— re-confirm where it sits; agreed over a year ago"
              : "— agree where the framework puts it"}
        </p>
        {item.kind === "UNMAPPED" && id ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                void onRun(async () => {
                  const out = await api.suggestPlace(id);
                  setTold(
                    out.placed
                      ? `Suggested ${out.bottleneck} (${Math.round(out.confidence * 100)}% sure): ${out.why}. Open it below and agree if you do.`
                      : `No place suggested — ${out.why}. Place it yourself instead.`,
                  );
                })
              }
            >
              <Sparkles className="size-3.5" />
              {busy ? "Asking…" : "Suggest a place"}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setPlacing((v) => !v)}>
              {placing ? "Cancel" : "Place it myself"}
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={open}>
            Review
            <ChevronRight className="size-3.5" />
          </Button>
        )}
      </div>

      {told && <p className="mt-2 text-xs text-muted-foreground">{told}</p>}

      {placing && id && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Select value={choice} onValueChange={setChoice}>
            <SelectTrigger className="h-9 min-w-0 flex-1 text-xs" aria-label="Bottleneck">
              <SelectValue placeholder="Which bottleneck does it clear?" />
            </SelectTrigger>
            <SelectContent>
              {bottlenecks.map((b) => (
                <SelectItem key={b.id} value={b.id}>
                  {b.id} · {b.name} (unblocks {b.crosses.length})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            disabled={busy || !choice}
            onClick={() =>
              void onRun(async () => {
                await api.placeInstrument(id, { b_bottleneck: choice });
                setPlacing(false);
              })
            }
          >
            Place it
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void onRun(async () => {
                await api.placeInstrument(id, { off_framework: true });
                setPlacing(false);
              })
            }
          >
            Outside the framework
          </Button>
        </div>
      )}
    </li>
  );
}

function Company({
  mapping: m,
  bottlenecks,
  imperatives,
  busy,
  arrival,
  onApprove,
  onRemap,
  onRevise,
}: {
  mapping: Mapping;
  bottlenecks: Bottleneck[];
  imperatives: Array<{ id: string; name: string }>;
  busy: boolean;
  arrival: string | null;
  onApprove: () => void;
  onRemap: (b: string, off: boolean) => void;
  onRevise: (crosses: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const approved = m.approved_at != null;
  const box = QUADRANT[m.quadrant ?? ""];
  const price = priceChip(m);
  const flags = flagsChip(m);
  const waiting = needsYou(m);
  const domId = `item-${m.instrument_id}`;

  useEffect(() => {
    if (arrival === domId) setOpen(true);
  }, [arrival, domId]);

  return (
    <li id={domId} className={cn("scroll-mt-4", waiting && "bg-caution/4")}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="grid w-full grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-3 text-left outline-none hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring xl:grid-cols-[auto_minmax(0,1fr)_auto]"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "mt-1 size-4 text-muted-foreground transition-transform",
            open && "rotate-90",
          )}
        />
        <span className="min-w-0">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 font-semibold">{m.symbol}</span>
            <span className="min-w-0 truncate text-sm text-muted-foreground">{m.name}</span>
          </span>
          <span className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
            <Chip tone={m.is_held ? "accent" : "neutral"}>{m.is_held ? "held" : "watchlist"}</Chip>
            {waiting && (
              <Chip tone="caution" icon={AlertTriangle}>
                {approved ? "re-confirm" : "agree first"}
              </Chip>
            )}
            <span className="min-w-0 truncate">
              {m.off_framework
                ? "Outside the framework"
                : `${m.b_bottleneck} · ${m.bottleneck_name}`}
            </span>
          </span>
        </span>

        {/* ⚠ Fixed columns on a wide screen, so a reader can run an eye down "Business" or "price
            against worth" across every company — the comparison a list like this is for. An
            empty cell keeps its column rather than letting the next chip slide into it. */}
        <span className="col-start-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 xl:col-start-3 xl:grid xl:grid-cols-[7rem_7rem_10.5rem_8rem_6rem] xl:gap-x-3">
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            Fit
            {m.score.total == null ? (
              <span className="font-semibold text-foreground">—</span>
            ) : approved ? (
              <Meter
                value={Number(m.score.total)}
                max={Number(m.score.available) || 10}
                label="How much India needs what it does"
                width="w-10"
              />
            ) : (
              <span className="font-semibold text-foreground">0 until agreed</span>
            )}
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            {m.quality && m.quality.available !== "0" && (
              <>
                Business
                <Meter
                  value={Number(m.quality.earned)}
                  max={Number(m.quality.available)}
                  label="Business quality, of what could be measured"
                  width="w-10"
                />
              </>
            )}
          </span>
          <span className="min-w-0">{box && <Chip tone={box.tone}>{box.label}</Chip>}</span>
          <span className="min-w-0">{price && <Chip tone={price.tone}>{price.text}</Chip>}</span>
          <span className="min-w-0">
            {flags && (
              <Chip tone={flags.tone} icon={flags.tone === "caution" ? AlertTriangle : undefined}>
                {flags.text}
              </Chip>
            )}
          </span>
        </span>
      </button>

      {open && (
        <Detail
          mapping={m}
          bottlenecks={bottlenecks}
          imperatives={imperatives}
          busy={busy}
          onApprove={onApprove}
          onRemap={onRemap}
          onRevise={onRevise}
        />
      )}
    </li>
  );
}

function Detail({
  mapping: m,
  bottlenecks,
  imperatives,
  busy,
  onApprove,
  onRemap,
  onRevise,
}: {
  mapping: Mapping;
  bottlenecks: Bottleneck[];
  imperatives: Array<{ id: string; name: string }>;
  busy: boolean;
  onApprove: () => void;
  onRemap: (b: string, off: boolean) => void;
  onRevise: (crosses: string[]) => void;
}) {
  const [choice, setChoice] = useState(m.b_bottleneck ?? "");
  const [moving, setMoving] = useState(false);
  const [editing, setEditing] = useState(false);
  const [picked, setPicked] = useState<string[]>(m.a_imperatives);
  const approved = m.approved_at != null;
  const q = m.quality;
  const flags = [...m.flags].sort(
    (a, b) =>
      ["YES", "UNKNOWN", "NO"].indexOf(a.verdict) - ["YES", "UNKNOWN", "NO"].indexOf(b.verdict),
  );

  return (
    <div className="space-y-4 border-t border-border bg-muted/20 px-4 py-4 sm:pl-11">
      {m.rationale && <p className="text-sm text-muted-foreground">{m.rationale}</p>}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* --- does India need what it does -------------------------------------------- */}
        <div>
          <p className="flex items-center gap-1.5 text-xs font-semibold">
            <Landmark className="size-3.5 text-muted-foreground" aria-hidden="true" />
            Does India need what it does?
            {m.score.total != null && approved && (
              <span className="font-normal text-muted-foreground">
                {m.score.total} of {m.score.available}
              </span>
            )}
          </p>
          {m.score.unavailable_because && (
            <p className="mt-1.5 text-xs text-muted-foreground">{m.score.unavailable_because}</p>
          )}
          {approved && m.score.total != null && (
            <ul className="mt-2 space-y-2">
              {m.score.components.map((c) => (
                <li key={c.name} className="text-xs">
                  <span className="flex items-center gap-2">
                    <span className="w-24 shrink-0 text-muted-foreground">
                      {COMPONENT_LABEL[c.name] ?? c.name}
                    </span>
                    <Meter
                      value={Number(c.points)}
                      max={Number(c.available)}
                      label={COMPONENT_LABEL[c.name] ?? c.name}
                      width="w-14"
                    />
                  </span>
                  <span className="mt-0.5 block pl-26 text-muted-foreground">{c.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* --- is it a good business at a fair price ----------------------------------- */}
        {q && q.available !== "0" ? (
          <div>
            <p className="flex flex-wrap items-center gap-1.5 text-xs font-semibold">
              <Compass className="size-3.5 text-muted-foreground" aria-hidden="true" />
              Is it a good business, at a fair price?
              {/* ⚠ Both halves, always. "6" alone is meaningless: six of ten is mediocre and six
                  of six is excellent, and the gap is how much has been read. */}
              <span className="font-normal text-muted-foreground">
                {q.earned} of {q.available} measurable
                {q.available !== q.possible && ` (of ${q.possible} its test offers)`}
              </span>
            </p>
            {/* ⚠ Says WHICH limit is binding: "too young to have more" resolves with time;
                "the exchange has not published it" may resolve with a fetch. */}
            <p className="mt-1 text-xs text-muted-foreground">
              {m.years_read} year{m.years_read === 1 ? "" : "s"} of filings read
              {q.years_possible != null &&
                q.years_possible !== m.years_read &&
                ` of ${q.years_possible} possible`}
              {q.history_note && ` — ${q.history_note}`}
            </p>
            <ul className="mt-2 space-y-2">
              {q.parts.map((p) => (
                <li key={p.name} className="text-xs">
                  <span className="flex items-center gap-2">
                    <span className="w-32 shrink-0 text-muted-foreground">
                      {PART_LABEL[p.name] ?? p.name}
                    </span>
                    {/* ⚠ Three renderings for three different facts. A number: measured. "not
                        read": the filings are not in, and a company marked poor for that looks
                        identical to one that is poor. "does not apply": the test never
                        described this kind of company, and that is not a gap anyone can fill. */}
                    {p.applicable === false ? (
                      <Chip>does not apply</Chip>
                    ) : p.points == null ? (
                      <Chip icon={CircleDashed}>not read</Chip>
                    ) : (
                      <Meter
                        value={Number(p.points)}
                        max={Number(p.available)}
                        label={PART_LABEL[p.name] ?? p.name}
                        width="w-14"
                      />
                    )}
                  </span>
                  <span className="mt-0.5 block pl-34 text-muted-foreground">{p.detail}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <Quiet icon={CircleDashed}>Nothing filed has been read for it yet, so it cannot be scored.</Quiet>
        )}
      </div>

      {flags.length > 0 && (
        <div>
          <p className="text-xs font-semibold">Red flags</p>
          <ul className="mt-2 grid gap-x-5 gap-y-1.5 sm:grid-cols-2">
            {flags.map((f) => (
              <li key={f.number} className="flex gap-2 text-xs" title={f.question}>
                {f.verdict === "YES" ? (
                  <AlertTriangle className="mt-px size-3.5 shrink-0 text-caution" aria-label="yes" />
                ) : f.verdict === "NO" ? (
                  <Check className="mt-px size-3.5 shrink-0 text-good" aria-label="no" />
                ) : (
                  <CircleDashed className="mt-px size-3.5 shrink-0 text-faint" aria-label="not answered" />
                )}
                <span>
                  <span className={f.verdict === "YES" ? "font-medium" : "text-muted-foreground"}>
                    {FLAG_NAMES[f.number] ?? `Flag ${f.number}`}
                  </span>
                  <span className="block text-muted-foreground">{f.evidence}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {m.score.breadth_is_floor && !m.off_framework && (
        <Callout tone="caution" title={`Unblocks at least ${m.crosses_a_count} of the ten — maybe more`}>
          Your notes establish the full set for eight bottlenecks and leave this one unstated, so
          the score may be understated.
          {/* ⚠ The control matters as much as the warning. "This may be understated" with no way
              to correct it is information dressed as an action. */}
          <div className="mt-2">
            <Button size="xs" variant="outline" onClick={() => setEditing((v) => !v)}>
              {editing ? "Cancel" : "Set what it actually unblocks"}
            </Button>
          </div>
          {editing && (
            <div className="mt-3">
              <div className="flex flex-wrap gap-1.5">
                {imperatives.map((a) => (
                  <label
                    key={a.id}
                    className="flex cursor-pointer items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
                    title={a.name}
                  >
                    <input
                      type="checkbox"
                      checked={picked.includes(a.id)}
                      onChange={() =>
                        setPicked((cur) =>
                          cur.includes(a.id) ? cur.filter((x) => x !== a.id) : [...cur, a.id],
                        )
                      }
                    />
                    {a.id}
                  </label>
                ))}
              </div>
              <Button
                size="sm"
                className="mt-2"
                disabled={busy || picked.length === 0}
                onClick={() => onRevise(picked)}
              >
                {busy ? "Saving…" : `Save — unblocks ${picked.length}`}
              </Button>
              <p className="mt-1.5 text-xs">
                This changes the framework itself: every company on {m.b_bottleneck} is rescored,
                and a new version is recorded so past decisions keep the rules they used.
              </p>
            </div>
          )}
        </Callout>
      )}

      {m.multiple_is_fallback && !m.off_framework && (
        <p className="flex items-start gap-1.5 text-xs text-caution">
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          {m.multiple_why} — any price-against-worth figure from it is a guess.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {!approved ? (
          <Button size="sm" disabled={busy} onClick={onApprove}>
            <Check className="size-3.5" />
            {busy ? "Saving…" : "Agree with this placement"}
          </Button>
        ) : (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Check className="size-3.5 text-good" />
            Agreed{m.review_after ? ` · check again after ${m.review_after}` : ""}
          </span>
        )}
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setMoving((v) => !v)}>
          {moving ? "Cancel" : "Move it"}
        </Button>
      </div>

      {moving && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-3">
          <Select value={choice} onValueChange={setChoice}>
            <SelectTrigger className="h-9 min-w-0 flex-1 text-xs" aria-label="Bottleneck">
              <SelectValue placeholder="Choose a bottleneck" />
            </SelectTrigger>
            <SelectContent>
              {bottlenecks.map((b) => (
                <SelectItem key={b.id} value={b.id}>
                  {b.id} · {b.name} (unblocks {b.crosses.length})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button size="sm" disabled={busy || !choice} onClick={() => onRemap(choice, false)}>
            Move
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onRemap("", true)}>
            Outside the framework
          </Button>
          <p className="w-full text-xs text-muted-foreground">
            A move is a fresh claim: it scores zero again until you agree with the new place.
          </p>
        </div>
      )}
    </div>
  );
}

/** The framework itself, for reference: the ten things India must build and the bottlenecks
 *  in the way, with who you follow on each. Closed by default — it is the map, not the news. */
function Reference({ framework }: { framework: Framework }) {
  const imperatives = framework.imperatives as Array<{ id: string; name: string }>;
  const on = new Map<string, string[]>();
  for (const m of framework.mappings) {
    if (m.b_bottleneck) on.set(m.b_bottleneck, [...(on.get(m.b_bottleneck) ?? []), m.symbol]);
  }
  return (
    <Section
      icon={Landmark}
      memory="companies.reference"
      defaultOpen={false}
      title="The framework itself"
      summary={`${imperatives.length} things India must build · ${framework.bottlenecks.length} bottlenecks in the way`}
    >
      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <p className="text-xs font-semibold">What India must build</p>
          <ol className="mt-2 space-y-1 text-xs">
            {imperatives.map((a) => (
              <li key={a.id} className="flex gap-2">
                <span className="w-7 shrink-0 font-medium text-muted-foreground">{a.id}</span>
                {a.name}
              </li>
            ))}
          </ol>
        </div>
        <div>
          <p className="text-xs font-semibold">The bottlenecks, and who you follow on each</p>
          <ul className="mt-2 space-y-1.5 text-xs">
            {framework.bottlenecks.map((b) => (
              <li key={b.id} className="flex flex-wrap items-baseline gap-x-2">
                <span className="w-9 shrink-0 font-medium text-muted-foreground">{b.id}</span>
                <span className="min-w-0 flex-1">{b.name}</span>
                <span className="text-muted-foreground">unblocks {b.crosses.length}</span>
                {on.get(b.id) && (
                  <span className="w-full pl-11 text-primary">{on.get(b.id)?.join(", ")}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}
