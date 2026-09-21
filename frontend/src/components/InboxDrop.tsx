import { useState } from "react";
import { Inbox, Loader2 } from "lucide-react";

import * as api from "@/lib/api";
import type { DropResult } from "@/lib/api";

/* Drop a link, a video, or something a friend said.
 *
 * ⚠ **One line, no ceremony, always visible.** Friction here kills the whole input channel:
 * an inbox that takes three taps to reach is an inbox nobody uses, and the ideas that would
 * have gone into it go nowhere instead.
 *
 * ⚠ **What you drop is recorded the way a channel's uploads are.** You become a measured
 * source, which is what eventually answers whether the tips you act on beat the exchange feed
 * you ignore.
 */

function looksLikeUrl(value: string) {
  return /^https?:\/\/\S+$/i.test(value.trim());
}

/* ⚠ A refusal is reported as plainly as a success. "Nothing was read" and "nobody was named"
   are different outcomes, and an inbox that blurred them would have its user dropping links
   into a void without ever knowing. */
function Outcome({ result, onClear }: { result: DropResult; onClear: () => void }) {
  const queued = result.discovered;
  const known = result.already_followed;

  return (
    <div className="mt-2 rounded-lg border border-border bg-muted/30 p-2.5 text-xs">
      {result.stored ? (
        <>
          <p className="font-medium">Filed: {result.title}</p>
          {queued.length > 0 && (
            <p className="mt-1 text-muted-foreground">
              Added to the research queue: <strong>{queued.join(", ")}</strong>
            </p>
          )}
          {known.length > 0 && (
            <p className="mt-1 text-muted-foreground">
              Filed against what you already follow: {known.join(", ")}
            </p>
          )}
          {queued.length === 0 && known.length === 0 && (
            <p className="mt-1 text-muted-foreground">
              No listed company was named in it — kept anyway, so the record of what you
              read stays complete.
            </p>
          )}
          {result.trust_tier === 1 && (
            <p className="mt-1 text-muted-foreground">
              Treated as a filing, because it came from an exchange or a regulator.
            </p>
          )}
        </>
      ) : (
        <p className="text-muted-foreground">
          Not filed — {result.note}
          {result.named.length > 0 && (
            <span className="mt-1 block">It named: {result.named.join(", ")}</span>
          )}
        </p>
      )}
      <button
        type="button"
        onClick={onClear}
        className="mt-1.5 text-muted-foreground underline underline-offset-2 hover:text-foreground"
      >
        dismiss
      </button>
    </div>
  );
}

export default function InboxDrop({ onFiled }: { onFiled?: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DropResult | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const submit = async () => {
    const raw = value.trim();
    if (!raw || busy) return;
    setBusy(true);
    setFailed(null);
    try {
      // ⚠ A bare URL is a link; anything else is a note. Both are valid, and a link with a
      // line of your own about why it matters reads better than the page alone.
      const out = await api.dropIntoInbox(
        looksLikeUrl(raw) ? { url: raw } : { text: raw },
      );
      setResult(out);
      setValue("");
      if (out.stored) onFiled?.();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "that could not be read");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
        <Inbox className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
          }}
          disabled={busy}
          aria-label="Drop a link, a video, or something you heard"
          placeholder="Drop a link, a video, or something you heard…"
          className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || value.trim().length === 0}
          className="flex shrink-0 items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
        >
          {busy && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}
          {busy ? "reading" : "Read it"}
        </button>
      </div>

      {failed && <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">{failed}</p>}
      {result && <Outcome result={result} onClear={() => setResult(null)} />}
    </section>
  );
}
