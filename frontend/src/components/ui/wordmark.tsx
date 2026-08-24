/* The Acero wordmark, in whichever theme is active.
 *
 * Two files rather than one, because the mark bakes its colours into pixels: the word
 * "acero" is near-black ink, which is invisible on a dark background. A CSS filter would
 * have been one line and wrong — `invert()` would flip the clay stroke too, turning the
 * brand colour teal.
 *
 * Swapped with `dark:` classes rather than JavaScript so there is no flash of the wrong
 * one before hydration: `index.html` sets the `dark` class before first paint, so the right
 * image is chosen by CSS on the very first frame.
 *
 * The alt text lives on one of them and the other is `aria-hidden`, so a screen reader
 * hears "Acero" once rather than twice.
 */

import { cn } from "@/lib/utils";

export default function Wordmark({ className }: { className?: string }) {
  return (
    <>
      <img
        src="/wordmark.png"
        alt="Acero"
        // Intrinsic size given so the layout does not jump while it loads.
        width={720}
        height={179}
        className={cn("block dark:hidden", className)}
      />
      <img
        src="/wordmark-dark.png"
        alt=""
        aria-hidden
        width={720}
        height={179}
        className={cn("hidden dark:block", className)}
      />
    </>
  );
}
