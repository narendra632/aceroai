import { useCallback, useEffect, useState } from "react";
import { ArrowUpRight, FileCode2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FlowDiagram } from "@/components/ui/flow-diagram";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useLearnConstants } from "@/hooks/useLearnConstants";
import { CONCEPTS, DIAGRAMS, PLANNED } from "@/lib/learn/content";
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

const GROUP_LABEL: Record<string, string> = {
  memory: "Memory",
  model: "The model",
  data: "Data",
  delivery: "Delivery",
};

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
        <p className="rounded-lg border border-border bg-secondary/60 px-3 py-2 text-sm">
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

  const text = useCallback((s: string) => interpolate(s, constants), [constants]);

  const openConcept = CONCEPTS.find((c) => c.id === selected) as Concept | undefined;
  const openDiagram = DIAGRAMS.find((d) => d.panels[selected ?? ""]);
  const open = openConcept ?? (selected ? openDiagram?.panels[selected] : undefined);

  const grouped = CONCEPTS.reduce<Record<string, Concept[]>>((acc, c) => {
    (acc[c.group] ??= []).push(c);
    return acc;
  }, {});

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl space-y-12 px-4 py-8 md:px-6">
        <header className="space-y-2">
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

        {DIAGRAMS.map((diagram) => (
          <section key={diagram.id} className="space-y-4">
            <div className="space-y-1.5">
              <h2 className="text-lg font-semibold">{text(diagram.title)}</h2>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                {text(diagram.intro)}
              </p>
            </div>

            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
              <FlowDiagram
                ariaLabel={diagram.title}
                nodes={diagram.nodes}
                edges={diagram.edges}
                selected={selected}
                onSelect={select}
              />
              {/* On a wide screen the panel sits beside the diagram, so the two are read
                  together. On anything narrower it becomes a Sheet — see below. */}
              <aside className="hidden lg:block">
                {open && diagram.panels[selected ?? ""] ? (
                  <div className="sticky top-6 space-y-4 rounded-xl border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-base font-semibold">{text(open.title)}</h3>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() => select(null)}
                        aria-label="Close"
                      >
                        <X />
                      </Button>
                    </div>
                    <PanelBody item={open} text={text} onConcept={select} />
                  </div>
                ) : (
                  <p className="sticky top-6 rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
                    Pick a step to see what happens there.
                  </p>
                )}
              </aside>
            </div>
          </section>
        ))}

        <section className="space-y-4">
          <div className="space-y-1.5">
            <h2 className="text-lg font-semibold">The ideas underneath</h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              The concepts this is built on. Each one explains the idea first, then how
              Acero uses it — so they are worth knowing outside this project too.
            </p>
          </div>

          {Object.entries(grouped).map(([group, items]) => (
            <div key={group} className="space-y-2">
              <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {GROUP_LABEL[group] ?? group}
              </h3>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {items.map((concept) => (
                  <button
                    key={concept.id}
                    onClick={() => select(selected === concept.id ? null : concept.id)}
                    aria-pressed={selected === concept.id}
                    className={cn(
                      "min-h-11 rounded-xl border border-border bg-card p-3 text-left transition",
                      "hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                      selected === concept.id && "border-primary ring-[3px] ring-primary/25",
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
        </section>

        <section className="space-y-4">
          <div className="space-y-1.5">
            <h2 className="text-lg font-semibold">Not built yet</h2>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Kept separate on purpose. Each one is scheduled by a measurement rather than
              a date — the app says when it is time.
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
                <p className="mt-1.5 text-xs leading-snug text-faint">{text(item.trigger)}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* Below `lg`, the explanation is a Sheet rather than a column — the primitive
          already handles focus trapping and dismissal, and at 375px there is no room to
          put a panel beside anything. */}
      <div className="lg:hidden">
        <Sheet open={!!open} onOpenChange={(o) => !o && select(null)}>
          {open && (
            <SheetContent title={text(open.title)} className="overflow-y-auto">
              <div className="px-4 pb-6">
                <PanelBody item={open} text={text} onConcept={select} />
              </div>
            </SheetContent>
          )}
        </Sheet>
      </div>
    </div>
  );
}
