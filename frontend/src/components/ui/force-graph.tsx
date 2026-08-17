import * as React from "react";
import { Maximize, Minus, Plus } from "lucide-react";

import type { Graph, GraphNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/* The knowledge graph.
   Facts are nodes; edges are semantic similarity computed server-side by pgvector.
   The 768-dimensional vectors never reach the browser — only the relationships do.

   Layout is a hand-written force simulation (repulsion + springs + centring) rather
   than a library: the whole renderer is ~1 file, and no dependency was added.

   ENCODING — one series, deliberately. Colour carries nothing.
     radius = confidence      ring = stated vs inferred      position = relatedness
   Category is a filter, not a hue. Six categorical colours cannot be told apart in a
   scatter form even with full colour vision (measured; see design.md 6b), and hue would
   fight the clustering that is the actual information here.

   ACCESSIBILITY: a canvas is opaque to screen readers. The list view is the equivalent
   surface — same data, same actions, keyboard reachable — not a fallback. */

const REPULSION = 5200; // node-node push; raise to spread clusters apart
const SPRING = 0.012; // edge pull toward its rest length
const CENTRE_PULL = 0.006; // keeps the whole graph from drifting off-canvas
const DAMPING = 0.82; // velocity retained per tick; below 1 or it never settles
const ALPHA_DECAY = 0.985; // simulation "temperature" — stops the loop once cold
const ALPHA_MIN = 0.004;
const MIN_R = 5;
const MAX_R = 13;

type Sim = { id: string; x: number; y: number; vx: number; vy: number; r: number };

/** Deterministic PRNG. The same graph must lay out the same way every reload — a layout
 *  that reshuffles on refresh makes it impossible to build a mental map of your own
 *  memory, which is the entire point of the view. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hash(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function radiusFor(confidence: number): number {
  return MIN_R + (MAX_R - MIN_R) * Math.max(0, Math.min(1, confidence));
}

function readVar(el: HTMLElement, name: string): string {
  return getComputedStyle(el).getPropertyValue(name).trim() || "#888";
}

export type ForceGraphProps = {
  graph: Graph;
  selectedId?: string | null;
  /** Ids to keep at full strength; everything else dims. Used by the category filter. */
  highlightIds?: Set<string> | null;
  onSelect?: (node: GraphNode | null) => void;
  className?: string;
};

