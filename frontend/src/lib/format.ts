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
