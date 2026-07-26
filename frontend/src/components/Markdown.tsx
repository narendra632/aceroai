import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Safe markdown for assistant messages. react-markdown does not render raw HTML
// (no rehype-raw), so model output cannot inject scripts.
export default function Markdown({ content }: { content: string }) {
  return (
    <div className="space-y-3 leading-relaxed break-words text-[0.95rem]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (props) => <p {...props} />,
          ul: (props) => <ul className="list-disc space-y-1 pl-5" {...props} />,
          ol: (props) => <ol className="list-decimal space-y-1 pl-5" {...props} />,
          li: (props) => <li className="marker:text-muted-foreground" {...props} />,
          a: (props) => (
            <a
              className="text-primary underline underline-offset-2 hover:opacity-80"
              target="_blank"
              rel="noreferrer"
              {...props}
            />
          ),
          strong: (props) => <strong className="font-semibold" {...props} />,
          h1: (props) => <h1 className="text-lg font-semibold" {...props} />,
          h2: (props) => <h2 className="text-base font-semibold" {...props} />,
          h3: (props) => <h3 className="text-base font-semibold" {...props} />,
          blockquote: (props) => (
            <blockquote className="border-l-2 border-border pl-3 text-muted-foreground" {...props} />
          ),
          hr: () => <hr className="border-border" />,
          pre: (props) => (
            <pre
              className="overflow-x-auto rounded-lg border border-border bg-secondary p-3 text-sm"
              {...props}
            />
          ),
          code: ({ className, ...props }: ComponentPropsWithoutRef<"code">) =>
            className?.includes("language-") ? (
              <code className={className} {...props} />
            ) : (
              <code
                className="rounded bg-secondary px-1.5 py-0.5 text-[0.85em] font-medium"
                {...props}
              />
            ),
          table: (props) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm" {...props} />
            </div>
          ),
          th: (props) => (
            <th className="border border-border px-2 py-1 text-left font-semibold" {...props} />
          ),
          td: (props) => <td className="border border-border px-2 py-1" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
