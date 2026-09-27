import { useCallback, useId, useState, type ComponentType, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, ChevronRight, CircleAlert, Info } from "lucide-react";

import { InfoTip } from "@/components/InfoTip";
import { cn } from "@/lib/utils";

/* The pieces every Investments panel is built from.
 *
 * ⚠ One of each, on purpose. Before this the page had six different ways to hide a panel — an
 * underlined "show", a "Show" button with a chevron, a `<details>`, a "hide" link, a "Review
 * them" button, and panels with no toggle at all — none of which remembered its state and none
 * of which told a screen reader whether it was open. Every panel choosing its own was how a
 * beginner ended up unable to tell which grey text mattered.
 *
 * ⚠ Tone is STATE, never decoration: good, caution, bad, info, and a neutral. Each comes from
 * the tokens in index.css, has its own dark-mode step, and is always paired with an icon or a
 * word — a red number and a green number are the same number to a reader who cannot tell the
 * two colours apart.
 */

export type Tone = "good" | "caution" | "bad" | "info" | "neutral" | "accent";

const TEXT: Record<Tone, string> = {
  good: "text-good",
  caution: "text-caution",
  bad: "text-bad",
  info: "text-info",
  neutral: "text-muted-foreground",
  accent: "text-primary",
};

const SOFT: Record<Tone, string> = {
  good: "border-good/30 bg-good/10 text-good",
  caution: "border-caution/35 bg-caution/10 text-caution",
  bad: "border-bad/35 bg-bad/10 text-bad",
  info: "border-info/30 bg-info/10 text-info",
  neutral: "border-border bg-muted/60 text-muted-foreground",
  accent: "border-primary/30 bg-primary/10 text-primary",
};

const BAR: Record<Tone, string> = {
  good: "bg-good",
  caution: "bg-caution",
  bad: "bg-bad",
  info: "bg-info",
  neutral: "bg-muted-foreground/60",
  accent: "bg-primary",
};

const EDGE: Record<Tone, string> = {
  good: "border-good/40 bg-good/4",
  caution: "border-caution/45 bg-caution/5",
  bad: "border-bad/45 bg-bad/5",
  info: "border-info/35 bg-info/4",
  neutral: "border-border bg-card",
  accent: "border-primary/40 bg-primary/4",
};

/** Open or closed, remembered per section on this device.
 *
 *  ⚠ A viewer convenience and nothing more, so `localStorage` is right for it — and it can
 *  throw in a private window, so both halves are guarded and the section still works for the
 *  visit when nothing can be stored. */
function useRememberedOpen(key: string | undefined, fallback: boolean) {
  const storageKey = key ? `aceroai.section.${key}` : null;
  const [open, setOpen] = useState<boolean>(() => {
    if (!storageKey) return fallback;
    try {
      const stored = window.localStorage.getItem(storageKey);
      return stored == null ? fallback : stored === "1";
    } catch {
      return fallback;
    }
  });
  const toggle = useCallback(() => {
    setOpen((was) => {
      const next = !was;
      if (storageKey) {
        try {
          window.localStorage.setItem(storageKey, next ? "1" : "0");
        } catch {
          /* Not remembered this time; still toggles. */
        }
      }
      return next;
    });
  }, [storageKey]);
  return [open, toggle, setOpen] as const;
}

/** A panel with a header that always says what is inside it.
 *
 *  ⚠ `summary` is the point. A closed section hides the detail, never the fact: "40 refused —
 *  mostly the price" closed is worth reading, and a bare "show" is not. The whole header is the
 *  control (a real button, with `aria-expanded`), and anything interactive in the header —
 *  an "i", an action — sits beside it rather than inside it, because a button inside a button
 *  is not a thing a keyboard or a screen reader can use. */
export function Section({
  id,
  memory,
  icon: Icon,
  title,
  summary,
  count,
  countTone = "neutral",
  tip,
  actions,
  collapsible = true,
  defaultOpen = true,
  tone = "neutral",
  flush = false,
  className,
  children,
}: {
  /** DOM id, so the "needs you" list can scroll here. */
  id?: string;
  /** Key the open state is remembered under. Omit for sections that should not remember. */
  memory?: string;
  icon?: ComponentType<{ className?: string }>;
  title: ReactNode;
  summary?: ReactNode;
  count?: number;
  countTone?: Tone;
  tip?: ReactNode;
  actions?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  tone?: Tone;
  /** Body without padding, for lists whose rows run edge to edge. */
  flush?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const [open, toggle] = useRememberedOpen(memory, defaultOpen);
  const bodyId = useId();
  const shown = !collapsible || open;

  const heading = (
    <>
      {collapsible && (
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform duration-150",
            open && "rotate-90",
          )}
        />
      )}
      {Icon && <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold">
          {title}
          {count != null && count > 0 && <Count n={count} tone={countTone} />}
        </span>
        {summary && (
          <span className="mt-0.5 block text-xs font-normal text-muted-foreground">{summary}</span>
        )}
      </span>
    </>
  );

  return (
    <section id={id} className={cn("scroll-mt-4 rounded-xl border", EDGE[tone], className)}>
      <div className="flex items-start gap-2 px-3 py-3 sm:px-4">
        {collapsible ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={toggle}
            className="-m-1 flex min-w-0 flex-1 items-start gap-2.5 rounded-md p-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {heading}
          </button>
        ) : (
          <div className="flex min-w-0 flex-1 items-start gap-2.5">{heading}</div>
        )}
        {tip && (
          <span className="mt-0.5">
            <InfoTip label="What this is">{tip}</InfoTip>
          </span>
        )}
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </div>
      {shown && (
        <div id={bodyId} className={cn("border-t border-border", !flush && "px-3 py-3 sm:px-4")}>
          {children}
        </div>
      )}
    </section>
  );
}

