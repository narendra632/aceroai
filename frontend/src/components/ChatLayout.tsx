import { useEffect, useState } from "react";

import * as api from "../lib/api";
import type { Session } from "../lib/api";
import Composer from "./Composer";
import MessageList from "./MessageList";
import type { UIMessage } from "./MessageBubble";
import Sidebar from "./Sidebar";

// immutable helpers that update the trailing (assistant) message
function patchLast(list: UIMessage[], patch: Partial<UIMessage>): UIMessage[] {
  const next = list.slice();
  const i = next.length - 1;
  next[i] = { ...next[i], ...patch };
  return next;
}

export default function ChatLayout({
  email,
  onLogout,
}: {
  email: string;
  onLogout: () => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    api.listSessions().then(setSessions);
  }, []);

  async function openSession(id: string) {
    setSidebarOpen(false);
    setCurrentId(id);
    const msgs = await api.getMessages(id);
    setMessages(
      msgs.map((m) => ({ role: m.role as UIMessage["role"], content: m.content })),
    );
  }

  function newChat() {
    setSidebarOpen(false);
    setCurrentId(null);
    setMessages([]);
  }

  async function send(text: string) {
    if (busy) return;
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "", streaming: true },
    ]);
    try {
      for await (const ev of api.streamChat(text, currentId)) {
        if (ev.event === "session") {
          setCurrentId(ev.data);
        } else if (ev.event === "delta") {
          setMessages((prev) => patchLast(prev, { content: prev[prev.length - 1].content + ev.data }));
        } else if (ev.event === "done") {
          setMessages((prev) => patchLast(prev, { streaming: false }));
        } else if (ev.event === "error") {
          setMessages((prev) =>
            patchLast(prev, { streaming: false, error: true, content: `⚠ ${ev.data}` }),
          );
        }
      }
      setSessions(await api.listSessions());
    } catch {
      setMessages((prev) =>
        patchLast(prev, { streaming: false, error: true, content: "⚠ Something went wrong." }),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full">
      <Sidebar
        email={email}
        sessions={sessions}
        currentId={currentId}
        open={sidebarOpen}
        onSelect={openSession}
        onNewChat={newChat}
        onClose={() => setSidebarOpen(false)}
        onLogout={onLogout}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line px-4 py-3 md:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="grid h-9 w-9 place-items-center rounded-lg text-muted hover:bg-line"
            aria-label="Open menu"
          >
            ☰
          </button>
          <span className="font-semibold tracking-tight">aceroai</span>
        </header>

        <MessageList messages={messages} />
        <Composer onSend={send} busy={busy} />
      </div>
    </div>
  );
}
