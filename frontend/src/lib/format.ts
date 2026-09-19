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
 *  shown, and the rate lives in one place so it can be corrected.
 *
 *  ⚠ The name carries the unit ON PURPOSE. This was `formatINR`, which is a trap next to
 *  the Investments page: called on a real rupee figure it renders ₹89,015 as ₹78,33,320 —
 *  a plausible number, wrong by 88x, that nobody would question. For actual rupees use
 *  `formatRupees`, which takes a string and multiplies by nothing. */
export const USD_TO_INR = 88;

export function approxINRFromUSD(usd: number): string {
  const inr = usd * USD_TO_INR;
  if (inr === 0) return "₹0";
  if (inr < 1) return `₹${inr.toFixed(2)}`;
  if (inr < 100) return `₹${inr.toFixed(1)}`;
  return `₹${Math.round(inr).toLocaleString("en-IN")}`;
}

/* --- real money -----------------------------------------------------------------------
 *
 * Everything below takes a STRING, because that is how the server sends money: an exact
 * decimal that has never been through a float. These format it and never compute with it.
 * If a component finds itself needing to add two figures, the addition belongs on the
 * server — see `services/investments/overview.py`.
 */

/** ₹1,23,456 — Indian digit grouping, which is not what `toLocaleString()` gives by
 *  default in every runtime. Whole rupees above 100; paise below, where they are the
 *  difference between "nothing" and "something". */
export function formatRupees(
  value: string | null | undefined,
  opts: { paise?: boolean } = {},
): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const decimals = opts.paise || abs < 100 ? 2 : 0;
  return `${sign}₹${abs.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

/** A ratio the server computed, as a signed percentage: "+7.34%".
 *
 *  ⚠ The server sends a FRACTION (0.0734), already divided in exact decimal. Multiplying
 *  by 100 here is presentation, not arithmetic on money — the figure's correctness was
 *  settled before it left the server. */
export function formatSignedPct(
  value: string | null | undefined,
  digits = 2,
): string {
  if (value == null) return "—";
  const n = Number(value) * 100;
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

/** A quantity: whole where it is whole, trimmed where it is fractional. Never rounded to a
 *  fixed scale — 0.86242900 units of a fractional share is the fact, and 0.86 is not. */
export function formatQuantity(value: string): string {
  const trimmed = value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
  const n = Number(trimmed);
  return Number.isFinite(n) && Number.isInteger(n)
    ? String(n)
    : trimmed;
}

/** A price — money per unit — from the server's exact decimal string.
 *
 *  ⚠ Rounding for DISPLAY is not computing. The rule that money never becomes a float is
 *  about arithmetic: never add, subtract or divide two figures here. Reducing
 *  `741.7469696969696969696969697` to `₹741.75` to put it on a screen is the whole job, and
 *  a double carries ~15 significant digits — far more than the 2 to 8 decimals shown.
 *
 *  The scale adapts because a price can be ₹4,133.20 or ₹0.84: two decimals on Dogecoin
 *  would render most of a crypto holding as its rounding error.
 */
export function formatPrice(
  value: string | null | undefined,
  currency = "INR",
): string {
  if (value == null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const decimals = abs >= 1 ? 2 : abs >= 0.01 ? 4 : 8;
  const symbol = currency === "INR" ? "₹" : "$";
  const body =
    currency === "INR"
      ? Math.abs(n).toLocaleString("en-IN", {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        })
      : Math.abs(n).toFixed(decimals);
  // Trailing zeros past two places say "measured to eight decimals", which a typed price
  // is not. Keep two, drop the rest: ₹787.800000 -> ₹787.80, ₹0.84000000 -> ₹0.84.
  const trimmed = body.includes(".")
    ? body.replace(/(\.\d\d)(\d*?)0+$/, "$1$2").replace(/(\.\d*[1-9])0+$/, "$1")
    : body;
  return `${n < 0 ? "-" : ""}${symbol}${trimmed}`;
}

/** "27 Apr 2027" — with the year, always.
 *
 *  ⚠ `formatDay` omits it, which is right on a chart axis and wrong on a holding-period
 *  boundary: a lot bought on 27 Apr becomes long-term on 27 Apr of the FOLLOWING year, and
 *  "230 days to long-term · Apr 27" reads as though it were already there.
 */
export function formatDateFull(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
