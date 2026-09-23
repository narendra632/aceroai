import { useEffect, useState } from "react";
import { Radar } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
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

  return (
    <section className="rounded-xl border border-border bg-card p-3">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <Radar className="size-3.5 text-muted-foreground" />
        Written about lately
        <InfoTip label="How this is worked out">
          Articles about a sector name no company, so nothing would normally
          come of them. The framework knows which chokepoints matter and who
          sits on each, so a theme becomes a list of your own holdings. It is
          something to read, never a reason to act.
        </InfoTip>
      </h2>

      <ul className="mt-2 space-y-1.5">
        {data.themes.map((row) => (
          <li key={row.bottleneck_id} className="text-xs">
            <span className="font-medium">{row.name}</span>
            <span className="text-muted-foreground">
              {" "}
              · {row.mentions} {row.mentions === 1 ? "piece" : "pieces"}
            </span>
            {row.held.length > 0 && (
              <span className="block text-muted-foreground">
                you hold: <span className="text-foreground">{row.held.join(", ")}</span>
              </span>
            )}
            {row.queued.length > 0 && (
              <span className="block text-muted-foreground">
                waiting to be looked at: {row.queued.join(", ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
