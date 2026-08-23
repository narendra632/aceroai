import type { LearnConstants } from "@/lib/api";

/* Resolve `{recall_k}` in a sentence against the live configuration.
 *
 * The rule the whole Learn section rests on: content never writes a number the system
 * decides. It writes a placeholder, and this fills it in from what the server actually
 * uses right now.
 */

const TOKEN = /\{(\w+)\}/g;

/** Numbers are formatted for reading, not for parsing — 16000 is `16,000`, and 0.52 keeps
 *  its decimals rather than being rounded into a different claim. */
function format(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString() : String(value);
}

export function interpolate(text: string, constants: LearnConstants | null): string {
  if (!constants) return text;
  return text.replace(TOKEN, (whole, key: string) => {
    const value = (constants as unknown as Record<string, number | undefined>)[key];
    // An unresolved token is left VISIBLE, on purpose. `undefined` in a sentence reads as
    // a rendering bug; a bare `{recall_k}` reads as a missing number, which is what it is.
    // Silently dropping it would be worst of all — the sentence would still scan, and
    // teach something incomplete without anyone noticing.
    return typeof value === "number" ? format(value) : whole;
  });
}
