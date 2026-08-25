import { useCallback, useEffect, useMemo, useState } from "react";
import { BadgeCheck, Brain, LayoutList, Network, Search, Wrench, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ForceGraph, GraphLegend } from "@/components/ui/force-graph";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState, ErrorState, ListSkeleton, Skeleton } from "@/components/ui/states";
import FactSheet from "@/components/FactSheet";
import { useOptimisticList } from "@/hooks/useOptimisticList";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { Fact, Graph } from "@/lib/api";
import { cn } from "@/lib/utils";

/* What Acero has learned about you.
 *
 * Until this view existed, `profile_facts` had no HTTP surface at all: the assistant
 * carried its own inferences into every conversation, on every channel, and you could
 * not read them, correct them, or remove them.
 *
 * Two presentations of the same data. The graph shows how beliefs relate — clusters
 * emerge from meaning, so two facts sharing no words can still sit together. The list is
 * the readable, searchable, screen-reader-accessible equivalent, and is the default on a
 * small screen where a canvas is unusable.
 */

const CATEGORIES = ["preference", "health", "work", "finance", "relationship", "other"] as const;

const CATEGORY_LABEL: Record<string, string> = {
  all: "All categories",
  preference: "Preference",
  health: "Health",
  work: "Work",
  finance: "Finance",
  relationship: "Relationship",
  other: "Other",
};

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Graph on desktop, list on a phone — decided once on mount rather than on every
 *  resize, so rotating the device doesn't throw away what you were looking at. */
function initialMode(): "graph" | "list" {
  return typeof window !== "undefined" && window.matchMedia("(min-width: 640px)").matches
    ? "graph"
    : "list";
}

