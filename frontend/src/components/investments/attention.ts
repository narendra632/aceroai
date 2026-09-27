import type { Tone } from "@/components/investments/kit";
import type { Waiting } from "@/lib/api";

/** What each part of the page is called where the "needs you" list points to it. */
export const TAB_LABEL: Record<Waiting["tab"], string> = {
  holdings: "Holdings",
  decisions: "Decisions",
  companies: "Companies",
  sources: "Sources",
};

/** The most pressing severity among some items, as the tone their count should wear. */
export function severityTone(items: Waiting[]): Tone {
  if (items.some((i) => i.severity === "urgent")) return "bad";
  if (items.some((i) => i.severity === "decide")) return "accent";
  return "neutral";
}
