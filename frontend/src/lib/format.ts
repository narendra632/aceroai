/* Display formatting for numbers that appear on charts and in tables.
 *
 * Separate from `ui/chart.tsx` because React Fast Refresh only works when a module
 * exports components exclusively — the same reason `hooks/useToast.ts` was split out of
 * `ui/toast.tsx`.
 */

export function formatUSD(value: number): string {
  if (value === 0) return "$0";
  // A single cheap turn costs ~$0.0004. Rounding to cents would render most of this
  // app's activity as zero, so small values keep the precision that makes them real.
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)}s` : `${Math.round(ms)}ms`;
}

/** "2026-08-18" -> "18 Aug". Parsed as local midnight, never via Date(iso) which would
 *  treat a bare date as UTC and can show the wrong day. */
export function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** A Date -> "YYYY-MM-DD" using LOCAL calendar parts.
 *
 *  Never via toISOString(): that converts to UTC first, so local midnight on 18 Aug in
 *  IST (UTC+5:30) becomes "2026-08-17". Building chart keys that way made every key miss
 *  the server's, so every day rendered as empty AND a day early — two symptoms, one line.
 */
export function localDayKey(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Rupees alongside dollars. Providers bill in USD, so this is a convenience conversion
 *  at a fixed rate, not an authoritative figure — it is labelled approximate wherever
 *  shown, and the rate lives in one place so it can be corrected. */
export const USD_TO_INR = 88;

export function formatINR(usd: number): string {
  const inr = usd * USD_TO_INR;
  if (inr === 0) return "₹0";
  if (inr < 1) return `₹${inr.toFixed(2)}`;
  if (inr < 100) return `₹${inr.toFixed(1)}`;
  return `₹${Math.round(inr).toLocaleString("en-IN")}`;
}
