import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import Markdown from "./Markdown";

export type UIMessage = {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={copy}
          aria-label="Copy message"
          className="text-muted-foreground opacity-0 transition group-hover:opacity-100"
        >
          {copied ? <Check className="text-primary" /> : <Copy />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied" : "Copy"}</TooltipContent>
    </Tooltip>
  );
}

export default function MessageBubble({ message }: { message: UIMessage }) {
  if (message.role === "user") {
    return (
      <div className="rise flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-4 py-2.5 whitespace-pre-wrap text-accent-foreground">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="rise group flex gap-3">
      <div className="mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
        A
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        {message.error ? (
          <p className="text-destructive">{message.content}</p>
        ) : (
          <Markdown content={message.content} />
        )}
        <div className="mt-1 -ml-2">
          <CopyButton text={message.content} />
        </div>
      </div>
    </div>
  );
}
