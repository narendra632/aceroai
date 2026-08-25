/* The notification centre: what Acero has said, whether or not it reached a device.
 *
 * This is the reason notifications are stored before they are delivered. A push you swiped
 * off a lockscreen is gone; the row behind it is not, and it is here. Everything Acero has
 * raised — including what quiet hours suppressed and what a denied permission never allowed
 * — is readable in one place.
 *
 * The panel is a Popover on wide screens and a Sheet on narrow ones, chosen by MEASURED
 * width rather than a CSS class. Radix portals its content to `document.body`, so a
 * `lg:hidden` on a wrapper never reaches it and both would render at once — a bug this
 * project has already shipped once and fixed the same way.
 *
 * ⚠ Two things this file got wrong for a whole release, both fixed here, because the
 * component was hand-rolled instead of going through `useOptimisticList` like every other
 * list in the app — and so re-implemented none of the invariants that hook enforces:
 *
 *   1. An empty array was rendered as "Nothing yet." REGARDLESS of whether anything had
 *      been loaded. Opening the bell stated confidently that there were no notifications,
 *      then contradicted itself when the fetch landed.
 *   2. `.catch(() => {})` meant a FAILED load rendered identically. A dead backend and an
 *      empty inbox were indistinguishable.
 *
 * `ui-standards` has forbidden exactly this since the UI-polish change: "an error is never
 * rendered as an empty result, which would misreport a fault as 'you have nothing'".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BellOff, Check, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { NotificationRow } from "@/lib/api";
import { cn } from "@/lib/utils";

/** How often the unread count is refreshed while the app is open. One indexed count with
 *  no rows serialised, so this is cheap — but not so cheap it should be a second. */
const POLL_MS = 60_000;

type Status = "loading" | "ready" | "error";

function relative(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
}

function PanelSkeleton() {
  return (
    <div className="space-y-3 px-3 py-3" role="status" aria-label="Loading notifications">
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="space-y-1.5">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3 w-full" />
        </div>
      ))}
    </div>
  );
}

/** One row.
 *
 * ⚠ A container with two sibling buttons, NOT one button. The row used to be a single
 * `<button>`, and a button may not contain another button — nesting them is invalid HTML
 * and browsers resolve it by discarding the inner one. The dismiss control therefore could
 * not simply be added inside the existing element. */
