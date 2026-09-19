/* Display rules for the Investments page, in one place so the table, the sheet and the
 * history cannot drift apart on what a thing is called or coloured.
 *
 * Nothing here computes money. Every figure arrives from the server already exact; these
 * functions choose words, icons and hues for it.
 */

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
