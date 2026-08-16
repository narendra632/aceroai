import * as React from "react";
import { Dialog as DialogPrimitive, VisuallyHidden } from "radix-ui";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/* A slide-over panel: from the bottom on mobile, from the right on desktop.
   Built on Radix Dialog rather than a hand-rolled div, which buys focus trapping,
   Escape handling, scroll locking, and correct aria roles — three of which are easy
   to get subtly wrong and one of which (focus) makes the panel unusable by keyboard
   if missed. */

const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetClose = DialogPrimitive.Close;

function SheetContent({
  className,
  children,
  title,
  description,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  /** Required by Radix for screen readers; pass a visible node or a plain string. */
  title: React.ReactNode;
  description?: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className={cn(
          "fixed inset-0 z-40 bg-black/40 animate-in fade-in-0",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
        )}
      />
      <DialogPrimitive.Content
        data-slot="sheet-content"
        className={cn(
          "fixed z-50 flex flex-col gap-4 bg-card shadow-xl outline-none",
          // mobile: bottom sheet, capped so the page stays visible behind it
          "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-2xl border-t border-border",
          "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom",
          "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom",
          // desktop: right-hand panel, full height
          "sm:inset-y-0 sm:right-0 sm:left-auto sm:max-h-none sm:w-[26rem] sm:rounded-none",
          "sm:border-t-0 sm:border-l",
          "sm:data-[state=open]:slide-in-from-right sm:data-[state=closed]:slide-out-to-right",
          "duration-200",
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="sr-only">
              {description}
            </DialogPrimitive.Description>
          ) : (
            <VisuallyHidden.Root>
              <DialogPrimitive.Description>Details panel</DialogPrimitive.Description>
            </VisuallyHidden.Root>
          )}
          <DialogPrimitive.Close
            aria-label="Close"
            className={cn(
              "grid size-11 shrink-0 place-items-center rounded-lg text-muted-foreground",
              "transition-colors hover:bg-accent hover:text-foreground",
              "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
            )}
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "sticky bottom-0 -mx-4 mt-2 flex gap-2 border-t border-border bg-card px-4 pt-3 pb-1",
        className,
      )}
      {...props}
    />
  );
}

export { Sheet, SheetClose, SheetContent, SheetFooter, SheetTrigger };