export function ForceGraph({
  graph,
  selectedId,
  highlightIds,
  onSelect,
  className,
}: ForceGraphProps) {
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const simRef = React.useRef<Sim[]>([]);
  const viewRef = React.useRef({ x: 0, y: 0, scale: 1 });
  const alphaRef = React.useRef(1);
  const rafRef = React.useRef(0);
  const sizeRef = React.useRef({ w: 0, h: 0 });
  // The loop parks itself when the layout settles; these let interaction restart it.
  const runningRef = React.useRef(false);
  const dirtyRef = React.useRef(true);
  const wakeRef = React.useRef<() => void>(() => {});
  const [hovered, setHovered] = React.useState<{ node: GraphNode; x: number; y: number } | null>(
    null,
  );
  // Mirrors viewRef.scale purely so the +/- buttons can disable at their limits. The
  // canvas itself reads the ref, so this never drives a redraw.
  const [zoom, setZoom] = React.useState(1);

  const nodeById = React.useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of graph.nodes) m.set(n.id, n);
    return m;
  }, [graph.nodes]);

  // --- build / rebuild the simulation when the data changes -------------------------
  React.useEffect(() => {
    const rand = seeded(1337);
    const previous = new Map(simRef.current.map((s) => [s.id, s]));
    simRef.current = graph.nodes.map((n) => {
      const kept = previous.get(n.id);
      if (kept) return { ...kept, r: radiusFor(n.confidence) };
      // Seed from the node's own id so a given fact always starts in the same place,
      // then jitter deterministically so nodes don't stack exactly.
      const angle = (hash(n.id) % 360) * (Math.PI / 180);
      const dist = 60 + rand() * 140;
      return {
        id: n.id,
        x: Math.cos(angle) * dist,
        y: Math.sin(angle) * dist,
        vx: 0,
        vy: 0,
        r: radiusFor(n.confidence),
      };
    });
    alphaRef.current = 1; // reheat so the new shape settles
  }, [graph.nodes]);

  // --- the loop ---------------------------------------------------------------------
  React.useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const edges = graph.edges;

    function tick() {
      const sim = simRef.current;
      const alpha = alphaRef.current;

      if (alpha > ALPHA_MIN) {
        // Repulsion — every pair pushes apart. O(n²), which at a few hundred facts is
        // far cheaper than the quadtree that would replace it.
        for (let i = 0; i < sim.length; i++) {
          for (let j = i + 1; j < sim.length; j++) {
            const a = sim[i];
            const b = sim[j];
            let dx = b.x - a.x;
            let dy = b.y - a.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 1) {
              dx = (hash(a.id + b.id) % 100) / 50 - 1;
              dy = (hash(b.id + a.id) % 100) / 50 - 1;
              d2 = 1;
            }
            const force = (REPULSION * alpha) / d2;
            const d = Math.sqrt(d2);
            const fx = (dx / d) * force;
            const fy = (dy / d) * force;
            a.vx -= fx;
            a.vy -= fy;
            b.vx += fx;
            b.vy += fy;
          }
        }

        // Springs — a closer meaning pulls harder, so tight clusters read as tight.
        const index = new Map(sim.map((s) => [s.id, s]));
        for (const e of edges) {
          const a = index.get(e.source);
          const b = index.get(e.target);
          if (!a || !b) continue;
          const rest = 40 + e.distance * 160;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 1;
          const f = (d - rest) * SPRING * alpha;
          const fx = (dx / d) * f;
          const fy = (dy / d) * f;
          a.vx += fx;
          a.vy += fy;
          b.vx -= fx;
          b.vy -= fy;
        }

        for (const s of sim) {
          s.vx -= s.x * CENTRE_PULL * alpha;
          s.vy -= s.y * CENTRE_PULL * alpha;
          s.vx *= DAMPING;
          s.vy *= DAMPING;
          s.x += s.vx;
          s.y += s.vy;
        }
        alphaRef.current = alpha * ALPHA_DECAY;
      }

      const hot = alphaRef.current > ALPHA_MIN;
      if (hot || dirtyRef.current) {
        draw();
        dirtyRef.current = false;
      }

      // Stop once the layout has settled and nothing has changed. Without this the loop
      // would keep repainting an identical picture at 60fps for as long as the page is
      // open — invisible on a desktop, a real battery cost on a phone. `wake()` restarts
      // it on any interaction.
      if (hot) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        runningRef.current = false;
      }
    }

    function wake() {
      dirtyRef.current = true;
      if (runningRef.current) return;
      runningRef.current = true;
      rafRef.current = requestAnimationFrame(tick);
    }
    wakeRef.current = wake;

    function draw() {
      if (!ctx || !canvas || !wrap) return;
      const { w, h } = sizeRef.current;
      const view = viewRef.current;
      const nodeColor = readVar(wrap, "--viz-node");
      const edgeColor = readVar(wrap, "--viz-edge");
      const surface = readVar(wrap, "--card");

      ctx.save();
      ctx.clearRect(0, 0, w, h);
      ctx.translate(w / 2 + view.x, h / 2 + view.y);
      ctx.scale(view.scale, view.scale);

      const index = new Map(simRef.current.map((s) => [s.id, s]));
      const dimmed = (id: string) => highlightIds != null && !highlightIds.has(id);

      // Edges first so nodes sit on top.
      ctx.lineWidth = 1.25 / view.scale;
      for (const e of edges) {
        const a = index.get(e.source);
        const b = index.get(e.target);
        if (!a || !b) continue;
        // Closer meaning = stronger line. Recessive by design: the marks carry the data.
        const strength = 1 - Math.min(1, e.distance);
        const faded = dimmed(e.source) || dimmed(e.target);
        ctx.globalAlpha = faded ? 0.06 : 0.2 + strength * 0.5;
        ctx.strokeStyle = edgeColor;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }

      for (const s of simRef.current) {
        const node = nodeById.get(s.id);
        if (!node) continue;
        const isSelected = selectedId === s.id;
        ctx.globalAlpha = dimmed(s.id) ? 0.18 : 1;

        // A 2px surface ring keeps overlapping marks readable rather than merged.
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r + 2 / view.scale, 0, Math.PI * 2);
        ctx.fillStyle = surface;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = nodeColor;
        ctx.fill();

        // A confirmed fact wears an outer ring — two states, so this is a shape channel
        // rather than a second hue.
        if (node.source === "stated") {
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r + 3.5 / view.scale, 0, Math.PI * 2);
          ctx.lineWidth = 1.5 / view.scale;
          ctx.strokeStyle = nodeColor;
          ctx.stroke();
        }
        if (isSelected) {
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r + 7 / view.scale, 0, Math.PI * 2);
          ctx.lineWidth = 2 / view.scale;
          ctx.strokeStyle = nodeColor;
          ctx.stroke();
        }
      }
      ctx.restore();
    }

    function resize() {
      if (!canvas || !wrap) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = wrap.getBoundingClientRect();
      sizeRef.current = { w: rect.width, h: rect.height };
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    resize();
    const ro = new ResizeObserver(() => {
      resize();
      wake();
    });
    ro.observe(wrap);
    wake();
    return () => {
      cancelAnimationFrame(rafRef.current);
      runningRef.current = false;
      ro.disconnect();
    };
  }, [graph.edges, nodeById, selectedId, highlightIds]);

  // --- pointer: pan, pinch-zoom, hover, select --------------------------------------
  const pointers = React.useRef(new Map<number, { x: number; y: number }>());
  const dragRef = React.useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const pinchRef = React.useRef<number | null>(null);

  function toWorld(clientX: number, clientY: number) {
    const wrap = wrapRef.current;
    if (!wrap) return { x: 0, y: 0 };
    const rect = wrap.getBoundingClientRect();
    const view = viewRef.current;
    return {
      x: (clientX - rect.left - rect.width / 2 - view.x) / view.scale,
      y: (clientY - rect.top - rect.height / 2 - view.y) / view.scale,
    };
  }

  function nodeAt(clientX: number, clientY: number): Sim | null {
    const p = toWorld(clientX, clientY);
    // Reverse order so the mark drawn on top is the one you hit.
    for (let i = simRef.current.length - 1; i >= 0; i--) {
      const s = simRef.current[i];
      // Hit target deliberately larger than the mark.
      const reach = s.r + 8;
      if ((s.x - p.x) ** 2 + (s.y - p.y) ** 2 <= reach * reach) return s;
    }
    return null;
  }

  function onPointerDown(e: React.PointerEvent) {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 1) {
      dragRef.current = { x: e.clientX, y: e.clientY, moved: false };
    } else if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinchRef.current = Math.hypot(a.x - b.x, a.y - b.y);
      dragRef.current = null;
    }
  }

  function onPointerMove(e: React.PointerEvent) {
    if (pointers.current.has(e.pointerId)) {
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    }

    if (pointers.current.size === 2 && pinchRef.current != null) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const view = viewRef.current;
      view.scale = Math.max(0.3, Math.min(3, view.scale * (dist / pinchRef.current)));
      pinchRef.current = dist;
      wakeRef.current();
      return;
    }

    const drag = dragRef.current;
    if (drag) {
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
      viewRef.current.x += dx;
      viewRef.current.y += dy;
      drag.x = e.clientX;
      drag.y = e.clientY;
      setHovered(null);
      wakeRef.current();
      return;
    }

    const hit = nodeAt(e.clientX, e.clientY);
    const node = hit ? nodeById.get(hit.id) : null;
    setHovered(node ? { node, x: e.clientX, y: e.clientY } : null);
  }

  function onPointerUp(e: React.PointerEvent) {
    const wasDrag = dragRef.current?.moved;
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinchRef.current = null;
    dragRef.current = null;
    if (wasDrag) return; // a pan is not a click
    const hit = nodeAt(e.clientX, e.clientY);
    onSelect?.(hit ? (nodeById.get(hit.id) ?? null) : null);
  }

  function onWheel(e: React.WheelEvent) {
    zoomBy(e.deltaY < 0 ? 1.1 : 0.9);
  }

  /* Explicit controls alongside the gestures. A trackpad or a pinch overshoots easily,
     and a fixed step per click is the only way to land somewhere precisely — plus it is
     the sole zoom route available to a keyboard. */
  function zoomBy(factor: number) {
    const view = viewRef.current;
    view.scale = Math.max(0.3, Math.min(3, view.scale * factor));
    setZoom(view.scale);
    wakeRef.current();
  }

  function resetView() {
    viewRef.current = { x: 0, y: 0, scale: 1 };
    alphaRef.current = Math.max(alphaRef.current, 0.25); // nudge the layout back to centre
    setZoom(1);
    wakeRef.current();
  }

  return (
    <div
      ref={wrapRef}
      className={cn("relative touch-none overflow-hidden rounded-xl bg-card", className)}
    >
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`Knowledge graph: ${graph.nodes.length} facts, ${graph.edges.length} connections. Switch to the list view for a readable version.`}
        className="block cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHovered(null)}
        onWheel={onWheel}
      />

      <div className="absolute top-3 right-3 flex flex-col gap-1 rounded-lg border border-border bg-card/90 p-1 shadow-sm backdrop-blur">
        {(
          [
            { label: "Zoom in", icon: Plus, onClick: () => zoomBy(1.25), off: zoom >= 3 },
            { label: "Zoom out", icon: Minus, onClick: () => zoomBy(0.8), off: zoom <= 0.3 },
            { label: "Reset view", icon: Maximize, onClick: resetView, off: false },
          ] as const
        ).map(({ label, icon: Icon, onClick, off }) => (
          <button
            key={label}
            type="button"
            onClick={onClick}
            disabled={off}
            aria-label={label}
            title={label}
            className={cn(
              "grid size-8 place-items-center rounded-md text-muted-foreground transition-colors",
              "hover:bg-accent hover:text-foreground",
              "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
              "disabled:pointer-events-none disabled:opacity-40",
            )}
          >
            <Icon className="size-4" />
          </button>
        ))}
      </div>

      {hovered && (
        <div
          className="pointer-events-none absolute z-10 max-w-64 rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-lg"
          style={{
            left: Math.min(
              hovered.x - (wrapRef.current?.getBoundingClientRect().left ?? 0) + 12,
              (sizeRef.current.w || 0) - 260,
            ),
            top: hovered.y - (wrapRef.current?.getBoundingClientRect().top ?? 0) + 12,
          }}
        >
          <p className="text-popover-foreground">{hovered.node.fact}</p>
          <p className="mt-1 text-muted-foreground capitalize">
            {hovered.node.category} · {hovered.node.source}
          </p>
        </div>
      )}
    </div>
  );
}

/** Explains what the marks mean. An unexplained encoding is decoration. */
export function GraphLegend({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground",
        className,
      )}
    >
      <span className="flex items-center gap-1.5">
        <svg width="26" height="14" aria-hidden="true">
          <circle cx="6" cy="7" r="3.5" fill="var(--viz-node)" />
          <circle cx="18" cy="7" r="6" fill="var(--viz-node)" />
        </svg>
        size = confidence
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="16" height="14" aria-hidden="true">
          <circle cx="8" cy="7" r="4" fill="var(--viz-node)" />
          <circle
            cx="8"
            cy="7"
            r="6"
            fill="none"
            stroke="var(--viz-node)"
            strokeWidth="1.5"
          />
        </svg>
        ring = you confirmed it
      </span>
      <span className="flex items-center gap-1.5">
        <svg width="22" height="14" aria-hidden="true">
          <line x1="1" y1="7" x2="21" y2="7" stroke="var(--viz-edge)" strokeWidth="1.5" />
        </svg>
        line = related meaning
      </span>
    </div>
  );
}