function Row({
  n,
  onOpen,
  onDismiss,
}: {
  n: NotificationRow;
  onOpen: (n: NotificationRow) => void;
  onDismiss: (n: NotificationRow) => void;
}) {
  return (
    <li
      className={cn(
        "group relative flex items-start transition-colors hover:bg-secondary",
        !n.read_at && "bg-secondary/50",
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(n)}
        className="flex min-w-0 flex-1 flex-col gap-0.5 py-2.5 pl-3 pr-1 text-left focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/50"
      >
        <span className="flex items-center gap-2">
          {!n.read_at && (
            <span
              className="size-1.5 shrink-0 rounded-full bg-primary"
              aria-label="Unread"
            />
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-medium">
            {n.title}
          </span>
          <span className="shrink-0 text-[11px] text-muted-foreground">
            {relative(n.created_at)}
          </span>
        </span>
        <span className={cn("line-clamp-2 text-xs text-muted-foreground", !n.read_at && "pl-3.5")}>
          {n.body}
        </span>
      </button>
      {/* Always rendered, never revealed on hover: the device this app is installed on is
          a phone, where there is no hover and a hidden control simply does not exist. */}
      <button
        type="button"
        onClick={() => onDismiss(n)}
        aria-label={`Dismiss: ${n.title}`}
        className="mr-1 mt-2 shrink-0 rounded-md p-1.5 text-muted-foreground/60 transition-colors hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 group-hover:text-muted-foreground"
      >
        <X className="size-3.5" />
      </button>
    </li>
  );
}

/** `showHeader` is false inside a Sheet, which renders its own title and close button.
 *  Rendering both produces two stacked headers — a bug this project shipped once already
 *  when the same panel was reused in both containers. */
function NotificationList({
  items,
  status,
  onOpen,
  onDismiss,
  onMarkAll,
  onClearRead,
  onRetry,
  showHeader,
}: {
  items: NotificationRow[];
  status: Status;
  onOpen: (n: NotificationRow) => void;
  onDismiss: (n: NotificationRow) => void;
  onMarkAll: () => void;
  onClearRead: () => void;
  onRetry: () => void;
  showHeader: boolean;
}) {
  const unread = items.filter((n) => !n.read_at).length;
  const read = items.length - unread;

  // The skeleton appears only when there is nothing to show. On re-open the rows already
  // held stay visible while a fresh copy loads underneath — which REMOVES the flash rather
  // than replacing it with a spinner, and is the whole point of tracking status separately
  // from the array.
  const showSkeleton = status === "loading" && items.length === 0;
  const showError = status === "error" && items.length === 0;

  const header = showHeader ? (
    <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
      <span className="text-sm font-medium">Notifications</span>
      <Actions unread={unread} read={read} onMarkAll={onMarkAll} onClearRead={onClearRead} />
    </div>
  ) : (
    <div className="mb-1 flex items-center gap-3 px-3">
      <Actions unread={unread} read={read} onMarkAll={onMarkAll} onClearRead={onClearRead} />
    </div>
  );

  return (
    <>
      {header}
      {showSkeleton ? (
        <PanelSkeleton />
      ) : showError ? (
        <div className="px-3 py-6">
          <ErrorState
            title="Couldn't load your notifications"
            detail="This is a connection problem, not an empty inbox."
            onRetry={onRetry}
          />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
          <BellOff className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Nothing yet.</p>
          <p className="max-w-[24ch] text-xs text-muted-foreground">
            Acero will tell you when a task falls overdue or a briefing is ready.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-border overflow-y-auto lg:max-h-[min(60vh,28rem)]">
          {items.map((n) => (
            <Row key={n.id} n={n} onOpen={onOpen} onDismiss={onDismiss} />
          ))}
        </ul>
      )}
    </>
  );
}

/** Each action appears only when it would do something. A "Clear read" that clears nothing
 *  teaches the user their tap did not register. */
function Actions({
  unread,
  read,
  onMarkAll,
  onClearRead,
}: {
  unread: number;
  read: number;
  onMarkAll: () => void;
  onClearRead: () => void;
}) {
  return (
    <span className="flex items-center gap-3">
      {unread > 0 && (
        <button
          type="button"
          onClick={onMarkAll}
          className="flex items-center gap-1 rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Check className="size-3" />
          Mark all read
        </button>
      )}
      {read > 0 && (
        <button
          type="button"
          onClick={onClearRead}
          className="flex items-center gap-1 rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <Trash2 className="size-3" />
          Clear read
        </button>
      )}
    </span>
  );
}

export default function NotificationBell({
  onNavigate,
}: {
  onNavigate: (url: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationRow[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [unread, setUnread] = useState(0);
  const wide = useMediaQuery("(min-width: 1024px)");
  const toast = useToast();

  // Guards against a slow earlier load overwriting a newer one's result.
  const loadId = useRef(0);

  const refreshCount = useCallback(() => {
    api
      .unreadCount()
      .then(setUnread)
      .catch(() => {});
  }, []);

  const load = useCallback(() => {
    const id = ++loadId.current;
    setStatus("loading");
    api
      .listNotifications()
      .then(({ items: rows, unread: count }) => {
        if (id !== loadId.current) return;
        setItems(rows);
        setUnread(count);
        setStatus("ready");
      })
      .catch(() => {
        if (id !== loadId.current) return;
        // Deliberately does NOT clear `items`: a failed refresh must not destroy rows the
        // user can still read. And it must not look like an empty inbox.
        setStatus("error");
      });
  }, []);

  useEffect(() => {
    refreshCount();
    const timer = window.setInterval(refreshCount, POLL_MS);
    // Coming back to a backgrounded tab is the moment the count is most likely stale,
    // and the cheapest possible trigger for a refresh.
    const onVisible = () =>
      document.visibilityState === "visible" && refreshCount();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshCount]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const handleOpen = useCallback(
    (n: NotificationRow) => {
      setOpen(false);
      if (!n.read_at) {
        setItems((rows) =>
          rows.map((r) =>
            r.id === n.id ? { ...r, read_at: new Date().toISOString() } : r,
          ),
        );
        setUnread((c) => Math.max(0, c - 1));
        api.markNotificationRead(n.id).catch(() => {});
      }
      if (n.url) onNavigate(n.url);
    },
    [onNavigate],
  );

  const handleMarkAll = useCallback(() => {
    const now = new Date().toISOString();
    setItems((rows) => rows.map((r) => ({ ...r, read_at: r.read_at ?? now })));
    setUnread(0);
    api.markAllNotificationsRead().catch(() => {});
  }, []);

  /* Optimistic with a real rollback, and an undo — the idiom `useOptimisticList` and
     `TasksView.remove` established. An optimistic update without a revert path shows state
     the server rejected, which is strictly worse than waiting. */
  const handleDismiss = useCallback(
    (n: NotificationRow) => {
      const snapshot = items;
      const wasUnread = !n.read_at;
      setItems((rows) => rows.filter((r) => r.id !== n.id));
      if (wasUnread) setUnread((c) => Math.max(0, c - 1));
      api
        .deleteNotification(n.id)
        .then(() => {
          toast.undo("Notification removed", async () => {
            await api.restoreNotification(n.id);
            load();
            refreshCount();
          });
        })
        .catch(() => {
          setItems(snapshot);
          if (wasUnread) setUnread((c) => c + 1);
          toast.error("Could not remove that notification");
        });
    },
    [items, toast, load, refreshCount],
  );

  const handleClearRead = useCallback(() => {
    const snapshot = items;
    setItems((rows) => rows.filter((r) => !r.read_at));
    api
      .clearReadNotifications()
      .then((ids) => {
        if (ids.length === 0) return;
        // Undo restores exactly the ids that were removed — not "everything read", which
        // would also resurrect anything marked read since.
        toast.undo(`${ids.length} removed`, async () => {
          await api.restoreNotifications(ids);
          load();
          refreshCount();
        });
      })
      .catch(() => {
        setItems(snapshot);
        toast.error("Could not clear those notifications");
      });
  }, [items, toast, load, refreshCount]);

  const panel = (showHeader: boolean) => (
    <NotificationList
      items={items}
      status={status}
      onOpen={handleOpen}
      onDismiss={handleDismiss}
      onMarkAll={handleMarkAll}
      onClearRead={handleClearRead}
      onRetry={load}
      showHeader={showHeader}
    />
  );

  const trigger = (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={
        unread > 0 ? `Notifications, ${unread} unread` : "Notifications"
      }
      className="relative"
    >
      <Bell />
      {unread > 0 && (
        <span
          className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-4 text-primary-foreground"
          aria-hidden
        >
          {unread > 9 ? "9+" : unread}
        </span>
      )}
    </Button>
  );

  // Rendered CONDITIONALLY, not hidden with a class. Radix portals its content to
  // `document.body`, so a `lg:hidden` on a wrapper never reaches it and both panels would
  // open at once — exactly the bug this project shipped and fixed on the Learn section.
  if (wide) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent align="end" className="w-[22rem] p-0">
          {panel(true)}
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent title="Notifications" className="px-0">
        {panel(false)}
      </SheetContent>
    </Sheet>
  );
}