export default function KnowledgeView({
  onOpenSession,
}: {
  onOpenSession: (sessionId: string) => void;
}) {
  const [mode, setMode] = useState<"graph" | "list">(initialMode);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sheetId, setSheetId] = useState<string | null>(null);
  const toast = useToast();

  // Pagination. The filters are applied SERVER-side, so "load more" always continues
  // within whatever category or search is active rather than paging through everything
  // and filtering the leftovers.
  const [more, setMore] = useState({ offset: 0, hasMore: false });
  const [loadingMore, setLoadingMore] = useState(false);

  const filters = useMemo(
    () => ({
      q: query || undefined,
      category: category === "all" ? undefined : category,
    }),
    [query, category],
  );

  const load = useCallback(async () => {
    const page = await api.listFacts({ ...filters, limit: api.FACT_PAGE_SIZE, offset: 0 });
    // A full page means there is probably another; a short one means we reached the end.
    setMore({ offset: page.length, hasMore: page.length === api.FACT_PAGE_SIZE });
    return page;
  }, [filters]);

  const list = useOptimisticList<Fact>(load, [filters]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.listFacts({
        ...filters,
        limit: api.FACT_PAGE_SIZE,
        offset: more.offset,
      });
      list.setItems((items) => {
        // Guard against a duplicate if something was inserted between pages.
        const seen = new Set(items.map((i) => i.id));
        return [...items, ...page.filter((f) => !seen.has(f.id))];
      });
      setMore({
        offset: more.offset + page.length,
        hasMore: page.length === api.FACT_PAGE_SIZE,
      });
    } catch {
      toast.error("Could not load more");
    } finally {
      setLoadingMore(false);
    }
  }

  // The graph is loaded once and filtered client-side: re-fetching on every filter
  // change would relayout the whole thing, which destroys the mental map that makes
  // the view worth having.
  const [graph, setGraph] = useState<Graph | null>(null);
  const [graphError, setGraphError] = useState(false);
  // How close two facts must be to be drawn as related. Real embeddings of one person's
  // facts sit in a narrow band (measured: 0.13-0.48), so this control genuinely changes
  // what you see rather than being a decorative knob.
  const [strength, setStrength] = useState(0.32);

  const loadGraph = useCallback(() => {
    setGraphError(false);
    api
      .getGraph(strength)
      .then(setGraph)
      .catch(() => setGraphError(true));
  }, [strength]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Timeline scrubber: how the memory grew. `null` = show everything.
  const [upTo, setUpTo] = useState<number | null>(null);
  const days = useMemo(() => {
    const all = (graph?.nodes ?? []).map((n) => n.valid_from).sort();
    return [...new Set(all.map((d) => d.slice(0, 10)))];
  }, [graph]);

  const visibleGraph = useMemo<Graph>(() => {
    if (!graph)
      return {
        nodes: [],
        edges: [],
        truncated: false,
        total: 0,
        render_limit: 0,
        needs_faster_layout: false,
      };
    if (upTo == null || upTo >= days.length - 1) return graph;
    const cutoff = days[upTo];
    const nodes = graph.nodes.filter((n) => n.valid_from.slice(0, 10) <= cutoff);
    const ids = new Set(nodes.map((n) => n.id));
    return {
      ...graph,
      nodes,
      edges: graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
    };
  }, [graph, upTo, days]);

  // The category filter dims rather than removes, so you keep seeing how the highlighted
  // facts sit inside the whole memory.
  const highlightIds = useMemo(() => {
    if (category === "all" && !query) return null;
    const wanted = new Set(
      visibleGraph.nodes
        .filter(
          (n) =>
            (category === "all" || n.category === category) &&
            (!query || n.fact.toLowerCase().includes(query.toLowerCase())),
        )
        .map((n) => n.id),
    );
    return wanted;
  }, [visibleGraph.nodes, category, query]);

  function forget(fact: Fact) {
    void (async () => {
      const ok = await list.mutate({
        optimistic: (items) => items.filter((f) => f.id !== fact.id),
        request: () => api.forgetFact(fact.id),
        errorMessage: "Could not forget that",
      });
      if (ok) {
        setGraph((g) =>
          g
            ? {
                ...g,
                nodes: g.nodes.filter((n) => n.id !== fact.id),
                edges: g.edges.filter((e) => e.source !== fact.id && e.target !== fact.id),
                total: Math.max(0, g.total - 1),
              }
            : g,
        );
        toast.undo("Forgotten — Acero won't use this again", async () => {
          await list.mutate({
            optimistic: (items) => [fact, ...items],
            request: () => api.restoreFact(fact.id),
            errorMessage: "Could not restore that",
          });
          loadGraph();
        });
      }
    })();
  }

  function onSaved(saved: Fact, supersededId: string | null) {
    if (supersededId) {
      list.setItems((items) => [saved, ...items.filter((f) => f.id !== supersededId)]);
      toast.success("Updated — the previous version is kept as history");
      loadGraph(); // a new fact means new edges; the layout genuinely changed
    } else {
      list.replace((f) => f.id === saved.id, saved);
      toast.success("Updated");
    }
  }

  function onConfirmed(saved: Fact) {
    list.replace((f) => f.id === saved.id, saved);
    setGraph((g) =>
      g
        ? { ...g, nodes: g.nodes.map((n) => (n.id === saved.id ? { ...n, source: "stated" } : n)) }
        : g,
    );
    toast.success("Confirmed — Acero will treat this as certain");
  }

  const filtering = category !== "all" || query.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* No page title here: the shell's header owns it, so a screen is named once.
          What remains is this view's own control, which belongs with the content it
          governs rather than in a header shared with every other screen. */}
      <header className="border-b border-border px-4 py-2.5 sm:px-6">
        <div className="flex items-center justify-end gap-3">
          <div className="flex shrink-0 rounded-lg border border-border p-0.5">
            {(
              [
                { key: "graph", label: "Graph", icon: Network },
                { key: "list", label: "List", icon: LayoutList },
              ] as const
            ).map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setMode(key)}
                aria-pressed={mode === key}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                  mode === key
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Filters in one row above the view. */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-0 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search what it knows…"
              aria-label="Search facts"
              className="w-full rounded-lg border border-input bg-background py-2 pr-3 pl-9 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
            />
          </div>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {CATEGORY_LABEL[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {filtering && (
            <Button
              variant="ghost"
              onClick={() => {
                setQuery("");
                setCategory("all");
              }}
            >
              <X className="size-4" /> Clear
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
        {mode === "graph" ? (
          graphError ? (
            <ErrorState
              title="Couldn't load the knowledge graph"
              detail="The connections between facts are computed on the server."
              onRetry={loadGraph}
            />
          ) : !graph ? (
            <Skeleton className="h-[60vh] w-full rounded-xl" />
          ) : graph.nodes.length === 0 ? (
            <EmptyState
              icon={Brain}
              title="Nothing learned yet"
              hint="As you talk to Acero it picks up durable facts about you. They'll appear here, connected by meaning."
            />
          ) : (
            <div className="space-y-3">
              <ForceGraph
                graph={visibleGraph}
                selectedId={selectedId}
                highlightIds={highlightIds}
                onSelect={(n) => {
                  setSelectedId(n?.id ?? null);
                  setSheetId(n?.id ?? null);
                }}
                className="h-[60vh] min-h-80 border border-border"
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <GraphLegend />
                <p className="text-xs text-muted-foreground">
                  {visibleGraph.nodes.length} facts · {visibleGraph.edges.length} connections
                  {graph.truncated && (
                    <>
                      {" "}
                      · showing the latest {graph.nodes.length} of {graph.total}
                    </>
                  )}
                </p>
              </div>

              {/* The engineering trigger, surfaced where it will actually be seen. A note
                  buried in a document gets read once and never re-read; this appears at
                  exactly the moment it becomes true. */}
              {graph.needs_faster_layout && (
                <div
                  role="status"
                  className="flex items-start gap-3 rounded-xl border border-border bg-muted/40 p-4"
                >
                  <Wrench className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 text-sm">
                    <p className="font-medium">
                      {graph.truncated
                        ? `Memory has outgrown the graph (${graph.total} facts, drawing ${graph.render_limit})`
                        : `Approaching the graph's limit — ${graph.total} of ${graph.render_limit} facts`}
                    </p>
                    <p className="mt-1 text-muted-foreground">
                      The layout compares every fact with every other one, so its cost grows
                      with the square of the count. Time to switch it to a{" "}
                      <strong className="font-medium text-foreground">
                        Barnes-Hut quadtree
                      </strong>
                      , which treats distant clusters as one blob and turns that into
                      roughly n·log n. It is a change to one function — the rest of this
                      page is unaffected.
                      {graph.truncated && " Until then, older facts are only in the list."}
                    </p>
                  </div>
                </div>
              )}

              <div className="rounded-xl border border-border bg-card p-4">
                <label
                  htmlFor="strength"
                  className="flex items-center justify-between text-sm font-medium"
                >
                  How closely related to draw a link
                  <span className="font-normal text-muted-foreground">
                    {strength <= 0.25 ? "only the tightest" : strength >= 0.45 ? "loose" : "balanced"}
                  </span>
                </label>
                <input
                  id="strength"
                  type="range"
                  min={0.15}
                  max={0.6}
                  step={0.01}
                  value={strength}
                  onChange={(e) => setStrength(Number(e.target.value))}
                  className="mt-3 w-full accent-(--viz-node)"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  Drag right to reveal weaker associations. Facts with nothing close stay
                  unconnected — that's real information, not a gap.
                </p>
              </div>

              {days.length > 1 && (
                <div className="rounded-xl border border-border bg-card p-4">
                  <label
                    htmlFor="timeline"
                    className="flex items-center justify-between text-sm font-medium"
                  >
                    Watch it grow
                    <span className="font-normal text-muted-foreground">
                      {upTo == null || upTo >= days.length - 1
                        ? "everything so far"
                        : `up to ${formatDay(days[upTo])}`}
                    </span>
                  </label>
                  <input
                    id="timeline"
                    type="range"
                    min={0}
                    max={days.length - 1}
                    value={upTo ?? days.length - 1}
                    onChange={(e) => setUpTo(Number(e.target.value))}
                    className="mt-3 w-full accent-(--viz-node)"
                  />
                  <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                    <span>{formatDay(days[0])}</span>
                    <span>{formatDay(days[days.length - 1])}</span>
                  </div>
                </div>
              )}
            </div>
          )
        ) : list.status === "loading" ? (
          <ListSkeleton rows={5} />
        ) : list.status === "error" ? (
          <ErrorState
            title="Couldn't load what Acero knows"
            detail="This is a connection problem, not an empty memory."
            onRetry={list.reload}
          />
        ) : list.items.length === 0 ? (
          <EmptyState
            icon={Brain}
            title={filtering ? "No facts match that" : "Nothing learned yet"}
            hint={
              filtering
                ? "Try a different search or category."
                : "As you talk to Acero it picks up durable facts about you. They'll appear here."
            }
            action={
              filtering ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setCategory("all");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <ul className="space-y-2">
            {list.items.map((fact) => (
              <li key={fact.id}>
                <button
                  onClick={() => setSheetId(fact.id)}
                  className={cn(
                    "flex w-full items-start gap-3 rounded-xl border border-border bg-card p-4 text-left",
                    "transition-colors hover:bg-accent/50",
                    "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm">{fact.fact}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                      <span className="rounded-md bg-secondary px-1.5 py-0.5 text-secondary-foreground">
                        {CATEGORY_LABEL[fact.category] ?? fact.category}
                      </span>
                      <span>{Math.round(fact.confidence * 100)}% confident</span>
                      <span>·</span>
                      <span>learned {formatDay(fact.valid_from)}</span>
                      {/* Kept rather than deleted, and said so. The previous behaviour was
                          to drop a close-sounding fact silently, which is how a
                          certification the user asked for by name disappeared. */}
                      {fact.possible_duplicate_of && (
                        <>
                          <span>·</span>
                          <span className="rounded-md bg-secondary px-1.5 py-0.5 text-secondary-foreground">
                            may repeat another
                          </span>
                        </>
                      )}
                    </span>
                  </span>
                  {fact.source === "stated" && (
                    <BadgeCheck
                      className="size-4 shrink-0 text-primary"
                      aria-label="You confirmed this"
                    />
                  )}
                </button>
              </li>
            ))}
            {more.hasMore && (
              <li className="pt-2 text-center">
                <Button variant="outline" onClick={() => void loadMore()} disabled={loadingMore}>
                  {loadingMore ? "Loading…" : "Load more"}
                </Button>
                <p className="mt-2 text-xs text-muted-foreground">
                  Showing {list.items.length}
                  {category !== "all" ? ` in ${CATEGORY_LABEL[category].toLowerCase()}` : ""}
                </p>
              </li>
            )}
          </ul>
        )}
      </div>

      <FactSheet
        factId={sheetId}
        onClose={() => setSheetId(null)}
        onSaved={onSaved}
        onConfirmed={onConfirmed}
        onForget={forget}
        onOpenSession={onOpenSession}
      />
    </div>
  );
}
