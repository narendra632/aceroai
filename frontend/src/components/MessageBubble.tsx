export type UIMessage = {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  error?: boolean;
};

export default function MessageBubble({ message }: { message: UIMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end rise">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-user px-4 py-2.5 text-ink">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 rise">
      <div className="mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-full bg-clay text-xs font-semibold text-white">
        A
      </div>
      <div
        className={`min-w-0 whitespace-pre-wrap pt-0.5 ${
          message.error ? "text-clay-strong" : "text-ink"
        } ${message.streaming && !message.content ? "caret" : ""}`}
      >
        {message.content}
        {message.streaming && message.content && <span className="caret" />}
      </div>
    </div>
  );
}
