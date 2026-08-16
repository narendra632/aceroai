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

const UNDO_MS = 7000;

type ToastItem = {
  id: number;
  message: string;
  variant: "success" | "error";
  action?: { label: string; onAction: () => void | Promise<void> };
  duration: number;
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([]);
  const nextId = React.useRef(0);

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
          // errors linger: the user may need to read them, and there is nothing to undo
          duration: options?.duration ?? (variant === "error" ? 8000 : 4000),
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

  const dismiss = (id: number) => setItems((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={api}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        {items.map((t) => (
          <ToastPrimitive.Root
            key={t.id}
            duration={t.duration}
            onOpenChange={(open) => !open && dismiss(t.id)}
            className={cn(
              "flex items-center gap-3 rounded-xl border bg-card px-4 py-3 shadow-lg",
              "data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom-2",
              "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
              "data-[swipe=end]:animate-out data-[swipe=end]:fade-out-0",
              t.variant === "error" ? "border-destructive/40" : "border-border",
            )}
          >
            {t.variant === "error" ? (
              <AlertTriangle className="size-4 shrink-0 text-destructive" />
            ) : (
              <Check className="size-4 shrink-0 text-primary" />
            )}
            <ToastPrimitive.Description className="min-w-0 flex-1 text-sm">
              {t.message}
            </ToastPrimitive.Description>
            {t.action && (
              <ToastPrimitive.Action
                asChild
                altText={t.action.label}
                onClick={() => void t.action?.onAction()}
              >
                <button
                  className={cn(
                    "shrink-0 rounded-md px-2.5 py-1.5 text-sm font-medium text-primary",
                    "transition-colors hover:bg-accent focus-visible:ring-[3px]",
                    "focus-visible:ring-ring/50 focus-visible:outline-none",
                  )}
                >
                  {t.action.label}
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
        ))}
        {/* bottom on mobile (thumb-reachable, clear of the composer), bottom-right on desktop */}
        <ToastPrimitive.Viewport
          className={cn(
            "fixed bottom-0 z-60 flex w-full flex-col gap-2 p-4 outline-none",
            "sm:right-0 sm:bottom-0 sm:w-auto sm:max-w-sm",
          )}
        />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}
