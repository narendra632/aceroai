import type { Session } from "../lib/api";

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
  return (
    <>
      {/* backdrop on mobile when the drawer is open */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/30 md:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-line bg-surface-2 transition-transform duration-200 md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <span className="text-lg font-semibold tracking-tight">aceroai</span>
          <button
            onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-line md:hidden"
            aria-label="Close menu"
          >
            ✕
          </button>
        </div>

        <div className="px-3">
          <button
            onClick={onNewChat}
            className="min-h-11 w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-left text-sm font-medium text-ink transition hover:border-clay"
          >
            + New chat
          </button>
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
                    className={`w-full truncate rounded-lg px-3 py-2.5 text-left text-sm transition ${
                      s.id === currentId
                        ? "bg-clay/12 text-ink"
                        : "text-muted hover:bg-line/60"
                    }`}
                    title={s.title ?? "Untitled"}
                  >
                    {s.title ?? "Untitled"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <div className="border-t border-line px-4 py-3">
          <p className="truncate text-xs text-faint" title={email}>
            {email}
          </p>
          <button
            onClick={onLogout}
            className="mt-1 text-sm text-muted transition hover:text-clay-strong"
          >
            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}
