import * as React from "react";

import { formatDay, formatUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

/* Charts, written directly as SVG.
 *
 * No charting library. The same trade the Select and DatePicker primitives made: own the
 * behaviour, keep the dependency list at zero, and get colours from theme tokens so light
 * and dark are correct by construction rather than by overriding a library's defaults.
 *
 * Rules these follow, and the reasons:
 *   - ONE axis. Never two y-scales — the single most misleading thing a chart can do.
 *   - Hues are assigned in fixed order and follow the ENTITY, so hiding a series never
 *     repaints the others.
 *   - A legend whenever there are 2+ series, AND direct labels. Colour alone never
 *     carries identity: the palette's worst pair sits in a colour-blind-unsafe band that
 *     is only legal with that second channel.
 *   - Grid and axes are recessive; the data is the only thing with weight.
 *   - Text wears text tokens, never a series colour.
 *   - Axis numbers use tabular figures so they don't jitter as values change.
 */

const AXIS_FONT = 11;

/** Measure the container so text stays crisp — scaling a viewBox would blur it. */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = React.useRef<T>(null);
  const [width, setWidth] = React.useState(0);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Round an axis maximum up to a readable number: 0/25/50/75/100, never 0/23.7/47.4. */
function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => value <= s * magnitude) ?? 10;
  return step * magnitude;
}

function ticksFor(max: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, i) => (max / count) * i);
}

// --- stacked area over time ---------------------------------------------------------

export type Series = { key: string; label: string; color: string };

type StackedAreaProps = {
  /** One entry per bucket, in order. `values` is keyed by series key. */
  data: { day: string; values: Record<string, number> }[];
  series: Series[];
  height?: number;
  format?: (n: number) => string;
  className?: string;
};

