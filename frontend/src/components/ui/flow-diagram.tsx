import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/* A diagram whose boxes can be clicked.
 *
 * Deliberately not Mermaid. Mermaid is the right tool for a diagram inside a *document* —
 * which is why docs/ uses it for all eleven — and the wrong one for an interactive
 * component. The requirement here is not "render a flowchart": it is click a node and get a
 * panel, reachable by keyboard, correct in dark mode, usable at 375px, in this app's
 * palette. Mermaid's click directives fight React state, its SVG output resists theming,
 * and it would add ~500KB for the privilege.
 *
 * So: nodes are real <button> elements on a CSS grid, which makes keyboard reach, focus
 * rings and touch targets fall out of the platform rather than being reimplemented. Edges
 * are drawn in an SVG overlay from the nodes' MEASURED positions, so there is one code path
 * for every screen width — at 375px the grid collapses to a single column and the same
 * measuring code draws short vertical connectors instead of long diagonal ones.
 *
 * This matches how the rest of the app's visuals are built: force-graph and waterfall are
 * both hand-rolled for the same reasons.
 */

export type NodeKind = "stage" | "store" | "external" | "planned";

export type FlowNode = {
  id: string;
  label: string;
  /** One short line under the label. Not a description — a hint at what happens here. */
  hint?: string;
  /** 1-based grid position. Nodes may share a cell row to sit side by side. */
  col: number;
  row: number;
  kind?: NodeKind;
};

export type FlowEdge = {
  from: string;
  to: string;
  /** Drawn as a small label at the midpoint. Keep it to a word or two. */
  label?: string;
  /** A branch that is not the main path — drawn dashed. */
  dashed?: boolean;
};

type Segment = { d: string; dashed: boolean; label?: string; lx: number; ly: number };

const KIND_CLASS: Record<NodeKind, string> = {
  stage: "border-border bg-card",
  store: "border-border bg-secondary",
  external: "border-dashed border-border bg-card",
  // Muted and marked. A learning tool that lets "planned" read as "built" teaches the
  // wrong thing, so the treatment has to be visible without reading the label.
  planned: "border-dashed border-border/70 bg-transparent text-muted-foreground",
};

export function FlowDiagram({
  nodes,
  edges,
  selected,
  onSelect,
  className,
  ariaLabel,
}: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  className?: string;
  ariaLabel: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef(new Map<string, HTMLButtonElement>());
  const [segments, setSegments] = useState<Segment[]>([]);
  const [box, setBox] = useState({ w: 0, h: 0 });

  const cols = Math.max(...nodes.map((n) => n.col), 1);

  const measure = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;
    const origin = host.getBoundingClientRect();
    setBox({ w: origin.width, h: origin.height });

    // Stacked (one column) vs laid out: decided from the MEASURED geometry rather than a
    // media query, so it stays correct inside any container, not just at a page width.
    const first = nodes[0] && nodeRefs.current.get(nodes[0].id)?.getBoundingClientRect();
    const stacked = !!first && first.width > origin.width * 0.75;

    const next: Segment[] = [];
    for (const edge of edges) {
      const a = nodeRefs.current.get(edge.from)?.getBoundingClientRect();
      const b = nodeRefs.current.get(edge.to)?.getBoundingClientRect();
      if (!a || !b) continue; // a dangling edge is caught by a test, not drawn as a guess

      let x1: number, y1: number, x2: number, y2: number;
      if (stacked || Math.abs(a.left - b.left) < 4) {
        // vertical: leave the bottom edge, arrive at the top edge
        x1 = a.left + a.width / 2 - origin.left;
        y1 = a.bottom - origin.top;
        x2 = b.left + b.width / 2 - origin.left;
        y2 = b.top - origin.top;
      } else {
        // horizontal: leave the right edge, arrive at the left edge
        x1 = a.right - origin.left;
        y1 = a.top + a.height / 2 - origin.top;
        x2 = b.left - origin.left;
        y2 = b.top + b.height / 2 - origin.top;
      }

      // A gentle curve rather than a straight line: two boxes on different rows joined by
      // a diagonal read as "diagonal", where a curve reads as "flows into".
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;
      const d =
        stacked || Math.abs(x1 - x2) < 4
          ? `M ${x1} ${y1} L ${x2} ${y2}`
          : `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
      next.push({ d, dashed: !!edge.dashed, label: edge.label, lx: mx, ly: my });
    }
    setSegments(next);
  }, [edges, nodes]);

  useLayoutEffect(measure, [measure]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    for (const el of nodeRefs.current.values()) ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  return (
    <div
      ref={hostRef}
      className={cn("relative", className)}
      role="group"
      aria-label={ariaLabel}
    >
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
        width={box.w}
        height={box.h}
        aria-hidden="true"
      >
        <defs>
          <marker
            id="flow-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-[var(--viz-edge)]" />
          </marker>
        </defs>
        {segments.map((s, i) => (
          <g key={i}>
            <path
              d={s.d}
              fill="none"
              stroke="var(--viz-edge)"
              strokeWidth={2}
              strokeDasharray={s.dashed ? "5 4" : undefined}
              markerEnd="url(#flow-arrow)"
            />
            {s.label && (
              <text
                x={s.lx}
                y={s.ly - 5}
                textAnchor="middle"
                className="fill-muted-foreground text-[10px]"
              >
                {s.label}
              </text>
            )}
          </g>
        ))}
      </svg>

      <div
        className="relative grid gap-x-8 gap-y-5"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {nodes.map((node) => {
          const kind = node.kind ?? "stage";
          const isSelected = selected === node.id;
          return (
            <button
              key={node.id}
              ref={(el) => {
                if (el) nodeRefs.current.set(node.id, el);
                else nodeRefs.current.delete(node.id);
              }}
              type="button"
              // Selecting the same node again clears it, so the panel can be dismissed
              // from the diagram as well as from the panel.
              onClick={() => onSelect(isSelected ? null : node.id)}
              aria-pressed={isSelected}
              style={{ gridColumn: node.col, gridRow: node.row }}
              className={cn(
                "relative z-10 rounded-xl border px-3 py-2.5 text-left transition",
                "min-h-11", // a 44px touch target, per the UI standard
                "hover:border-primary/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                KIND_CLASS[kind],
                isSelected && "border-primary ring-[3px] ring-primary/25",
              )}
            >
              <span className="block text-sm leading-snug font-medium">{node.label}</span>
              {node.hint && (
                <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                  {node.hint}
                </span>
              )}
              {kind === "planned" && (
                <span className="mt-1 inline-block rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
                  planned
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
