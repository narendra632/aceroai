/* Display rules for the Investments page, in one place so the table, the sheet and the
 * history cannot drift apart on what a thing is called or coloured.
 *
 * Nothing here computes money. Every figure arrives from the server already exact; these
 * functions choose words, icons and hues for it.
 */

import type { Tone } from "@/components/investments/kit";
import type { AssetClass, Holding } from "@/lib/api";

export const ASSET_LABELS: Record<AssetClass, string> = {
  EQUITY_IN: "Indian equity",
  EQUITY_US: "US equity",
  MF_IN: "Mutual funds",
  CRYPTO: "Crypto",
};

/** Fixed order, so a hue follows the ASSET CLASS and never its rank. A filter that changes
 *  what is on screen must not repaint what survives. */
export const ASSET_ORDER: AssetClass[] = ["EQUITY_IN", "MF_IN", "EQUITY_US", "CRYPTO"];

export const ASSET_COLORS: Record<AssetClass, string> = {
  EQUITY_IN: "var(--series-1)",
  MF_IN: "var(--series-2)",
  EQUITY_US: "var(--series-3)",
  CRYPTO: "var(--series-4)",
};

/** Gain, loss, or neither — as a WORD, so the caller can pick a glyph as well as a colour.
 *  ⚠ Direction is never carried by colour alone: a red number and a green number are the
 *  same number to a reader who cannot tell them apart. */
export function direction(value: string | null): "up" | "down" | "flat" {
  if (value == null) return "flat";
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export function directionClass(value: string | null): string {
  const d = direction(value);
  if (d === "up") return "text-emerald-700 dark:text-emerald-400";
  if (d === "down") return "text-red-700 dark:text-red-400";
  return "text-muted-foreground";
}

/** ▲ / ▼ / — . Paired with the colour, never replaced by it. */
export function directionGlyph(value: string | null): string {
  const d = direction(value);
  return d === "up" ? "▲" : d === "down" ? "▼" : "–";
}

/** "3 days", "2 months", "long-term" — the countdown a holder actually asks about. */
export function longTermText(holding: Holding): string | null {
  if (holding.asset_class === "CRYPTO") return null;
  const days = holding.days_to_long_term;
  if (days == null) return "long-term";
  if (days <= 0) return "long-term";
  if (days === 1) return "1 day to long-term";
  if (days < 45) return `${days} days to long-term`;
  return `${Math.round(days / 30)} months to long-term`;
}

const SOURCE_LABELS: Record<string, string> = {
  NSE: "NSE",
  ANGEL_ONE: "Angel One",
  COINGECKO: "CoinGecko",
  BINANCE: "Binance, in USD at that day's rate",
  TWELVE_DATA: "Twelve Data",
  AMFI: "AMFI",
  USER: "typed",
};

/** Where a price came from, in words. An unknown source is shown as-is rather than hidden:
 *  a price whose origin cannot be named is exactly the one worth questioning. */
export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source.toLowerCase().replaceAll("_", " ");
}

/** Why a holding shows no value. Always a sentence, never a dash on its own. */
export function unpricedReason(holding: Holding): string {
  return holding.currency === "INR"
    ? "No price recorded yet"
    : `No price or ${holding.currency}/INR rate recorded yet`;
}

export function groupByAssetClass(holdings: Holding[]): [AssetClass, Holding[]][] {
  const groups = new Map<AssetClass, Holding[]>();
  for (const h of holdings) {
    const list = groups.get(h.asset_class) ?? [];
    list.push(h);
    groups.set(h.asset_class, list);
  }
  return ASSET_ORDER.filter((k) => groups.has(k)).map((k) => [k, groups.get(k)!]);
}

/** Numeric only for SORTING and chart geometry — never for anything displayed. */
export function num(value: string | null): number {
  if (value == null) return Number.NEGATIVE_INFINITY;
  const n = Number(value);
  return Number.isFinite(n) ? n : Number.NEGATIVE_INFINITY;
}

/* --- the words and tones the research half uses, in one place ----------------------------- */


/** The four boxes, and the two ways of not being in one.
 *
 *  ⚠ Q2 and Q4 block a purchase outright, so they read as what they MEAN and wear the "bad"
 *  tone. BORDERLINE is a refusal to convict on a partial reading — neutral, never red: it is
 *  not a verdict against the company. */
export const QUADRANT: Record<string, { label: string; tone: Tone }> = {
  Q1: { label: "Quality, and the story running", tone: "good" },
  Q3: { label: "Quality, quietly", tone: "info" },
  Q2: { label: "A story without a business", tone: "bad" },
  Q4: { label: "Cheap for a reason", tone: "bad" },
  BORDERLINE: { label: "Too little read to judge", tone: "neutral" },
  UNKNOWN: { label: "Nothing read yet", tone: "neutral" },
};

/** The ten red flags by what they ask, in a few words. The full question travels with each
 *  flag from the server and is shown beside this — these are for scanning, not for judging. */
export const FLAG_NAMES: Record<number, string> = {
  1: "Hard to understand, or easily made obsolete",
  2: "Weak or falling returns",
  3: "Must spend heavily just to stand still",
  4: "Value-destroying deals or buybacks",
  5: "Management spin",
  6: "Price ran ahead of profit",
  7: "Needs a high share price or cheap money",
  8: "Margins shrinking as it grows",
  9: "A hype-driven story",
  10: "Sharp swings in the market's mood",
};

/** What a suggestion proposes doing, in words. */
export const ACTION_WORDS: Record<string, string> = {
  INITIATE: "Start a position",
  ADD: "Add to it",
  HOLD: "Hold",
  TRIM: "Trim",
  EXIT: "Sell out",
  ACCUMULATE_POOL: "Set money aside",
};

/** Which rule refused a suggestion, as the reason a person would give. */
export const GATE_WORDS: Record<string, string> = {
  G1_framework: "its place in the framework",
  G2_quadrant: "business and price together",
  G3_margin_of_safety: "the price",
  G4_invalidation: "nothing would prove it wrong",
  G6_cooling_off: "refused too recently",
  G7_corporate_action: "an unrecorded split or bonus",
  G8_price_age: "the price is too old",
  G9_volume: "enough suggestions for now",
  G11_confidence: "not confident enough",
};

/** How much weight a source's word can carry, as a word and a tone. */
export const TIER: Record<number, { label: string; tone: Tone }> = {
  1: { label: "filing", tone: "good" },
  2: { label: "press", tone: "neutral" },
  3: { label: "commentary", tone: "caution" },
};

/** "3 days ago", "5 weeks ago" — the question a waiting list is asked is "how long", and a
 *  date makes the reader do the arithmetic. */
export function ageText(days: number): string {
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  return `${Math.round(days / 30)} months ago`;
}
