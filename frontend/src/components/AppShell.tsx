import { useCallback, useEffect, useRef, useState } from "react";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSmoothReveal } from "@/hooks/useSmoothReveal";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { BudgetStatus, RecalledFact, Session } from "@/lib/api";
import Composer, { type ComposerHandle } from "./Composer";
import JournalView from "./JournalView";
import InsightsView from "./InsightsView";
import KnowledgeView from "./KnowledgeView";
import LearnView from "./LearnView";
import MessageList from "./MessageList";
import type { UIMessage } from "./MessageBubble";
import SettingsView from "./SettingsView";
import Sidebar, { type View } from "./Sidebar";
import TasksView from "./TasksView";

const newId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;

export default function AppShell({ email, onLogout }: { email: string; onLogout: () => void }) {
  const [view, setView] = useState<View>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Chat state lives here (not in a child) so switching to Tasks/Journal and back
  // never loses the open conversation, an in-flight stream, OR a half-written message.
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [deep, setDeep] = useState(false);
  // The spend ceiling. Re-read after every turn so the number in the warning band is the
  // real one, not the one from whenever the app was opened.
  const [budget, setBudget] = useState<BudgetStatus | null>(null);

  const reveal = useSmoothReveal();
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<ComposerHandle>(null);

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => toast.error("Couldn't refresh your chats"));
  }, [toast]);

  // Best-effort: a failure here must never block chat, so it stays silent and the
  // composer simply behaves as it did before the limit existed.
  const refreshBudget = useCallback(() => {
    api.getBudget().then(setBudget).catch(() => {});
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Re-read on every arrival at the chat screen, not just on mount. Raising the limit
  // happens in Settings, so without this the composer would stay locked after the user
  // had already fixed it — and the one thing a blocked state must get right is letting
  // you out of it.
  useEffect(() => {
    if (view === "chat") refreshBudget();
  }, [view, refreshBudget]);

  function navigate(v: View) {
    setView(v);
    setSidebarOpen(false);
  }

  async function openSession(id: string) {
    setSidebarOpen(false);
    setView("chat");
    setCurrentId(id);
    setLoadingHistory(true);
    try {
      const msgs = await api.getMessages(id);
      setMessages(
        msgs.map((m) => ({
          id: m.id,
          role: m.role as UIMessage["role"],
          content: m.content,
          created_at: m.created_at,
        })),
      );
    } catch {
      toast.error("Couldn't open that conversation");
    } finally {
      setLoadingHistory(false);
    }
  }

  function deleteSession(session: Session) {
    void (async () => {
      const previous = sessions;
      setSessions((prev) => prev.filter((s) => s.id !== session.id));
      const wasOpen = session.id === currentId;
      if (wasOpen) {
        setCurrentId(null);
        setMessages([]);
      }
      try {
        await api.deleteSession(session.id);
        toast.undo("Conversation deleted", async () => {
          try {
            await api.restoreSession(session.id);
            refreshSessions();
            if (wasOpen) await openSession(session.id);
          } catch {
            toast.error("Could not restore the conversation");
          }
        });
      } catch {
        setSessions(previous); // put it back exactly as it was
        toast.error("Could not delete the conversation");
      }
    })();
  }

  function renameSession(id: string, title: string) {
    void (async () => {
      const previous = sessions;
      setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
      try {
        await api.renameSession(id, title);
      } catch {
        setSessions(previous);
        toast.error("Could not rename the conversation");
      }
    })();
  }

  const newChat = useCallback(() => {
    setSidebarOpen(false);
    setView("chat");
    setCurrentId(null);
    setMessages([]);
    setTimeout(() => composerRef.current?.focus(), 0);
  }, []);

  function stop() {
    abortRef.current?.abort();
  }

  const send = useCallback(
    async (text: string, useDeep = false) => {
      if (busy) return;
      setBusy(true);
      setThinking(true);
      setWorking(null);
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "user", content: text, created_at: new Date().toISOString() },
      ]);
      reveal.begin();

      const controller = new AbortController();
      abortRef.current = controller;

      // Arrives before the first token, so it is held here and attached to the assistant
      // bubble when the reply is finalized. What is shown is exactly what was sent to the
      // model — a display that can drift from what was used is worse than no display.
      let recalled: RecalledFact[] = [];

      const finalize = (content: string) => {
        if (content) {
          setMessages((prev) => [
            ...prev,
            {
              id: newId(),
              role: "assistant",
              content,
              created_at: new Date().toISOString(),
              recalled: recalled.length ? recalled : undefined,
            },
          ]);
        }
        setThinking(false);
        setWorking(null);
        setBusy(false);
        abortRef.current = null;
      };

      try {
        for await (const ev of api.streamChat(text, currentId, controller.signal, useDeep)) {
          if (ev.event === "session") {
            setCurrentId(ev.data);
          } else if (ev.event === "recall") {
            try {
              recalled = JSON.parse(ev.data) as RecalledFact[];
            } catch {
              recalled = []; // a malformed frame must never break the reply
            }
          } else if (ev.event === "tool") {
            setThinking(true);
            setWorking("Working…");
          } else if (ev.event === "delta") {
            setThinking(false);
            setWorking(null);
            reveal.push(ev.data);
          } else if (ev.event === "done") {
            reveal.finish(finalize);
            refreshSessions();
            refreshBudget();
            return;
          } else if (ev.event === "error") {
            reveal.cancel();
            setMessages((prev) => [
              ...prev,
              { id: newId(), role: "assistant", content: `⚠ ${ev.data}`, error: true },
            ]);
            setThinking(false);
            setWorking(null);
            setBusy(false);
            abortRef.current = null;
            refreshBudget();
            return;
          }
        }
        finalize(reveal.cancel()); // ended without "done" (e.g. aborted): keep partial text
        refreshSessions();
      } catch {
        finalize(reveal.cancel());
        refreshSessions();
      }
    },
    [busy, currentId, reveal, refreshSessions, refreshBudget],
  );

  /** Re-run the last turn: drop the trailing reply server-side, then resend. */
  function regenerate() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || busy) return;
    void (async () => {
      try {
        if (currentId) await api.regenerate(currentId);
        setMessages((prev) => {
          const idx = prev.map((m) => m.role).lastIndexOf("assistant");
          return idx === -1 ? prev : prev.filter((_, i) => i !== idx);
        });
        // the resend appends its own user bubble, so drop the old one first
        setMessages((prev) => prev.filter((m) => m.id !== lastUser.id));
        await send(lastUser.content, deep);
      } catch {
        toast.error("Could not regenerate that reply");
      }
    })();
  }

  /** Retry after an error bubble: remove it and send the same message again. */
  function retry() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser || busy) return;
    setMessages((prev) => prev.filter((m) => !m.error && m.id !== lastUser.id));
    void send(lastUser.content, deep);
  }

  // Keyboard shortcuts. `/` only steals focus when the user isn't already typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      const typing =
        !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        newChat();
      } else if (e.key === "/" && !typing) {
        e.preventDefault();
        setView("chat");
        composerRef.current?.focus();
      } else if (e.key === "Escape" && sidebarOpen) {
        setSidebarOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, sidebarOpen]);

  const streaming = busy ? { thinking, text: reveal.text, label: working ?? undefined } : null;
  const TITLES: Record<View, string> = {
    chat: "aceroai",
    tasks: "Tasks",
    journal: "Journal",
    knowledge: "Knowledge",
    insights: "Insights",
    learn: "Learn",
    settings: "Settings",
  };

  return (
    <div className="flex h-full">
      <Sidebar
        email={email}
        view={view}
        sessions={sessions}
        currentId={currentId}
        open={sidebarOpen}
        onNavigate={navigate}
        onSelect={openSession}
        onDelete={deleteSession}
        onRename={renameSession}
        onNewChat={newChat}
        onClose={() => setSidebarOpen(false)}
        onLogout={onLogout}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 md:hidden">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Menu />
          </Button>
          <span className="font-semibold tracking-tight">{TITLES[view]}</span>
        </header>

        {view === "chat" ? (
          <>
            <MessageList
              messages={messages}
              streaming={streaming}
              loading={loadingHistory}
              onSuggestion={(text) => void send(text, deep)}
              onRegenerate={regenerate}
              onRetry={retry}
            />
            {budget?.state === "warning" && (
              <div className="border-t border-border bg-background px-4 pt-3">
                <p className="mx-auto flex w-full max-w-2xl items-center justify-between gap-3 rounded-lg bg-secondary px-3 py-2 text-xs text-muted-foreground">
                  <span>
                    {Math.round(budget.used_ratio * 100)}% of this month&rsquo;s spend limit
                    used.
                  </span>
                  <button
                    type="button"
                    onClick={() => navigate("settings")}
                    className="shrink-0 font-medium text-foreground underline-offset-2 hover:underline"
                  >
                    Adjust
                  </button>
                </p>
              </div>
            )}
            <Composer
              ref={composerRef}
              text={draft}
              onTextChange={setDraft}
              deep={deep}
              onDeepChange={setDeep}
              onSend={(t, d) => void send(t, d)}
              onStop={stop}
              busy={busy}
              blocked={
                budget?.state === "exceeded"
                  ? {
                      reason: `Monthly spend limit reached. Replies resume on ${new Date(
                        `${budget.resets_on}T00:00:00`,
                      ).toLocaleDateString(undefined, { day: "numeric", month: "long" })}.`,
                      onResolve: () => navigate("settings"),
                    }
                  : undefined
              }
            />
          </>
        ) : view === "tasks" ? (
          <TasksView />
        ) : view === "journal" ? (
          <JournalView />
        ) : view === "insights" ? (
          <InsightsView />
        ) : view === "knowledge" ? (
          // `openSession` is exactly what a fact's provenance link needs: switch to chat
          // and load the conversation the belief came from.
          <KnowledgeView onOpenSession={(id) => void openSession(id)} />
        ) : view === "learn" ? (
          // Holds no state worth preserving — it describes the system rather than the
          // user — so unlike chat it needs none of the care above.
          <LearnView />
        ) : (
          <SettingsView />
        )}
      </div>
    </div>
  );
}
