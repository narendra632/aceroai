import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

/* A click-opened panel anchored to a trigger.
 *
 * Deliberately NOT a tooltip. Tooltips open on hover, and hover does not exist on a phone —
 * a hover-only control is simply missing there. Radix also gives this focus management and
 * dismiss-on-escape/outside-click for free, which a hand-rolled panel would have to
 * reimplement to be usable with a keyboard.
 */

function Popover({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        collisionPadding={12}
        className={cn(
          // max-w is capped against the viewport, not a fixed pixel width: at 375px a
          // 320px panel with padding overflows the screen and the page scrolls sideways.
          "z-50 w-[min(22rem,calc(100vw-1.5rem))] origin-(--radix-popover-content-transform-origin)",
          "animate-in rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-lg",
          "fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}

export { Popover, PopoverTrigger, PopoverContent }
