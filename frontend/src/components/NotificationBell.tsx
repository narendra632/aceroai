/* The notification centre: what Acero has said, whether or not it reached a device.
 *
 * This is the reason notifications are stored before they are delivered. A push you swiped
 * off a lockscreen is gone; the row behind it is not, and it is here. Everything Acero has
 * raised — including what quiet hours suppressed, what the daily cap dropped, and what a
 * denied permission never allowed — is readable in one place.
 *
 * The panel is a Popover on wide screens and a Sheet on narrow ones, chosen by MEASURED
 * width rather than a CSS class. Radix portals its content to `document.body`, so a
 * `lg:hidden` on a wrapper never reaches it and both would render at once — a bug this
 * project has already shipped once and fixed the same way.
 */

import { useCallback, useEffect, useState } from "react";
import { Bell, BellOff, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import * as api from "@/lib/api";
import type { NotificationRow } from "@/lib/api";
import { cn } from "@/lib/utils";

/** How often the unread count is refreshed while the app is open. One indexed count with
 *  no rows serialised, so this is cheap — but not so cheap it should be a second. */
const POLL_MS = 60_000;

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

/** `showHeader` is false inside a Sheet, which renders its own title and close button.
 *  Rendering both produces two stacked headers — a bug this project shipped once already
 *  when the same panel was reused in both containers. */
function NotificationList({
  items,
  onOpen,
  onMarkAll,
  showHeader,
}: {
  items: NotificationRow[];
  onOpen: (n: NotificationRow) => void;
  onMarkAll: () => void;
  showHeader: boolean;
}) {
  const unread = items.filter((n) => !n.read_at).length;

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
        <BellOff className="size-5 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Nothing yet.</p>
        <p className="max-w-[24ch] text-xs text-muted-foreground">
          Acero will tell you when a task falls overdue or a briefing is ready.
        </p>
      </div>
    );
  }

  return (
    <>
      {showHeader ? (
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-sm font-medium">Notifications</span>
          {unread > 0 && (
            <button
              type="button"
              onClick={onMarkAll}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <Check className="size-3" />
              Mark all read
            </button>
          )}
        </div>
      ) : (
        unread > 0 && (
          <button
            type="button"
            onClick={onMarkAll}
            className="mb-1 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <Check className="size-3" />
            Mark all read
          </button>
        )
      )}
      <ul className="divide-y divide-border overflow-y-auto lg:max-h-[min(60vh,28rem)]">
        {items.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              onClick={() => onOpen(n)}
              className={cn(
                "flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-secondary",
                !n.read_at && "bg-secondary/50",
              )}
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
              <span className="line-clamp-2 pl-3.5 text-xs text-muted-foreground">
                {n.body}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function NotificationBell({
  onNavigate,
}: {
  onNavigate: (url: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationRow[]>([]);
  const [unread, setUnread] = useState(0);
  const wide = useMediaQuery("(min-width: 1024px)");

  const refreshCount = useCallback(() => {
    api
      .unreadCount()
      .then(setUnread)
      .catch(() => {});
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
    if (!open) return;
    api
      .listNotifications()
      .then(({ items: rows, unread: count }) => {
        setItems(rows);
        setUnread(count);
      })
      .catch(() => {});
  }, [open]);

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
          <NotificationList
            items={items}
            onOpen={handleOpen}
            onMarkAll={handleMarkAll}
            showHeader
          />
        </PopoverContent>
      </Popover>
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>{trigger}</SheetTrigger>
      <SheetContent title="Notifications" className="px-0">
        <NotificationList
          items={items}
          onOpen={handleOpen}
          onMarkAll={handleMarkAll}
          showHeader={false}
        />
      </SheetContent>
    </Sheet>
  );
}
