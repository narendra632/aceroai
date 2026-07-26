import { useEffect, useRef } from "react";

import Markdown from "./Markdown";
import MessageBubble, { type UIMessage } from "./MessageBubble";
import ThinkingDots from "./ThinkingDots";

type StreamState = { thinking: boolean; text: string } | null;

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
}: {
  messages: UIMessage[];
  streaming: StreamState;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streaming]);

  if (messages.length === 0 && !streaming) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">How can I help?</h2>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          Ask me anything, think out loud, or jot down what's on your mind.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-5 px-4 py-6">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}

        {streaming && (
          <div className="rise flex gap-3">
            <AssistantAvatar />
            <div className="min-w-0 flex-1 pt-0.5">
              {streaming.thinking ? (
                <ThinkingDots />
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
  );
}
