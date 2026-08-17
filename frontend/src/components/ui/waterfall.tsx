import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

/* One turn, broken into the stages that made it up.
 *
 * This is the view the whole observability section exists for. It is what made a 12-second
 * embedding stall obvious once — by reading raw logs live, at the moment it happened. Here
 * it is a click, for any turn, later.
 *
 * No charting library does waterfalls, so this was custom work regardless of that decision.
 *
 * `first_token` is deliberately drawn differently: every other stage is a DURATION, but
 * that one is a MOMENT measured from the start of the turn. Drawing it as a bar beside the
 * others would double-count time and make the total look wrong.
 */

export type Span = {
  name: string;
  seq: number;
  duration_ms: number | null;
  meta: Record<string, unknown> | null;
};

const FIRST_TOKEN = "first_token";

/** Plain-English names. The stage keys are internal; a person reading this page should not
 *  have to know what `persist_user` means. */
const LABELS: Record<string, string> = {
  persist_user: "Save your message",
  memory_recall: "Recall what it knows",
  build_context: "Assemble the prompt",
  persist_assistant: "Save the reply",
  embed: "Embed the text",
  pgvector: "Search the memory",
  extract: "Learn from the turn",
  embed_facts: "Embed new facts",
  first_token: "First word appears",
};

function label(name: string): string {
  if (LABELS[name]) return LABELS[name];
  if (name.startsWith("llm_round")) return `Model, round ${name.replace("llm_round", "")}`;
  if (name.startsWith("tool:")) return `Tool: ${name.slice(5)}`;
  return name;
}

export function Waterfall({
  spans,
  totalMs,
  className,
}: {
  spans: Span[];
  totalMs: number | null;
  className?: string;
}) {
  const stages = spans.filter((s) => s.name !== FIRST_TOKEN);
  const firstToken = spans.find((s) => s.name === FIRST_TOKEN);
  const scale = Math.max(totalMs ?? 0, ...stages.map((s) => s.duration_ms ?? 0), 1);

  if (stages.length === 0) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        No stage detail was recorded for this call.
      </p>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      {stages.map((s) => {
        const ms = s.duration_ms ?? 0;
        const share = ms / scale;
        // The biggest stage is the answer to "why was this slow", so mark it.
        const dominant = ms === Math.max(...stages.map((x) => x.duration_ms ?? 0)) && share > 0.35;
        return (
          <div key={`${s.seq}-${s.name}`}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">
                {label(s.name)}
                {dominant && (
                  <span className="ml-2 rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground">
                    most of the time
                  </span>
                )}
              </span>
              <span
                className="shrink-0 text-muted-foreground"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {formatMs(ms)}
              </span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(1, share * 100)}%`,
                  background: dominant ? "var(--series-1)" : "var(--viz-edge)",
                }}
              />
            </div>
            {s.meta && Object.keys(s.meta).length > 0 && (
              <p className="mt-1 text-xs text-faint">
                {Object.entries(s.meta)
                  .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`)
                  .join(" · ")}
              </p>
            )}
          </div>
        );
      })}

      {firstToken?.duration_ms != null && (
        <p className="border-t border-border pt-2 text-xs text-muted-foreground">
          First word reached you after{" "}
          <strong className="font-medium text-foreground">
            {formatMs(firstToken.duration_ms)}
          </strong>
          {totalMs ? ` of ${formatMs(totalMs)} total` : ""} — a moment, not a stage, so it
          overlaps the bars above rather than adding to them.
        </p>
      )}
    </div>
  );
}
