/* What the machine is doing right now.
 *
 * Acero runs on a 1 GB / 10 GB shared-core VM with no database backup. Until this existed,
 * the numbers that decide whether that is still a safe bet were visible only over SSH —
 * which means visible only after something had already gone wrong.
 *
 * Three decisions worth knowing before changing anything here:
 *
 * **It is bordered, and the border is doing semantic work.** These readings are "right
 * now". The sibling box below is scoped to a selected range. Five tiles that looked exactly
 * like the four cost tiles, sitting directly above them, would invite the reading that
 * "Disk" is also a 30-day figure.
 *
 * So each box carries its own heading naming its own time — "Server · right now" against
 * "Cost and speed · last 30 days" — and the range control lives INSIDE the second one, on
 * its heading line. A single range control floating above both was the first attempt, and
 * it left exactly the ambiguity the border exists to remove.
 *
 * **A reading that cannot be taken is omitted, never drawn as zero.** `/proc` is Linux
 * only, so on a Windows development machine memory and load are genuinely absent. A zero
 * would be a wrong answer wearing the same confidence as a right one, and "0% memory
 * pressure" is the most reassuring possible way to say "I have no idea".
 *
 * **It is quiet when everything is fine.** Colour appears only at the thresholds. A
 * monitoring display that draws the eye while nothing is wrong trains you to stop looking,
 * which costs you the one moment it exists for.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";

import * as api from "@/lib/api";
import type { Capacity, Vitals } from "@/lib/api";
import { cn } from "@/lib/utils";

/** 10 seconds, not 5.
 *
 * Nothing measured here moves meaningfully inside five seconds — a 10 GB disk, a database
 * growing a few MB a day, a load average that is itself a 60-second mean. Halving the
 * interval would double the request rate against the very machine being measured, for no
 * additional information. */
const POLL_MS = 10_000;

/** Above this fraction of a capacity the reading is marked. Disk gets its threshold from
 *  the server instead, so the page and the `disk_watch` job cannot disagree about what
 *  "getting full" means. */
const MEMORY_WARN = 85;
const MEMORY_SERIOUS = 95;

function gb(bytes: number): string {
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}

function mb(bytes: number): string {
  const m = bytes / 1_000_000;
  return m >= 1000 ? `${(m / 1000).toFixed(1)} GB` : `${Math.round(m)} MB`;
}

