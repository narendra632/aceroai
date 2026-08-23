import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, FileCode2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FlowDiagram } from "@/components/ui/flow-diagram";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useLearnConstants } from "@/hooks/useLearnConstants";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { CONCEPTS, DIAGRAMS, PLANNED } from "@/lib/learn/content";
import { ICONS } from "@/lib/learn/icons";
import { interpolate } from "@/lib/learn/interpolate";
import type { Concept, Explanation } from "@/lib/learn/types";
import { cn } from "@/lib/utils";

/* The app explaining itself.
 *
 * Everything on this page describes the system, not the user — so it holds no personal
 * data, makes no writes, and is safe to leave open.
 *
 * Two rules it keeps to:
 *
 *  - Numbers are never written here. They arrive from /api/learn/constants, so a tuned
 *    setting changes the lesson rather than making it wrong.
 *  - Explanations are entered by clicking. A wall of prose was explicitly not the brief,
 *    and the content checker enforces the length budget that keeps it that way.
 */

const REPO = "https://github.com/narendra632/aceroai/blob/main/";

/** The breakpoint where a panel can sit beside a diagram instead of over it. Matches
 *  Tailwind's `lg`, and is read in JS rather than CSS because the Sheet is portalled —
 *  see `useMediaQuery`. */
const WIDE = "(min-width: 1024px)";

const GROUP_LABEL: Record<string, string> = {
  memory: "Memory",
  model: "The model",
  data: "Data",
  delivery: "Delivery",
};

type Section = { id: string; label: string };

