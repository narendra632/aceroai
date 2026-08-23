import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { ICONS, type IconName } from "@/lib/learn/icons";
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
 * Three things carry the meaning before any label is read: the ICON says what kind of work
 * happens, the STEP NUMBER says where you are in the sequence, and the FILL separates work
 * (solid) from storage (tinted) from what does not exist yet (ghosted).
 */

export type NodeKind = "stage" | "store" | "external" | "planned";

export type FlowNode = {
  id: string;
  label: string;
  /** One short line under the label. Not a description — a hint at what happens here. */
  hint?: string;
  icon?: IconName;
  /** Position on the main path. Omitted for anything off to the side. */
  step?: number;
  /** 1-based grid position. Nodes may share a row to sit side by side. */
  col: number;
  row: number;
  kind?: NodeKind;
};

export type FlowEdge = {
  from: string;
  to: string;
  /** Drawn as a small pill at the midpoint. Keep it to a word or two. */
  label?: string;
  /** A branch that is not the main path — drawn dashed. */
  dashed?: boolean;
};

type Segment = {
  d: string;
  dashed: boolean;
  label?: string;
  lx: number;
  ly: number;
};

const KIND: Record<
  NodeKind,
  { card: string; chip: string; icon: string }
> = {
  stage: {
    card: "border-border bg-card hover:border-primary/60 hover:shadow-sm",
    chip: "bg-primary/10",
    icon: "text-primary",
  },
  store: {
    card: "border-border/80 bg-secondary/70 hover:border-primary/40",
    chip: "bg-background/70",
    icon: "text-muted-foreground",
  },
  external: {
    card: "border-dashed border-border bg-card hover:border-primary/50",
    chip: "bg-secondary",
    icon: "text-muted-foreground",
  },
  // Ghosted and badged. A learning tool that lets "planned" read as "built" teaches the
  // wrong thing, so the treatment has to land before the label is read.
  planned: {
    card: "border-dashed border-border/60 bg-transparent",
    chip: "bg-secondary/50",
    icon: "text-faint",
  },
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

      const sameColumn = Math.abs(a.left - b.left) < 4;
      let x1: number, y1: number, x2: number, y2: number;

      if (stacked || sameColumn) {
        // vertical: leave the bottom edge, arrive at the top edge
        x1 = a.left + a.width / 2 - origin.left;
        y1 = a.bottom - origin.top;
        x2 = b.left + b.width / 2 - origin.left;
        y2 = b.top - origin.top;
      } else {
        // sideways: leave the right edge, arrive at the left edge
        x1 = a.right - origin.left;
        y1 = a.top + a.height / 2 - origin.top;
        x2 = b.left - origin.left;
        y2 = b.top + b.height / 2 - origin.top;
      }

      // A curve, not a diagonal. Two boxes joined by a straight diagonal read as "these
      // are at an angle to each other"; a curve reads as "this flows into that".
      const vertical = stacked || sameColumn;
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;
      const d = vertical
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
    <div ref={hostRef} className={cn("relative", className)} role="group" aria-label={ariaLabel}>
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
        width={box.w}
        height={box.h}
        aria-hidden="true"
      >
        <defs>
          <marker
            id="flow-arrow"
            viewBox="0 0 12 12"
            refX="10"
            refY="6"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 1 1 L 11 6 L 1 11 z" fill="var(--viz-edge)" />
          </marker>
        </defs>
        {segments.map((s, i) => (
          <g key={i}>
            <path
              d={s.d}
              fill="none"
              stroke="var(--viz-edge)"
              strokeWidth={s.dashed ? 1.5 : 2}
              strokeLinecap="round"
              strokeDasharray={s.dashed ? "4 5" : undefined}
              markerEnd="url(#flow-arrow)"
            />
            {s.label && (
              <>
                {/* The label sits ON the line, so it needs the line cleared behind it —
                    otherwise the stroke runs straight through the text. */}
                <rect
                  x={s.lx - s.label.length * 3.4 - 6}
                  y={s.ly - 8}
                  width={s.label.length * 6.8 + 12}
                  height={16}
                  rx={8}
                  fill="var(--background)"
                  stroke="var(--border)"
                  strokeWidth={1}
                />
                <text
                  x={s.lx}
                  y={s.ly + 3.5}
                  textAnchor="middle"
                  className="fill-muted-foreground"
                  style={{ fontSize: 10 }}
                >
                  {s.label}
                </text>
              </>
            )}
          </g>
        ))}
      </svg>

      <div
        className="relative grid gap-x-10 gap-y-6"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {nodes.map((node) => {
          const kind = node.kind ?? "stage";
          const tone = KIND[kind];
          const Icon = node.icon ? ICONS[node.icon] : null;
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
                "group relative z-10 flex min-h-14 items-center gap-3 rounded-xl border px-3 py-2.5 text-left",
                "transition-[border-color,box-shadow,transform] duration-150",
                "focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
                tone.card,
                isSelected && "border-primary shadow-sm ring-[3px] ring-primary/25",
              )}
            >
              {Icon && (
                <span
                  className={cn(
                    "grid size-8 flex-none place-items-center rounded-lg transition-colors",
                    tone.chip,
                    isSelected && kind === "stage" && "bg-primary/20",
                  )}
                >
                  <Icon className={cn("size-4", tone.icon)} />
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline gap-1.5">
                  {node.step !== undefined && (
                    <span className="text-[10px] font-medium tabular-nums text-faint">
                      {node.step}
                    </span>
                  )}
                  <span
                    className={cn(
                      "block truncate text-sm leading-snug font-medium",
                      kind === "planned" && "text-muted-foreground",
                    )}
                  >
                    {node.label}
                  </span>
                </span>
                {node.hint && (
                  <span className="mt-0.5 block truncate text-[11px] leading-snug text-muted-foreground">
                    {node.hint}
                  </span>
                )}
              </span>
              {kind === "planned" && (
                <span className="flex-none rounded-md bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground">
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
