import { useEffect, useRef, useState } from "react";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useSmoothReveal } from "@/hooks/useSmoothReveal";
import * as api from "@/lib/api";
import type { Session } from "@/lib/api";
import Composer from "./Composer";
import MessageList from "./MessageList";
import type { UIMessage } from "./MessageBubble";
import Sidebar from "./Sidebar";

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
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const reveal = useSmoothReveal();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions);
  }, []);

  async function openSession(id: string) {
    setSidebarOpen(false);
    setCurrentId(id);
    const msgs = await api.getMessages(id);
    setMessages(msgs.map((m) => ({ role: m.role as UIMessage["role"], content: m.content })));
  }

  function newChat() {
    setSidebarOpen(false);
    setCurrentId(null);
    setMessages([]);
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function send(text: string, deep = false) {
    if (busy) return;
    setBusy(true);
    setThinking(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    reveal.begin();

    const controller = new AbortController();
    abortRef.current = controller;
    let gotFirst = false;

    const finalize = (content: string) => {
      if (content) setMessages((prev) => [...prev, { role: "assistant", content }]);
      setThinking(false);
      setBusy(false);
      abortRef.current = null;
    };

    try {
      for await (const ev of api.streamChat(text, currentId, controller.signal, deep)) {
        if (ev.event === "session") {
          setCurrentId(ev.data);
        } else if (ev.event === "delta") {
          if (!gotFirst) {
            gotFirst = true;
            setThinking(false);
          }
          reveal.push(ev.data);
        } else if (ev.event === "done") {
          reveal.finish(finalize);
          api.listSessions().then(setSessions);
          return;
        } else if (ev.event === "error") {
          reveal.cancel();
          setMessages((prev) => [...prev, { role: "assistant", content: `⚠ ${ev.data}`, error: true }]);
          setThinking(false);
          setBusy(false);
          abortRef.current = null;
          return;
        }
      }
      // stream ended without an explicit done (e.g., aborted): keep partial text
      finalize(reveal.cancel());
      api.listSessions().then(setSessions);
    } catch {
      // aborted by the user, or network error — keep whatever was revealed
      finalize(reveal.cancel());
      api.listSessions().then(setSessions);
    }
  }

  const streaming = busy ? { thinking, text: reveal.text } : null;

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
        <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 md:hidden">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Menu />
          </Button>
          <span className="font-semibold tracking-tight">aceroai</span>
        </header>

        <MessageList messages={messages} streaming={streaming} />
        <Composer onSend={send} onStop={stop} busy={busy} />
      </div>
    </div>
  );
}
