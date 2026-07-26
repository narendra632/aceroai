import { LogOut, Moon, Plus, Sun, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";
import type { Session } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  email: string;
  sessions: Session[];
  currentId: string | null;
  open: boolean;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onClose: () => void;
  onLogout: () => void;
};

export default function Sidebar({
  email,
  sessions,
  currentId,
  open,
  onSelect,
  onNewChat,
  onClose,
  onLogout,
}: Props) {
  const { theme, toggle } = useTheme();

  return (
    <>
      {open && (
        <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={onClose} aria-hidden />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-border bg-secondary transition-transform duration-200 md:static md:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <span className="text-lg font-semibold tracking-tight">aceroai</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close menu"
              className="md:hidden"
            >
              <X />
            </Button>
          </div>
        </div>

        <div className="px-3">
          <Button variant="outline" onClick={onNewChat} className="w-full justify-start gap-2">
            <Plus /> New chat
          </Button>
        </div>

        <nav className="mt-3 flex-1 overflow-y-auto px-3 pb-3">
          {sessions.length === 0 ? (
            <p className="px-2 py-4 text-sm text-faint">No conversations yet.</p>
          ) : (
            <ul className="space-y-1">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    onClick={() => onSelect(s.id)}
                    title={s.title ?? "Untitled"}
                    className={cn(
                      "w-full truncate rounded-lg px-3 py-2.5 text-left text-sm transition",
                      s.id === currentId
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/60",
                    )}
                  >
                    {s.title ?? "Untitled"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <span className="truncate text-xs text-faint" title={email}>
            {email}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onLogout}
            aria-label="Sign out"
            className="text-muted-foreground"
          >
            <LogOut />
          </Button>
        </div>
      </aside>
    </>
  );
}
