import * as React from "react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* A themed date+time picker on Radix Popover.
   Hand-built rather than pulling in react-day-picker: this app needs one date, one
   locale, no ranges — the narrow case a general library's size and generality is
   priced for. The cost we accept is owning keyboard and screen-reader semantics,
   which is what most of this file is. Revisit if ranges or localisation arrive. */

const DAY_MS = 86_400_000;

function startOfDay(d: Date): Date {
  const c = new Date(d);
  c.setHours(0, 0, 0, 0);
  return c;
}

function sameDay(a: Date | null, b: Date | null): boolean {
  return !!a && !!b && a.toDateString() === b.toDateString();
}

/** Local-time "YYYY-MM-DDTHH:mm" — never toISOString(), which shifts to UTC and can
 *  land the date on the wrong day. */
function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function monthGrid(view: Date): Date[] {
  const first = new Date(view.getFullYear(), view.getMonth(), 1);
  // grid starts on the Sunday on or before the 1st
  const start = new Date(first.getTime() - first.getDay() * DAY_MS);
  return Array.from({ length: 42 }, (_, i) => new Date(start.getTime() + i * DAY_MS));
}

const WEEKDAYS = (() => {
  // derive short weekday names from the runtime locale rather than hard-coding English
  const base = new Date(2024, 0, 7); // a Sunday
  const fmt = new Intl.DateTimeFormat(undefined, { weekday: "short" });
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(base.getTime() + i * DAY_MS)));
})();

type Props = {
  /** datetime-local string ("YYYY-MM-DDTHH:mm") or "" */
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  /** default time applied when a day is picked and no time is set yet */
  defaultHour?: number;
};

