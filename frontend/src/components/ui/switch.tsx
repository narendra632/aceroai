import * as React from "react";
import { Switch as SwitchPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

/* An on/off control.
 *
 * Replaces a hand-rolled version that had a real defect: the knob was positioned
 * `absolute` with a `top` but **no `left`**. Without a horizontal anchor, an absolutely
 * positioned element falls back to its *static* position — and a `<button>` centres its
 * children, so the knob started centred rather than at the left edge. The `translate-x`
 * that was supposed to move it across the track instead pushed it past the right edge,
 * where it sat outside the pill and, being near-black on a dark page, was invisible.
 *
 * The switch therefore rendered as a featureless coloured blob when on, with no indication
 * it was a switch at all.
 *
 * Radix drives the knob from `data-state` instead, and brings keyboard support (space and
 * enter), the correct `role="switch"` and `aria-checked`, and form semantics — all of which
 * the hand-rolled one either lacked or had to reimplement.
 *
 * The track uses `--muted` rather than `--input` when off: `--input` is tuned for the
 * inside of a text field, which is nearly the page colour, so an off switch read as a hole
 * rather than a control.
 */

function Switch({
  className,
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-transparent",
        "transition-colors outline-none",
        "focus-visible:ring-[3px] focus-visible:ring-ring/50",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "data-[state=checked]:bg-primary data-[state=unchecked]:bg-muted",
        // A visible edge when off, so the control still reads as a control against a card
        // background that is close to the track colour.
        "data-[state=unchecked]:border-border",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block size-5 rounded-full bg-background shadow-sm ring-0",
          "transition-transform",
          // Anchored by flex, not by absolute positioning — which is what went wrong
          // before. 0.125rem of travel keeps a 2px gap at each end of an 11/6 track.
          "data-[state=checked]:translate-x-[1.375rem] data-[state=unchecked]:translate-x-0.5",
        )}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