/** How many things are waiting — on a tab, or a section header. */
export function Count({
  n,
  tone = "neutral",
  label,
}: {
  n: number;
  tone?: Tone;
  label?: string;
}) {
  const solid: Record<Tone, string> = {
    bad: "bg-bad text-white dark:text-[#1f1e1b]",
    caution: "bg-caution text-white dark:text-[#1f1e1b]",
    accent: "bg-primary text-primary-foreground",
    good: "bg-good text-white dark:text-[#1f1e1b]",
    info: "bg-info text-white dark:text-[#1f1e1b]",
    neutral: "bg-muted text-muted-foreground ring-1 ring-border",
  };
  return (
    <span
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-semibold tabular-nums leading-none",
        solid[tone],
      )}
    >
      {n}
      {label && <span className="sr-only"> {label}</span>}
    </span>
  );
}

/** A score out of a maximum, drawn as well as written.
 *
 *  ⚠ The bar carries `role="meter"` and its value, so it is not a picture a screen reader
 *  skips. The tone follows the proportion unless the caller knows better — and the numbers
 *  are always printed beside it, so the colour is never the only way to read it. */
export function Meter({
  value,
  max,
  label,
  tone,
  text,
  className,
  width = "w-16",
}: {
  value: number;
  max: number;
  label: string;
  tone?: Tone;
  text?: string;
  className?: string;
  width?: string;
}) {
  const share = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const t = tone ?? (share >= 0.7 ? "good" : share >= 0.4 ? "caution" : "bad");
  const shown = text ?? `${trim(value)}/${trim(max)}`;
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={`${trim(value)} of ${trim(max)}`}
        className={cn("relative h-1.5 shrink-0 overflow-hidden rounded-full bg-muted", width)}
      >
        <span
          className={cn("absolute inset-y-0 left-0 rounded-full", BAR[t])}
          style={{ width: `${share * 100}%` }}
        />
      </span>
      <span className="shrink-0 text-xs font-semibold tabular-nums">{shown}</span>
    </span>
  );
}

function trim(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** A short state label: a tone, an optional icon, a word. */
export function Chip({
  tone = "neutral",
  icon: Icon,
  title,
  className,
  children,
}: {
  tone?: Tone;
  icon?: ComponentType<{ className?: string }>;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        SOFT[tone],
        className,
      )}
    >
      {Icon && <Icon className="size-3 shrink-0" aria-hidden="true" />}
      <span className="truncate">{children}</span>
    </span>
  );
}

const CALLOUT_ICON: Record<Tone, ComponentType<{ className?: string }>> = {
  bad: CircleAlert,
  caution: AlertTriangle,
  good: CheckCircle2,
  info: Info,
  neutral: Info,
  accent: Info,
};

/** Something that needs reading before the rest: a fired condition, a company waiting for
 *  agreement, a split the ledger has not caught up with. Tone and icon, never colour alone. */
export function Callout({
  id,
  tone = "caution",
  icon,
  title,
  action,
  className,
  children,
}: {
  id?: string;
  tone?: Tone;
  icon?: ComponentType<{ className?: string }>;
  title: ReactNode;
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  const Icon = icon ?? CALLOUT_ICON[tone];
  return (
    <div
      id={id}
      role={tone === "bad" ? "alert" : undefined}
      className={cn("flex scroll-mt-4 gap-3 rounded-xl border p-3 sm:p-4", EDGE[tone], className)}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", TEXT[tone])} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{title}</div>
        {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
        {action && <div className="mt-3 flex flex-wrap items-center gap-2">{action}</div>}
      </div>
    </div>
  );
}

/** The quiet state — nothing suggested, nothing waiting — said in one line, not a panel.
 *
 *  ⚠ Said rather than left blank: an empty area reads as broken, and a screen that looks
 *  broken when the system is behaving well teaches its reader to distrust it. */
export function Quiet({
  icon: Icon = CheckCircle2,
  children,
  className,
}: {
  icon?: ComponentType<{ className?: string }>;
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={cn("flex items-start gap-2 text-sm text-muted-foreground", className)}>
      <Icon className="mt-0.5 size-4 shrink-0 text-faint" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

/** A labelled figure: small label, the number, and an optional line under it. */
export function Figure({
  label,
  value,
  hint,
  valueClass,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  valueClass?: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-0.5 text-base font-semibold tabular-nums", valueClass)}>{value}</p>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
