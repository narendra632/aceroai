import { useCallback, useEffect, useRef, useState } from "react";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSmoothReveal } from "@/hooks/useSmoothReveal";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { Session } from "@/lib/api";
import Composer, { type ComposerHandle } from "./Composer";
import JournalView from "./JournalView";
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

  const reveal = useSmoothReveal();
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<ComposerHandle>(null);

  const refreshSessions = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => toast.error("Couldn't refresh your chats"));
  }, [toast]);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

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

      const finalize = (content: string) => {
        if (content) {
          setMessages((prev) => [
            ...prev,
            {
              id: newId(),
              role: "assistant",
              content,
              created_at: new Date().toISOString(),
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
    [busy, currentId, reveal, refreshSessions],
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
            <Composer
              ref={composerRef}
              text={draft}
              onTextChange={setDraft}
              deep={deep}
              onDeepChange={setDeep}
              onSend={(t, d) => void send(t, d)}
              onStop={stop}
              busy={busy}
            />
          </>
        ) : view === "tasks" ? (
          <TasksView />
        ) : view === "journal" ? (
          <JournalView />
        ) : (
          <SettingsView />
        )}
      </div>
    </div>
  );
}
