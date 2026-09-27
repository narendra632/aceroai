import { useEffect, useState } from "react";
import { Radar } from "lucide-react";

import { Chip, Section } from "@/components/investments/kit";
import * as api from "@/lib/api";
import type { Themes } from "@/lib/api";

/* Themes the reading has been about, and what you hold on each.
 *
 * ⚠ **This is the framework working as a routing table rather than a filing cabinet.** An
 * article about a sector names no company, so the mention matcher sees nothing — but the
 * framework already knows which chokepoints matter and who sits on each, so attention paid
 * to a theme becomes attention paid to a specific set of companies, including ones already
 * held. That is the half that matters most and the half nobody goes looking for.
 *
 * ⚠ **A theme is never evidence.** It raises no proposal and changes no score. It answers one
 * question — what am I exposed to that just got attention — and the answer is a list to read.
 */
export default function ThemesStrip() {
  const [data, setData] = useState<Themes | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getThemes()
      .then((d) => !cancelled && setData(d))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // ⚠ Renders nothing at all when nothing was written about. An empty panel headed "Themes"
  // teaches its reader to skip the space it occupies.
  if (!data || data.themes.length === 0) return null;

  const held = data.themes.filter((t) => t.held.length > 0).length;

  return (
    <Section
      icon={Radar}
      memory="decisions.themes"
      title="Written about lately"
      summary={`${data.themes.length} ${data.themes.length === 1 ? "theme" : "themes"} in what was read${
        held ? ` · ${held} touch${held === 1 ? "es" : ""} what you hold` : ""
      } — something to read, never a reason to act`}
      tip="An article about a sector names no company. The framework knows who sits on each chokepoint, so a theme becomes a list of your own holdings."
      flush
    >
      <ul className="divide-y divide-border">
        {data.themes.map((row) => (
          <li key={row.bottleneck_id} className="px-4 py-2.5 text-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{row.name}</span>
              <span className="text-xs text-muted-foreground">
                {row.mentions} {row.mentions === 1 ? "piece" : "pieces"}
              </span>
            </div>
            {(row.held.length > 0 || row.queued.length > 0) && (
              <div className="mt-1 flex flex-wrap gap-1.5">
                {row.held.map((symbol) => (
                  <Chip key={`h-${symbol}`} tone="accent">
                    you hold {symbol}
                  </Chip>
                ))}
                {row.queued.map((symbol) => (
                  <Chip key={`q-${symbol}`}>waiting: {symbol}</Chip>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}
