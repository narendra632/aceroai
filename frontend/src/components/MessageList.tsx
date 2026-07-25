import { useEffect, useRef } from "react";

import MessageBubble, { type UIMessage } from "./MessageBubble";

export default function MessageList({ messages }: { messages: UIMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <h2 className="text-2xl font-semibold tracking-tight">How can I help?</h2>
        <p className="mt-2 max-w-sm text-sm text-muted">
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
        <div ref={endRef} />
      </div>
    </div>
  );
}
