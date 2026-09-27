import { ArrowRight, CircleAlert, CircleDot, Telescope } from "lucide-react";

import { severityTone, TAB_LABEL } from "@/components/investments/attention";
import { Section, type Tone } from "@/components/investments/kit";
import { Button } from "@/components/ui/button";
import type { Attention, Waiting } from "@/lib/api";
import { cn } from "@/lib/utils";

/* Everything on the page waiting for a decision, in words, with a way to get to each.
 *
 * ⚠ Found by using the page: "1 company needs your agreement" lived in the third tab, and "1
 * channel waiting for you" inside a collapsed panel at the bottom of that tab. Nothing said
 * either existed until you went looking — and a beginner does not know where to look. The tab
 * counts say WHERE; this says WHAT.
 *
 * ⚠ Absent when nothing is waiting. An empty "Needs you" box on every visit is a box its
 * reader learns to skip, and then skips on the day it matters.
 */

const SEVERITY: Record<
  Waiting["severity"],
  { tone: Tone; icon: typeof CircleAlert; label: string }
> = {
  urgent: { tone: "bad", icon: CircleAlert, label: "Urgent" },
  decide: { tone: "accent", icon: CircleDot, label: "Your decision" },
  lead: { tone: "neutral", icon: Telescope, label: "Worth a look" },
};

type Row = { key: string; items: Waiting[] };

/* ⚠ Leads are folded into one line when there are several. They are the lowest severity and
   the most numerous; listed one per line, five leads would push a fired condition off the
   first screen of a phone. */
function rows(items: Waiting[]): Row[] {
  const leads = items.filter((i) => i.kind === "LEAD");
  const rest = items.filter((i) => i.kind !== "LEAD");
  const out: Row[] = rest.map((i, n) => ({ key: `${i.kind}-${i.ref ?? n}`, items: [i] }));
  if (leads.length === 1) out.push({ key: `lead-${leads[0].ref}`, items: leads });
  if (leads.length > 1) out.push({ key: "leads", items: leads });
  return out;
}

export default function NeedsYou({
  attention,
  onGo,
}: {
  attention: Attention | null;
  onGo: (tab: Waiting["tab"], ref: string | null) => void;
}) {
  if (!attention || attention.items.length === 0) return null;
  const list = rows(attention.items);
  const urgent = attention.items.filter((i) => i.severity === "urgent").length;

  return (
    <Section
      memory="needs-you"
      title="Needs you"
      count={attention.items.length}
      countTone={severityTone(attention.items)}
      summary={
        urgent > 0
          ? `${urgent} urgent — start at the top`
          : "Nothing urgent. Each one opens where it lives."
      }
      tone={urgent > 0 ? "bad" : "accent"}
      flush
    >
      <ul className="divide-y divide-border">
        {list.map((row) => {
          const first = row.items[0];
          const look = SEVERITY[first.severity];
          const Icon = look.icon;
          const text =
            row.items.length > 1
              ? `${row.items.length} companies a source named are worth a look — ${row.items
                  .slice(0, 4)
                  .map((i) => i.symbol)
                  .join(", ")}${row.items.length > 4 ? "…" : ""}`
              : first.text;
          return (
            <li key={row.key} className="flex items-center gap-3 px-3 py-2.5 sm:px-4">
              <Icon
                className={cn(
                  "size-4 shrink-0",
                  look.tone === "bad"
                    ? "text-bad"
                    : look.tone === "accent"
                      ? "text-primary"
                      : "text-muted-foreground",
                )}
                aria-label={look.label}
              />
              <span className="min-w-0 flex-1 text-sm">{text}</span>
              <Button
                size="sm"
                variant="ghost"
                className="shrink-0 text-muted-foreground hover:text-foreground"
                onClick={() => onGo(first.tab, row.items.length > 1 ? null : first.ref)}
              >
                {TAB_LABEL[first.tab]}
                <ArrowRight className="size-3.5" />
              </Button>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