function since(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return `${Math.max(0, seconds)}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function uptime(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

type Tone = "ok" | "warn" | "bad";

function Tile({
  label,
  value,
  hint,
  fill,
  tone = "ok",
}: {
  label: string;
  value: string;
  hint?: string;
  /** 0-100. Present only for the two readings that are genuinely proportions. */
  fill?: number;
  tone?: Tone;
}) {
  return (
    <div className="min-w-0 flex-1 basis-[9rem] rounded-lg border border-border/60 bg-muted/40 px-3 py-2.5">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 truncate text-base font-semibold",
          tone === "warn" && "text-[var(--warn,theme(colors.amber.600))]",
          tone === "bad" && "text-destructive",
        )}
        style={{ fontVariantNumeric: "tabular-nums" }}
      >
        {value}
      </p>
      {fill !== undefined && (
        <div
          className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`${Math.round(fill)}% used`}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-500",
              tone === "ok" && "bg-muted-foreground/40",
              tone === "warn" && "bg-amber-500",
              tone === "bad" && "bg-destructive",
            )}
            style={{ width: `${Math.min(100, Math.max(2, fill))}%` }}
          />
        </div>
      )}
      {hint && (
        <p className="mt-1 truncate text-[11px] text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function toneFor(percent: number, warn: number, bad: number): Tone {
  if (percent >= bad) return "bad";
  if (percent >= warn) return "warn";
  return "ok";
}

function capacityTile(
  label: string,
  cap: Capacity,
  warn: number,
  bad: number,
  format: (n: number) => string,
) {
  const tone = toneFor(cap.percent, warn, bad);
  return (
    <Tile
      key={label}
      label={label}
      value={`${Math.round(cap.percent)}%`}
      hint={`${format(cap.used_bytes)} of ${format(cap.total_bytes)}`}
      fill={cap.percent}
      tone={tone}
    />
  );
}

export default function ServerVitals({ className }: { className?: string }) {
  const [data, setData] = useState<Vitals | null>(null);
  const [stale, setStale] = useState(false);
  const alive = useRef(true);

  const read = useCallback(() => {
    api
      .getVitals()
      .then((v) => {
        if (!alive.current) return;
        setData(v);
        setStale(false);
      })
      .catch(() => {
        // Keep the last good reading and mark it stale. Blanking the block would turn a
        // dropped request into "the server has no disk", which is a worse lie than an
        // old number that says it is old.
        if (alive.current) setStale(true);
      });
  }, []);

  useEffect(() => {
    alive.current = true;
    read();

    let timer: number | undefined;
    const start = () => {
      window.clearInterval(timer);
      timer = window.setInterval(read, POLL_MS);
    };
    const stop = () => window.clearInterval(timer);

    // Polling stops while the tab is hidden. This is not a micro-optimisation: a tab left
    // open in a background window would otherwise poll the VM roughly 8,600 times a day to
    // render a page nobody is looking at — load generated BY the monitoring, ON the
    // machine being monitored.
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        read(); // immediately, so the first thing seen on return is never stale
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive.current = false;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [read]);

  if (!data) return null; // nothing useful to say yet, and a skeleton here would be noise

  const tiles = [];
  if (data.disk) {
    tiles.push(
      capacityTile(
        "Disk",
        data.disk,
        data.disk_warn_percent,
        data.disk_warn_percent + 10,
        gb,
      ),
    );
  }
  if (data.memory) {
    tiles.push(
      capacityTile("Memory", data.memory, MEMORY_WARN, MEMORY_SERIOUS, mb),
    );
  }
  if (data.database_bytes !== null) {
    tiles.push(
      <Tile
        key="db"
        label="Database"
        value={mb(data.database_bytes)}
        hint="on disk"
      />,
    );
  }
  if (data.load_1m !== null) {
    tiles.push(
      <Tile
        key="load"
        label="Load"
        value={data.load_1m.toFixed(2)}
        hint="1-minute average"
      />,
    );
  }

  // "Never ticked" and "ticked a long time ago" are different answers, and only one of
  // them is a fault. A container thirty seconds into its first boot has not ticked yet and
  // is perfectly healthy, which is why uptime is read alongside it.
  const interval = data.tick_interval_seconds;
  const tickAge = data.last_tick
    ? (Date.now() - new Date(data.last_tick).getTime()) / 1000
    : null;
  const starting = data.last_tick === null && data.uptime_seconds < interval;
  const tickTone: Tone =
    starting || (tickAge !== null && tickAge < interval * 3)
      ? "ok"
      : tickAge === null || tickAge > interval * 6
        ? "bad"
        : "warn";
  tiles.push(
    <Tile
      key="tick"
      label="Scheduled work"
      value={
        data.last_tick
          ? since(data.last_tick)
          : starting
            ? "starting"
            : "not running"
      }
      hint={`checks every ${Math.round(interval / 60)} min · up ${uptime(data.uptime_seconds)}`}
      tone={tickTone}
    />,
  );

  return (
    <section
      aria-label="Server condition"
      className={cn(
        "rounded-xl border border-border bg-card p-3 sm:p-4",
        className,
      )}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 px-0.5">
        <span className="relative flex size-2">
          <span
            className={cn(
              "absolute inline-flex size-full rounded-full opacity-60",
              stale ? "bg-muted-foreground" : "animate-ping bg-primary",
            )}
          />
          <span
            className={cn(
              "relative inline-flex size-2 rounded-full",
              stale ? "bg-muted-foreground" : "bg-primary",
            )}
          />
        </span>
        <h2 className="text-sm font-medium">Server</h2>
        <span className="text-xs text-muted-foreground">
          {stale ? "reconnecting — showing the last reading" : "right now"}
        </span>
        {data.disk && data.disk.percent >= data.disk_warn_percent && (
          <span className="ml-auto flex items-center gap-1 text-xs text-destructive">
            <AlertTriangle className="size-3.5" />
            Disk is filling up
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">{tiles}</div>
    </section>
  );
}
