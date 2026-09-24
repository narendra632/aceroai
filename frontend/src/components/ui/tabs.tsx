import * as React from "react";
import { Tabs as TabsPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

/* Tabs, for a page that has grown several jobs rather than several sections.
 *
 * ⚠ Tabs are not a layout preference here, they are a correction. The Investments page had
 * thirteen panels stacked down one column: the book, the chart, the holdings, live proposals,
 * the research queue, the framework, what sources said, the benchmarks, the parallel books,
 * the reviews, the go/no-go criteria, the foreign-holdings schedule and the ledger. Every one
 * of them answers a different question asked at a different frequency — "what is it worth
 * today" is a daily glance and "should this experiment continue" is a quarterly sit-down —
 * and stacking them made the page a scroll whose length was the only thing any of them had
 * in common. What is checked daily ended up above what is read monthly purely because it was
 * written first.
 *
 * ⚠ The selected tab is remembered per viewer. Reloading back to "Holdings" every time
 * punishes exactly the person who came to look at the research queue, and losing a tab on
 * refresh is the kind of small friction that quietly decides which parts of a tool get used.
 * `localStorage` can throw — a private window, blocked site data — so both the read and the
 * write are guarded and the page renders correctly with neither.
 */

const Tabs = TabsPrimitive.Root;

function TabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        /* Scrolls sideways rather than wrapping. A tab bar that wraps to two lines on a
         * phone moves the content down by a row, which reads as the page having shifted. */
        "flex w-full items-center gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1",
        "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
      {...props}
    />
  );
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium",
        "text-muted-foreground transition-colors",
        "hover:text-foreground",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "data-[state=active]:bg-muted data-[state=active]:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      /* ⚠ `mt-0` then spacing from the caller. Radix gives content no margin of its own and
       * the panels below supply their own rhythm; a margin here would double it. */
      className={cn("mt-0 focus-visible:outline-none", className)}
      {...props}
    />
  );
}

/** Remember which tab was open, per browser, surviving a reload but never leaving it. */
function useRememberedTab(storageKey: string, fallback: string) {
  const [tab, setTab] = React.useState<string>(() => {
    try {
      return window.localStorage.getItem(storageKey) ?? fallback;
    } catch {
      return fallback;
    }
  });

  const choose = React.useCallback(
    (next: string) => {
      setTab(next);
      try {
        window.localStorage.setItem(storageKey, next);
      } catch {
        /* A private window refuses to store. The tab still works for this visit. */
      }
    },
    [storageKey],
  );

  return [tab, choose] as const;
}

export { Tabs, TabsList, TabsTrigger, TabsContent, useRememberedTab };
