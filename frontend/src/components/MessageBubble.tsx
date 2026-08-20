import { useEffect, useRef, useState } from "react";
import { Brain, Check, Copy, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { RecalledFact } from "@/lib/api";
import { cn } from "@/lib/utils";
import Markdown from "./Markdown";

export type UIMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  error?: boolean;
  /** The facts recall injected for this reply. Absent when nothing was recalled — which
   *  after hybrid recall is a real, common state (a coding question recalls nothing). */
  recalled?: RecalledFact[];
};

/** What each search contributed, in words rather than jargon. */
const VIA_LABEL: Record<RecalledFact["via"], string> = {
  both: "meaning + wording",
  vector: "meaning",
  lexical: "wording",
};

function timeLabel(iso?: string): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear on unmount — otherwise this sets state on a component that is gone.
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
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
          aria-label={label}
          className={cn(
            "text-muted-foreground transition",
            // hover-reveal on desktop, always reachable on touch — a hover-only
            // control simply does not exist on a phone
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            "max-md:opacity-60",
          )}
        >
          {copied ? <Check className="text-primary" /> : <Copy />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied" : label}</TooltipContent>
    </Tooltip>
  );
}

function RecalledFacts({ facts }: { facts: RecalledFact[] }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Show the ${facts.length} memories used`}
          className="text-muted-foreground opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-60"
        >
          <Brain />
        </Button>
      </PopoverTrigger>
      {/* Click, not hover: hover does not exist on a phone, and this has to work at 375px. */}
      <PopoverContent>
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {facts.length === 1 ? "1 memory used" : `${facts.length} memories used`}
        </p>
        <ul className="max-h-72 space-y-2 overflow-y-auto">
          {facts.map((f) => (
            <li key={f.id} className="text-sm leading-snug">
              {f.fact}
              <span className="mt-0.5 block text-[11px] text-faint">
                {f.category} · found by {VIA_LABEL[f.via]}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

export default function MessageBubble({
  message,
  onRegenerate,
  onRetry,
}: {
  message: UIMessage;
  /** Present only on the last assistant message. */
  onRegenerate?: () => void;
  /** Present only on an error bubble. */
  onRetry?: () => void;
}) {
  const time = timeLabel(message.created_at);

  if (message.role === "user") {
    return (
      <div className="group flex flex-col items-end gap-1">
        <div className="rise max-w-[85%] rounded-2xl rounded-br-md bg-accent px-4 py-2.5 whitespace-pre-wrap text-accent-foreground">
          {message.content}
        </div>
        <div className="flex items-center gap-1">
          {time && <span className="text-[11px] text-faint">{time}</span>}
          <CopyButton text={message.content} label="Copy message" />
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
          <div className="rounded-xl border border-destructive/40 bg-destructive/5 px-3 py-2.5">
            <p className="text-sm text-destructive">{message.content}</p>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry} className="mt-2">
                <RefreshCw className="size-3.5" /> Try again
              </Button>
            )}
          </div>
        ) : (
          <Markdown content={message.content} />
        )}
        {!message.error && (
          <div className="mt-1 -ml-2 flex items-center gap-1">
            <CopyButton text={message.content} label="Copy reply" />
            {/* Absent, not present-and-empty. A button that opens onto "nothing" is noise
                on exactly the turns that need no explanation. */}
            {message.recalled && message.recalled.length > 0 && (
              <RecalledFacts facts={message.recalled} />
            )}
            {onRegenerate && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={onRegenerate}
                    aria-label="Regenerate reply"
                    className="text-muted-foreground opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-60"
                  >
                    <RefreshCw />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Regenerate</TooltipContent>
              </Tooltip>
            )}
            {time && <span className="ml-1 text-[11px] text-faint">{time}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