function useHashSelection() {
  const [selected, setSelected] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.location.hash.slice(1) || null,
  );

  // Reflected in the URL so a specific explanation can be linked to. Without it, pointing
  // someone at one means saying "click the third box".
  const select = useCallback((id: string | null) => {
    setSelected(id);
    const url = new URL(window.location.href);
    url.hash = id ?? "";
    window.history.replaceState(null, "", url.toString());
  }, []);

  useEffect(() => {
    const onHash = () => setSelected(window.location.hash.slice(1) || null);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return [selected, select] as const;
}

/** Highlights whichever section is currently on screen, so the contents bar says where you
 *  are rather than only where you can go. */
function useActiveSection(ids: string[], rootRef: React.RefObject<HTMLElement | null>) {
  const [active, setActive] = useState(ids[0]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;
    const seen = new Map<string, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) seen.set(entry.target.id, entry.intersectionRatio);
        // The most visible section wins. Picking "the first one intersecting" flickers
        // between two whenever a boundary crosses the viewport.
        let best = ids[0];
        let bestRatio = -1;
        for (const id of ids) {
          const ratio = seen.get(id) ?? 0;
          if (ratio > bestRatio) {
            best = id;
            bestRatio = ratio;
          }
        }
        setActive(best);
      },
      { root, threshold: [0, 0.15, 0.35, 0.6, 1], rootMargin: "-72px 0px -50% 0px" },
    );
    for (const id of ids) {
      const el = root.querySelector(`#${CSS.escape(id)}`);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids, rootRef]);

  return active;
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
          <li key={line} className="flex gap-2 text-sm leading-snug text-muted-foreground">
            <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-primary/60" />
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
  const [selected, select] = useHashSelection();
  const wide = useMediaQuery(WIDE);
  const scrollRef = useRef<HTMLDivElement>(null);

  const text = useCallback((s: string) => interpolate(s, constants), [constants]);

  const sections: Section[] = useMemo(
    () => [
      ...DIAGRAMS.map((d) => ({ id: `s-${d.id}`, label: d.title })),
      { id: "s-concepts", label: "The ideas underneath" },
      { id: "s-planned", label: "Not built yet" },
    ],
    [],
  );
  const sectionIds = useMemo(() => sections.map((s) => s.id), [sections]);
  const active = useActiveSection(sectionIds, scrollRef);

  const openConcept = CONCEPTS.find((c) => c.id === selected) as Concept | undefined;
  const openPanel = DIAGRAMS.find((d) => d.panels[selected ?? ""])?.panels[selected ?? ""];
  const open = openConcept ?? openPanel;

  const grouped = useMemo(
    () =>
      CONCEPTS.reduce<Record<string, Concept[]>>((acc, c) => {
        (acc[c.group] ??= []).push(c);
        return acc;
      }, {}),
    [],
  );

  function jump(id: string) {
    scrollRef.current?.querySelector(`#${CSS.escape(id)}`)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  const panelCard = open && (
    <div className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-semibold">{text(open.title)}</h3>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => select(null)}
          aria-label="Close"
          className="-mt-1 -mr-1 flex-none"
        >
          <X />
        </Button>
      </div>
      <PanelBody item={open} text={text} onConcept={select} />
    </div>
  );

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-smooth">
      <div className="mx-auto w-full max-w-5xl px-4 pb-16 md:px-6">
        <header className="space-y-2 pt-8 pb-5">
          <h1 className="text-2xl font-semibold">How this works</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Everything Acero does, explained by the app itself. Click any box or card to
            open it. The numbers come from the running system, so they are never out of
            date.
          </p>
          {failed && (
            <p className="text-xs text-muted-foreground">
              Couldn't reach the server for the current settings, so a few figures below
              show their placeholder instead of a number.
            </p>
          )}
        </header>

        {/* Contents. Sticky, so it is reachable from anywhere on a long page, and it
            highlights where you are rather than only where you can go. */}
        <nav
          aria-label="Contents"
          className="sticky top-0 z-20 -mx-4 mb-8 border-b border-border bg-background/85 px-4 py-2.5 backdrop-blur md:-mx-6 md:px-6"
        >
          <ul className="flex gap-1.5 overflow-x-auto">
            {sections.map((section, i) => (
              <li key={section.id} className="flex-none">
                <button
                  onClick={() => jump(section.id)}
                  aria-current={active === section.id ? "true" : undefined}
                  className={cn(
                    "rounded-lg px-2.5 py-1.5 text-xs whitespace-nowrap transition",
                    active === section.id
                      ? "bg-secondary font-medium text-secondary-foreground"
                      : "text-muted-foreground hover:bg-secondary/60",
                  )}
                >
                  <span className="mr-1.5 tabular-nums text-faint">{i + 1}</span>
                  {section.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="space-y-14">
          {DIAGRAMS.map((diagram) => (
            <section key={diagram.id} id={`s-${diagram.id}`} className="scroll-mt-20 space-y-5">
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
                  onSelect={select}
                />
                {/* Only rendered when this diagram owns the selection, so opening a step
                    in one diagram cannot leave a panel hanging beside the other. */}
                <aside className="hidden lg:block">
                  <div className="sticky top-16">
                    {diagram.panels[selected ?? ""] ? (
                      panelCard
                    ) : (
                      <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                        Pick a step to see what happens there.
                      </p>
                    )}
                  </div>
                </aside>
              </div>
            </section>
          ))}

          <section id="s-concepts" className="scroll-mt-20 space-y-5">
            <div className="space-y-1.5">
              <h2 className="text-lg font-semibold">The ideas underneath</h2>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                The concepts this is built on. Each one explains the idea first, then how
                Acero uses it — so they are worth knowing outside this project too.
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
                          onClick={() => select(selected === concept.id ? null : concept.id)}
                          aria-pressed={selected === concept.id}
                          className={cn(
                            "min-h-11 rounded-xl border border-border bg-card p-3 text-left transition",
                            "hover:border-primary/50 hover:shadow-sm",
                            "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                            selected === concept.id &&
                              "border-primary shadow-sm ring-[3px] ring-primary/25",
                          )}
                        >
                          <span className="block text-sm font-medium">{concept.title}</span>
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
                  {openConcept ? (
                    panelCard
                  ) : (
                    <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                      Pick an idea to read about it.
                    </p>
                  )}
                </div>
              </aside>
            </div>
          </section>

          <section id="s-planned" className="scroll-mt-20 space-y-5">
            <div className="space-y-1.5">
              <h2 className="text-lg font-semibold">Not built yet</h2>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                Kept separate on purpose. Each one is scheduled by a measurement rather
                than a date — the app says when it is time.
              </p>
            </div>
            <ul className="grid gap-2 sm:grid-cols-2">
              {PLANNED.map((item) => (
                <li key={item.id} className="rounded-xl border border-dashed border-border/70 p-3">
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
        </div>
      </div>

      {/* Below `lg` the explanation is a Sheet. Rendered ONLY when narrow, not hidden with
          a class: the Sheet portals into document.body, so a `lg:hidden` wrapper never
          applies to it and both panels drew at once. */}
      {!wide && (
        <Sheet open={!!open} onOpenChange={(o) => !o && select(null)}>
          {open && (
            <SheetContent title={text(open.title)} className="overflow-y-auto">
              <div className="px-4 pb-6">
                <PanelBody item={open} text={text} onConcept={select} />
              </div>
            </SheetContent>
          )}
        </Sheet>
      )}
    </div>
  );
}
