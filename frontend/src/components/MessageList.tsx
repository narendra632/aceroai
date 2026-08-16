import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";

import { ListSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/utils";
import Markdown from "./Markdown";
import MessageBubble, { type UIMessage } from "./MessageBubble";
import ThinkingDots from "./ThinkingDots";

type StreamState = { thinking: boolean; text: string; label?: string } | null;

const SUGGESTIONS = [
  "What's on my plate today?",
  "Log how today went",
  "Remind me to call the bank tomorrow",
  "What do you know about me?",
];

/** Treat "within this many pixels of the bottom" as the user following along. */
const STICK_PX = 120;

function AssistantAvatar() {
  return (
    <div className="mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
      A
    </div>
  );
}

export default function MessageList({
  messages,
  streaming,
  loading,
  onSuggestion,
  onRegenerate,
  onRetry,
}: {
  messages: UIMessage[];
  streaming: StreamState;
  loading?: boolean;
  onSuggestion?: (text: string) => void;
  onRegenerate?: () => void;
  onRetry?: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  const checkPosition = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(distance <= STICK_PX);
  }, []);

  // Follow the stream ONLY while the user is already near the bottom. Scrolling up to
  // re-read something used to yank you back down on every token, which made a long
  // reply impossible to read while it arrived.
  useEffect(() => {
    if (atBottom) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming, atBottom]);

  const jumpToBottom = () => {
    setAtBottom(true);
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-6">
          <ListSkeleton rows={3} />
        </div>
      </div>
    );
  }

  if (messages.length === 0 && !streaming) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">How can I help?</h2>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          Ask me anything, think out loud, or jot down what's on your mind.
        </p>
        {onSuggestion && (
          <div className="mt-6 flex max-w-md flex-wrap justify-center gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => onSuggestion(s)}
                className="rounded-full border border-border bg-card px-3.5 py-2 text-sm text-muted-foreground transition-colors hover:border-input hover:text-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant" && !m.error);
  const lastError = messages[messages.length - 1]?.error ? messages[messages.length - 1] : null;

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={scrollRef} onScroll={checkPosition} className="h-full overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-5 px-4 py-6">
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              onRegenerate={
                onRegenerate && !streaming && m.id === lastAssistant?.id ? onRegenerate : undefined
              }
              onRetry={onRetry && m.id === lastError?.id ? onRetry : undefined}
            />
          ))}

          {streaming && (
            <div className="rise flex gap-3">
              <AssistantAvatar />
              <div className="min-w-0 flex-1 pt-0.5">
                {streaming.thinking ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <ThinkingDots />
                    {streaming.label && <span>{streaming.label}</span>}
                  </div>
                ) : (
                  <div className="streaming">
                    <Markdown content={streaming.text} />
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={endRef} />
        </div>
      </div>

      {!atBottom && (
        <button
          onClick={jumpToBottom}
          aria-label="Jump to latest"
          className={cn(
            "absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-border",
            "bg-card p-2.5 shadow-lg transition-colors hover:bg-accent",
          )}
        >
          <ArrowDown className="size-4" />
        </button>
      )}
    </div>
  );
}