export default function DatePicker({
  value,
  onChange,
  placeholder = "Set a date",
  className,
  defaultHour = 9,
}: Props) {
  const selected = value ? new Date(value) : null;
  const [open, setOpen] = React.useState(false);
  const [view, setView] = React.useState<Date>(() => selected ?? new Date());
  const [focused, setFocused] = React.useState<Date>(() => selected ?? new Date());
  const gridRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (open) {
      const base = selected ?? new Date();
      setView(base);
      setFocused(base);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function commit(day: Date, hour?: number, minute?: number) {
    const next = new Date(day);
    if (hour !== undefined) next.setHours(hour, minute ?? 0, 0, 0);
    else if (selected) next.setHours(selected.getHours(), selected.getMinutes(), 0, 0);
    else next.setHours(defaultHour, 0, 0, 0);
    onChange(toLocalInput(next));
  }

  function preset(days: number) {
    commit(new Date(Date.now() + days * DAY_MS));
    setOpen(false);
  }

  function onGridKeyDown(e: React.KeyboardEvent) {
    const move = (deltaDays: number) => {
      e.preventDefault();
      const next = new Date(focused.getTime() + deltaDays * DAY_MS);
      setFocused(next);
      if (next.getMonth() !== view.getMonth()) setView(next);
    };
    switch (e.key) {
      case "ArrowLeft":
        return move(-1);
      case "ArrowRight":
        return move(1);
      case "ArrowUp":
        return move(-7);
      case "ArrowDown":
        return move(7);
      case "Home":
        return move(-focused.getDay());
      case "End":
        return move(6 - focused.getDay());
      case "PageUp": {
        e.preventDefault();
        const p = new Date(focused);
        p.setMonth(p.getMonth() - 1);
        setFocused(p);
        setView(p);
        return;
      }
      case "PageDown": {
        e.preventDefault();
        const n = new Date(focused);
        n.setMonth(n.getMonth() + 1);
        setFocused(n);
        setView(n);
        return;
      }
      case "Enter":
      case " ":
        e.preventDefault();
        commit(focused);
        setOpen(false);
        return;
    }
  }

  const label = selected
    ? selected.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : placeholder;

  const today = startOfDay(new Date());
  const days = monthGrid(view);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-label={selected ? `Due ${label}. Change date` : placeholder}
          className={cn(
            "flex h-11 items-center gap-2 rounded-lg border border-border bg-background px-3",
            "text-sm transition-colors outline-none hover:bg-accent/50",
            "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
            selected ? "text-foreground" : "text-muted-foreground",
            className,
          )}
        >
          {/* currentColor, so the icon is never a black glyph on a dark field */}
          <CalendarDays className="size-4 shrink-0 opacity-70" />
          <span className="truncate">{label}</span>
        </button>
      </PopoverPrimitive.Trigger>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={6}
          className={cn(
            "z-50 w-[19rem] rounded-xl border border-border bg-popover p-3 text-popover-foreground",
            "shadow-lg animate-in fade-in-0 zoom-in-95",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          )}
        >
          {/* presets first — the common cases shouldn't need the grid at all */}
          <div className="mb-3 flex flex-wrap gap-1.5">
            <Button variant="secondary" size="sm" onClick={() => preset(0)}>
              Today
            </Button>
            <Button variant="secondary" size="sm" onClick={() => preset(1)}>
              Tomorrow
            </Button>
            <Button variant="secondary" size="sm" onClick={() => preset(7)}>
              Next week
            </Button>
            {selected && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto text-muted-foreground"
                onClick={() => {
                  onChange("");
                  setOpen(false);
                }}
              >
                <X className="size-3.5" /> Clear
              </Button>
            )}
          </div>

          <div className="mb-2 flex items-center justify-between">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Previous month"
              onClick={() => setView(new Date(view.getFullYear(), view.getMonth() - 1, 1))}
            >
              <ChevronLeft />
            </Button>
            <span aria-live="polite" className="text-sm font-medium">
              {view.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Next month"
              onClick={() => setView(new Date(view.getFullYear(), view.getMonth() + 1, 1))}
            >
              <ChevronRight />
            </Button>
          </div>

          <div className="grid grid-cols-7 gap-0.5 text-center text-[11px] text-muted-foreground">
            {WEEKDAYS.map((d) => (
              <div key={d} className="py-1">
                {d}
              </div>
            ))}
          </div>

          {/* one tab stop for the whole grid, arrows move within it (WAI-ARIA grid) */}
          <div
            ref={gridRef}
            role="grid"
            aria-label="Choose a date"
            tabIndex={0}
            onKeyDown={onGridKeyDown}
            className="grid grid-cols-7 gap-0.5 rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            {days.map((d) => {
              const outside = d.getMonth() !== view.getMonth();
              const isSel = sameDay(d, selected);
              const isToday = sameDay(d, today);
              const isFocused = sameDay(d, focused);
              return (
                <button
                  key={d.toISOString()}
                  type="button"
                  role="gridcell"
                  tabIndex={-1}
                  aria-selected={isSel}
                  aria-current={isToday ? "date" : undefined}
                  onClick={() => {
                    commit(d);
                    setOpen(false);
                  }}
                  className={cn(
                    "grid h-9 place-items-center rounded-md text-sm transition-colors",
                    outside && "text-faint",
                    !isSel && "hover:bg-accent",
                    isSel && "bg-primary font-medium text-primary-foreground",
                    isToday && !isSel && "font-semibold text-primary",
                    isFocused && !isSel && "ring-1 ring-ring/60",
                  )}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex items-center gap-2 border-t border-border pt-3">
            <label htmlFor="dp-time" className="text-xs text-muted-foreground">
              Time
            </label>
            <input
              id="dp-time"
              type="time"
              value={selected ? toLocalInput(selected).slice(11) : ""}
              onChange={(e) => {
                const [h, m] = e.target.value.split(":").map(Number);
                if (!Number.isNaN(h)) commit(selected ?? new Date(), h, m || 0);
              }}
              className="h-9 rounded-md border border-border bg-background px-2 text-sm"
            />
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