export function StackedArea({
  data,
  series,
  height = 200,
  format = formatUSD,
  className,
}: StackedAreaProps) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = React.useState<number | null>(null);

  const pad = { top: 8, right: 8, bottom: 22, left: 52 };
  const plotW = Math.max(0, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;

  const totals = data.map((d) => series.reduce((sum, s) => sum + (d.values[s.key] ?? 0), 0));
  const max = niceMax(Math.max(...totals, 0));
  const x = (i: number) => (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const y = (v: number) => plotH - (v / max) * plotH;

  // Cumulative bands, bottom series first, so each sits on the one below it.
  const bands = series.map((s, si) => {
    const lower = data.map((d) =>
      series.slice(0, si).reduce((sum, o) => sum + (d.values[o.key] ?? 0), 0),
    );
    const upper = lower.map((base, i) => base + (data[i].values[s.key] ?? 0));
    return { series: s, lower, upper };
  });

  if (width === 0) return <div ref={ref} style={{ height }} className={className} />;

  // A single bucket has no line to draw between points, so the area path collapses to
  // nothing and the chart renders blank — which is what a first day of recording looks
  // like. Draw it as a column instead: one day of data is still data.
  const singleBucket = data.length === 1;

  return (
    <div ref={ref} className={cn("relative", className)}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`Spend over time, ${data.length} days`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = e.clientX - rect.left - pad.left;
          if (data.length === 0) return;
          const i = Math.round((px / plotW) * (data.length - 1));
          setHover(Math.max(0, Math.min(data.length - 1, i)));
        }}
      >
        <g transform={`translate(${pad.left},${pad.top})`}>
          {ticksFor(max).map((t) => (
            <g key={t}>
              <line
                x1={0}
                x2={plotW}
                y1={y(t)}
                y2={y(t)}
                stroke="var(--chart-grid)"
                strokeWidth={1}
              />
              <text
                x={-8}
                y={y(t)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={AXIS_FONT}
                fill="var(--muted-foreground)"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {format(t)}
              </text>
            </g>
          ))}

          {singleBucket &&
            bands.map(({ series: s, lower, upper }) => {
              const top = y(upper[0]);
              const bottom = y(lower[0]);
              if (bottom - top < 0.5) return null;
              return (
                <rect
                  key={s.key}
                  x={plotW / 2 - 18}
                  width={36}
                  y={top}
                  height={Math.max(1, bottom - top)}
                  fill={s.color}
                  stroke="var(--card)"
                  strokeWidth={2}
                  rx={2}
                />
              );
            })}

          {!singleBucket &&
            bands.map(({ series: s, lower, upper }) => {
            const top = upper.map((v, i) => `${x(i)},${y(v)}`).join(" L ");
            const bottom = [...lower].reverse().map((v, i) => {
              const idx = lower.length - 1 - i;
              return `${x(idx)},${y(v)}`;
            });
            return (
              <g key={s.key}>
                <path
                  d={`M ${top} L ${bottom.join(" L ")} Z`}
                  fill={s.color}
                  fillOpacity={0.85}
                  // A 2px gap in the surface colour keeps stacked bands from merging
                  // into one shape at a glance.
                  stroke="var(--card)"
                  strokeWidth={2}
                  strokeLinejoin="round"
                />
              </g>
            );
          })}

          {hover != null && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={0}
              y2={plotH}
              stroke="var(--chart-axis)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
          )}

          <line
            x1={0}
            x2={plotW}
            y1={plotH}
            y2={plotH}
            stroke="var(--chart-axis)"
            strokeWidth={1}
          />
          {data.map((d, i) =>
            // Roughly six labels, whatever the range.
            i % Math.max(1, Math.ceil(data.length / 6)) === 0 ? (
              <text
                key={d.day}
                x={x(i)}
                y={plotH + 15}
                textAnchor="middle"
                fontSize={AXIS_FONT}
                fill="var(--muted-foreground)"
              >
                {formatDay(d.day)}
              </text>
            ) : null,
          )}
        </g>
      </svg>

      {hover != null && data[hover] && (
        <div
          className="pointer-events-none absolute top-2 z-10 min-w-40 rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-lg"
          style={{
            left: Math.min(Math.max(0, x(hover) + pad.left - 70), Math.max(0, width - 170)),
          }}
        >
          <p className="font-medium text-popover-foreground">{formatDay(data[hover].day)}</p>
          {series.map((s) => (
            <p key={s.key} className="mt-1 flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span
                  className="inline-block size-2 rounded-full"
                  style={{ background: s.color }}
                  aria-hidden
                />
                {s.label}
              </span>
              <span
                className="text-popover-foreground"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {format(data[hover].values[s.key] ?? 0)}
              </span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// --- horizontal bars ----------------------------------------------------------------

type BarsProps = {
  data: { label: string; value: number; hint?: string; tag?: string }[];
  format?: (n: number) => string;
  className?: string;
};

/** Horizontal because the labels are model names, which do not fit under a vertical bar.
 *  One hue: this is a single measure across categories, so colour would merely repeat
 *  what the labels already say. */
export function Bars({ data, format = formatUSD, className }: BarsProps) {
  const max = Math.max(...data.map((d) => d.value), 0) || 1;
  return (
    <ul className={cn("space-y-2.5", className)}>
      {data.map((d) => (
        <li key={d.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="truncate">{d.label}</span>
              {d.tag && (
                <span className="shrink-0 rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground">
                  {d.tag}
                </span>
              )}
            </span>
            <span
              className="shrink-0 text-muted-foreground"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {format(d.value)}
              {d.hint && <span className="ml-1.5 text-faint">{d.hint}</span>}
            </span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(1.5, (d.value / max) * 100)}%`,
                background: "var(--series-1)",
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

// --- sparkline ----------------------------------------------------------------------

/** A trend beside a headline number. No axes on purpose — it answers "which way is this
 *  going", and gridlines would imply a precision it is not offering. */
export function Sparkline({
  values,
  width = 88,
  height = 26,
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  className?: string;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 0) || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * (width - 2) + 1;
    const y = height - 2 - (v / max) * (height - 4);
    return `${x},${y}`;
  });
  return (
    <svg width={width} height={height} className={className} aria-hidden>
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke="var(--series-1)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// --- legend -------------------------------------------------------------------------

export function Legend({ series, className }: { series: Series[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs", className)}>
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5 text-muted-foreground">
          <span
            className="inline-block size-2.5 rounded-sm"
            style={{ background: s.color }}
            aria-hidden
          />
          {s.label}
        </li>
      ))}
    </ul>
  );
}
