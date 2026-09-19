import { Info } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/** An "i" that explains something on hover or tap, so the page can stay short.
 *
 *  ⚠ Only ever for elaboration. Anything a reader needs in order to read the number
 *  correctly — whether it is per year or a total, what period it covers — belongs on the card
 *  itself: a tooltip is invisible to someone scanning, and on a phone it costs a deliberate
 *  tap. `asChild` is deliberately not used on the trigger: a real <button> is focusable, so
 *  the note is reachable by keyboard too.
 */
export function InfoTip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={label}
        className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="size-3.5" aria-hidden="true" />
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-pretty leading-relaxed">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}
