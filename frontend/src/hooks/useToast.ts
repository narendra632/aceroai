import { createContext, useContext } from "react";

/* The toast context lives here, apart from the provider component, so that editing
   toast.tsx hot-reloads instead of forcing a full page refresh. (React Fast Refresh
   only hot-swaps a module that exports components exclusively.) */

export type ToastOptions = {
  action?: { label: string; onAction: () => void | Promise<void> };
  duration?: number;
};

export type ToastApi = {
  success: (message: string, options?: ToastOptions) => void;
  error: (message: string, options?: ToastOptions) => void;
  /** Delete-with-undo: the common case, so it gets a named helper. */
  undo: (message: string, onUndo: () => void | Promise<void>) => void;
};

export const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
