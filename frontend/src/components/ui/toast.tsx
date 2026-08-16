import * as React from "react";
import { Toast as ToastPrimitive } from "radix-ui";
import { AlertTriangle, Check, X } from "lucide-react";

import { ToastContext, type ToastApi, type ToastOptions } from "@/hooks/useToast";
import { cn } from "@/lib/utils";

/* Action feedback, and the carrier for Undo.
   Before this, a save that worked and a save that failed looked identical: nothing
   happened. Deletes are immediate and reversible rather than gated behind a confirm
   dialog, so this component is what makes destructive actions safe.
   The context and `useToast` live in hooks/useToast.ts — see the note there. */

const PLAIN_MS = 3000; // a simple confirmation — read at a glance, then gone
const ERROR_MS = 6000; // failures need longer; there is usually something to read
const UNDO_MS = 7000; // long enough to notice the mistake and reach the button

/** Radix's own timer pauses whenever the document loses focus or the pointer is over
 *  the viewport. Since the viewport is a strip across the bottom of the screen, a
 *  cursor resting there froze toasts indefinitely. We drive dismissal ourselves, so
 *  this effectively disables Radix's timer while keeping its a11y and swipe support. */
const RADIX_TIMER_OFF = 1_000_000_000;

type ToastItem = {
  id: number;
  message: string;
  variant: "success" | "error";
  action?: { label: string; onAction: () => void | Promise<void> };
  duration: number;
};

function ToastRow({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  // Only actionable toasts pause on hover — you may need a moment to reach "Undo".
  // A plain confirmation should leave on schedule no matter where the cursor sits.
  const pausable = !!item.action;
  const [paused, setPaused] = React.useState(false);

  React.useEffect(() => {
    if (paused) return;
    const timer = setTimeout(() => onDismiss(item.id), item.duration);
    return () => clearTimeout(timer);
  }, [paused, item.id, item.duration, onDismiss]);

  return (
    <ToastPrimitive.Root
      duration={RADIX_TIMER_OFF}
      onOpenChange={(open) => !open && onDismiss(item.id)}
      onMouseEnter={pausable ? () => setPaused(true) : undefined}
      onMouseLeave={pausable ? () => setPaused(false) : undefined}
      onFocusCapture={pausable ? () => setPaused(true) : undefined}
      onBlurCapture={pausable ? () => setPaused(false) : undefined}
      className={cn(
        "flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-lg",
        "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom-2",
        "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
        "data-[swipe=end]:animate-out data-[swipe=end]:fade-out-0",
        item.variant === "error" ? "border-destructive/40" : "border-border",
      )}
    >
      {item.variant === "error" ? (
        <AlertTriangle className="size-4 shrink-0 text-destructive" />
      ) : (
        <Check className="size-4 shrink-0 text-primary" />
      )}
      <ToastPrimitive.Description className="min-w-0 flex-1 text-sm">
        {item.message}
      </ToastPrimitive.Description>
      {item.action && (
        <ToastPrimitive.Action
          asChild
          altText={item.action.label}
          onClick={() => void item.action?.onAction()}
        >
          <button
            className={cn(
              "shrink-0 rounded-md px-2.5 py-1.5 text-sm font-medium text-primary",
              "transition-colors hover:bg-accent focus-visible:ring-[3px]",
              "focus-visible:ring-ring/50 focus-visible:outline-none",
            )}
          >
            {item.action.label}
          </button>
        </ToastPrimitive.Action>
      )}
      <ToastPrimitive.Close
        aria-label="Dismiss"
        className="grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent"
      >
        <X className="size-3.5" />
      </ToastPrimitive.Close>
    </ToastPrimitive.Root>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const nextId = React.useRef(0);

  const dismiss = React.useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = React.useCallback(
    (message: string, variant: ToastItem["variant"], options?: ToastOptions) => {
      const id = nextId.current++;
      setItems((prev) => [
        ...prev,
        {
          id,
          message,
          variant,
          action: options?.action,
          duration:
            options?.duration ??
            (options?.action ? UNDO_MS : variant === "error" ? ERROR_MS : PLAIN_MS),
        },
      ]);
    },
    [],
  );

  const api = React.useMemo<ToastApi>(
    () => ({
      success: (m, o) => push(m, "success", o),
      error: (m, o) => push(m, "error", o),
      undo: (m, onUndo) =>
        push(m, "success", { action: { label: "Undo", onAction: onUndo }, duration: UNDO_MS }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        {items.map((t) => (
          <ToastRow key={t.id} item={t} onDismiss={dismiss} />
        ))}
        {/* bottom on mobile (thumb-reachable, clear of the composer), bottom-right on
            desktop. `pointer-events-none` on the strip so an empty viewport can never
            swallow clicks meant for the page beneath it. */}
        <ToastPrimitive.Viewport
          className={cn(
            "pointer-events-none fixed bottom-0 z-60 flex w-full flex-col gap-2 p-4 outline-none",
            "sm:right-0 sm:bottom-0 sm:w-auto sm:max-w-sm",
            "[&>*]:pointer-events-auto",
          )}
        />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
