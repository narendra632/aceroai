import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, FileCode2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FlowDiagram } from "@/components/ui/flow-diagram";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useLearnConstants } from "@/hooks/useLearnConstants";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  CONCEPTS,
  COST_FLOW,
  MESSAGE_FLOW,
  PLANNED,
  PROACTIVE_FLOW,
} from "@/lib/learn/content";
import { ICONS } from "@/lib/learn/icons";
import { interpolate } from "@/lib/learn/interpolate";
import type { Concept, Diagram, Explanation } from "@/lib/learn/types";
import { cn } from "@/lib/utils";

/* The app explaining itself.
 *
 * Everything here describes the system, not the user — so it holds no personal data, makes
 * no writes, and is safe to leave open.
 *
 * Three rules it keeps to:
 *
 *  - Numbers are never written here. They arrive from /api/learn/constants, so a tuned
 *    setting changes the lesson rather than making it wrong.
 *  - Explanations are entered by clicking. A wall of prose was explicitly not the brief,
 *    and the content checker enforces the length budget that keeps it that way.
 *  - One subject on screen at a time. These are four separate questions, and stacking them
 *    into one scroll made you hunt for where you were.
 */

const REPO = "https://github.com/narendra632/aceroai/blob/main/";

/** The breakpoint where a panel can sit beside a diagram instead of over it. Matches
 *  Tailwind's `lg`, and is read in JS rather than CSS because the Sheet is portalled —
 *  see `useMediaQuery`. */
const WIDE = "(min-width: 1024px)";

const TABS = [
  { id: "message", label: "How a message is answered" },
  { id: "proactive", label: "How Acero speaks first" },
  { id: "cost", label: "What it costs" },
  { id: "concepts", label: "The ideas underneath" },
  { id: "planned", label: "Not built yet" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const DIAGRAM_BY_TAB: Partial<Record<TabId, Diagram>> = {
  message: MESSAGE_FLOW,
  proactive: PROACTIVE_FLOW,
  cost: COST_FLOW,
};

const GROUP_LABEL: Record<string, string> = {
  memory: "Memory",
  model: "The model",
  data: "Data",
  delivery: "Delivery",
};

const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v);

/* Which tab is open, and what is open inside it, both in the URL.
 *
 * Written as `#tab/selection`, not `#selection` alone. Deriving the tab from a bare id
 * works today only because every id happens to be unique across the four tabs — that is a
 * coincidence, not a guarantee, and the day it stops holding the link would open the wrong
 * tab silently. The prefix removes the guess.
 *
 * A bare id is still ACCEPTED, as a last resort, so links written before tabs existed keep
 * working. Reading one is safe; writing one would bake in the coincidence. */
function useRoute() {
  const read = useCallback((): { tab: TabId; selected: string | null } => {
    const raw =
      typeof window === "undefined" ? "" : window.location.hash.slice(1);
    const [first, second] = raw.split("/");
    if (isTab(first)) return { tab: first, selected: second || null };
    // Fall back to resolving a bare id, so links made before tabs existed still land in
    // the right place. Only a LAST resort — as the tab prefix, it would be guessing.
    if (first && CONCEPTS.some((c) => c.id === first))
      return { tab: "concepts", selected: first };
    for (const [id, d] of Object.entries(DIAGRAM_BY_TAB)) {
      if (first && d?.panels[first])
        return { tab: id as TabId, selected: first };
    }
    return { tab: "message", selected: null };
  }, []);

  const [route, setRoute] = useState(read);

  const go = useCallback((tab: TabId, selected: string | null = null) => {
    setRoute({ tab, selected });
    const url = new URL(window.location.href);
    url.hash = selected ? `${tab}/${selected}` : tab;
    window.history.replaceState(null, "", url.toString());
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [read]);

  return [route, go] as const;
}

/* The panel body, without a heading.
 *
 * Deliberately headless: on a wide screen it sits in a card that supplies its own title
 * and close button, and below `lg` it goes inside a Sheet that already renders both. One
 * component with two headers would show the title twice on a phone. */
function PanelBody({
  item,
  text,
  onConcept,
}: {
  item: Explanation;
  text: (s: string) => string;
  onConcept: (id: string) => void;
}) {
  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed">{text(item.what)}</p>

      <ul className="space-y-2">
        {item.how.map((line) => (
          <li
            key={line}
            className="flex gap-2 text-sm leading-snug text-muted-foreground"
          >
            <span
              aria-hidden
              className="mt-2 size-1 shrink-0 rounded-full bg-primary/60"
            />
            <span>{text(line)}</span>
          </li>
        ))}
      </ul>

      {item.measured && (
        <p className="rounded-lg border-l-2 border-primary/50 bg-secondary/60 px-3 py-2 text-sm">
          <span className="mr-1.5 font-medium">Measured.</span>
          {text(item.measured)}
        </p>
      )}

      {item.concepts && item.concepts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {item.concepts.map((id) => {
            const concept = CONCEPTS.find((c) => c.id === id);
            if (!concept) return null;
            return (
              // Jumps to the Concepts tab with that idea open. Selecting a concept id
              // while a diagram tab is showing would set a selection nothing renders.
              <button
                key={id}
                onClick={() => onConcept(id)}
                className="rounded-md bg-secondary px-2 py-1 text-xs text-secondary-foreground transition hover:bg-accent"
              >
                {concept.title}
              </button>
            );
          })}
        </div>
      )}

      {(item.code?.length || item.reads?.length) && (
        <div className="space-y-1.5 border-t border-border pt-3">
          {item.code?.map((path) => (
            <a
              key={path}
              href={`${REPO}${path}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 text-xs text-muted-foreground transition hover:text-foreground"
            >
              <FileCode2 className="size-3.5 shrink-0" />
              <span className="truncate font-mono">{path}</span>
            </a>
          ))}
          {item.reads?.map((read) => (
            <a
              key={read.href}
              href={`${REPO}${read.href}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 text-xs text-primary transition hover:opacity-80"
            >
              <ArrowUpRight className="size-3.5 shrink-0" />
              {read.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LearnView() {
  const { constants, failed } = useLearnConstants();
  const [{ tab, selected }, go] = useRoute();
  const wide = useMediaQuery(WIDE);
  const scrollRef = useRef<HTMLDivElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);

  const text = useCallback(
    (s: string) => interpolate(s, constants),
    [constants],
  );

  // Switching subject scrolls back to the top. Landing mid-page in a tab you have not
  // read yet is disorienting, and it is the thing tabs were meant to fix.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [tab]);

  const diagram = DIAGRAM_BY_TAB[tab];
  const open: Explanation | undefined = selected
    ? tab === "concepts"
      ? CONCEPTS.find((c) => c.id === selected)
      : diagram?.panels[selected]
    : undefined;

  const grouped = useMemo(
    () =>
      CONCEPTS.reduce<Record<string, Concept[]>>((acc, c) => {
        (acc[c.group] ??= []).push(c);
        return acc;
      }, {}),
    [],
  );

  /** Left/right arrows move between tabs — the standard tablist behaviour, and the reason
   *  the buttons carry `role="tab"` rather than being styled links. */
  function onTabKey(event: React.KeyboardEvent) {
    const delta =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const i = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(i + delta + TABS.length) % TABS.length];
    go(next.id);
    // Focus follows selection in this pattern, so the arrow keys keep working.
    requestAnimationFrame(() => {
      tabsRef.current
        ?.querySelector<HTMLButtonElement>(`[data-tab="${next.id}"]`)
        ?.focus();
    });
  }

  const panelCard = open && (
    <div className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold">{text(open.title)}</h3>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => go(tab)}
          aria-label="Close"
          className="-mt-1 -mr-1 flex-none"
        >
          <X />
        </Button>
      </div>
      <PanelBody
        item={open}
        text={text}
        onConcept={(id) => go("concepts", id)}
      />
    </div>
  );

  const emptyHint = (
    <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
      {tab === "concepts"
        ? "Pick an idea to read about it."
        : "Pick a step to see what happens there."}
    </p>
  );

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 pb-16 md:px-6">
        {/* The shell's header names this screen, so there is no <h1> here. What stays is
            the part that is genuinely about the content: how to read it, and whether the
            numbers in it are live. */}
        <header className="space-y-2 pt-8 pb-5">
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Everything Acero does, explained by the app itself. Click any box or
            card to open it. The numbers come from the running system, so they
            are never out of date.
          </p>
          {failed && (
            <p className="text-xs text-muted-foreground">
              Couldn't reach the server for the current settings, so a few
              figures below show their placeholder instead of a number.
            </p>
          )}
        </header>

        <div
          ref={tabsRef}
          role="tablist"
          aria-label="Sections"
          onKeyDown={onTabKey}
          className="sticky top-0 z-20 -mx-4 mb-7 flex gap-1.5 overflow-x-auto border-b border-border bg-background/85 px-4 py-2.5 backdrop-blur md:-mx-6 md:px-6"
        >
          {TABS.map((t, i) => (
            <button
              key={t.id}
              data-tab={t.id}
              id={`learn-tab-${t.id}`}
              role="tab"
              aria-controls="learn-tabpanel"
              aria-selected={tab === t.id}
              // Only the selected tab is in the tab order; arrows move within the set.
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => go(t.id)}
              className={cn(
                "flex-none rounded-lg px-2.5 py-1.5 text-xs whitespace-nowrap transition",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                tab === t.id
                  ? "bg-secondary font-medium text-secondary-foreground"
                  : "text-muted-foreground hover:bg-secondary/60",
              )}
            >
              <span className="mr-1.5 tabular-nums text-faint">{i + 1}</span>
              {t.label}
            </button>
          ))}
        </div>

        <div
          id="learn-tabpanel"
          role="tabpanel"
          aria-labelledby={`learn-tab-${tab}`}
        >
          {diagram && (
            <section className="space-y-5">
              <div className="space-y-1.5">
                <h2 className="text-lg font-semibold">{text(diagram.title)}</h2>
                <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  {text(diagram.intro)}
                </p>
              </div>

              <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
                <FlowDiagram
                  ariaLabel={diagram.title}
                  nodes={diagram.nodes}
                  edges={diagram.edges}
                  selected={selected}
                  onSelect={(id) => go(tab, id)}
                />
                <aside className="hidden lg:block">
                  <div className="sticky top-16">
                    {open ? panelCard : emptyHint}
                  </div>
                </aside>
              </div>
            </section>
          )}

          {tab === "concepts" && (
            <section className="space-y-5">
              <div className="space-y-1.5">
                <h2 className="text-lg font-semibold">The ideas underneath</h2>
                <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  The concepts this is built on. Each one explains the idea
                  first, then how Acero uses it — so they are worth knowing
                  outside this project too.
                </p>
              </div>

              <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_21rem]">
                <div className="space-y-5">
                  {Object.entries(grouped).map(([group, items]) => (
                    <div key={group} className="space-y-2">
                      <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                        {GROUP_LABEL[group] ?? group}
                      </h3>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {items.map((concept) => (
                          <button
                            key={concept.id}
                            onClick={() =>
                              go(
                                "concepts",
                                selected === concept.id ? null : concept.id,
                              )
                            }
                            aria-pressed={selected === concept.id}
                            className={cn(
                              "min-h-11 rounded-xl border border-border bg-card p-3 text-left transition",
                              "hover:border-primary/50 hover:shadow-sm",
                              "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                              selected === concept.id &&
                                "border-primary shadow-sm ring-[3px] ring-primary/25",
                            )}
                          >
                            <span className="block text-sm font-medium">
                              {concept.title}
                            </span>
                            <span className="mt-1 block text-xs leading-snug text-muted-foreground">
                              {text(concept.what)}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <aside className="hidden lg:block">
                  <div className="sticky top-16">
                    {open ? panelCard : emptyHint}
                  </div>
                </aside>
              </div>
            </section>
          )}

          {tab === "planned" && (
            <section className="space-y-5">
              <div className="space-y-1.5">
                <h2 className="text-lg font-semibold">Not built yet</h2>
                <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  Kept separate on purpose. Each one is scheduled by a
                  measurement rather than a date — the app says when it is time.
                </p>
              </div>
              <ul className="grid gap-2 sm:grid-cols-2">
                {PLANNED.map((item) => (
                  <li
                    key={item.id}
                    className="rounded-xl border border-dashed border-border/70 p-3"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-muted-foreground">
                        {item.title}
                      </span>
                      <span className="rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                        planned
                      </span>
                    </div>
                    <p className="mt-1 text-xs leading-snug text-muted-foreground">
                      {text(item.what)}
                    </p>
                    <p className="mt-1.5 flex items-start gap-1.5 text-xs leading-snug text-faint">
                      <ICONS.gauge className="mt-0.5 size-3 flex-none" />
                      {text(item.trigger)}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>

      {/* Below `lg` the explanation is a Sheet. Rendered ONLY when narrow, not hidden with
          a class: the Sheet portals into document.body, so a `lg:hidden` wrapper never
          applies to it and both panels drew at once. */}
      {!wide && (
        <Sheet open={!!open} onOpenChange={(o) => !o && go(tab)}>
          {open && (
            <SheetContent title={text(open.title)} className="overflow-y-auto">
              <div className="px-4 pb-6">
                <PanelBody
                  item={open}
                  text={text}
                  onConcept={(id) => go("concepts", id)}
                />
              </div>
            </SheetContent>
          )}
        </Sheet>
      )}
    </div>
  );
}
