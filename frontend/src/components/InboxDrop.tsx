import { useState } from "react";
import { AlertTriangle, CheckCircle2, Inbox, Loader2, X } from "lucide-react";

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
   into a void without ever knowing.

   ⚠ One line, not a card. The first version rendered a full card that stayed pinned above
   every tab until dismissed, so a filed link pushed the whole page down on Holdings, Records
   and everywhere else. Where it went is a link away; what it said is the line. */
function Outcome({
  result,
  onClear,
  onSee,
}: {
  result: DropResult;
  onClear: () => void;
  onSee?: () => void;
}) {
  const queued = result.discovered;
  const known = result.already_followed;

  let line: React.ReactNode;
  let tone = "text-muted-foreground";
  if (!result.stored) {
    tone = "text-caution";
    line = (
      <>
        Not filed — {result.note}
        {result.named.length > 0 && <> It named {result.named.join(", ")}.</>}
      </>
    );
  } else if (queued.length > 0) {
    line = (
      <>
        Filed. <strong className="text-foreground">{queued.join(", ")}</strong> added to Worth a
        look
        {known.length > 0 && <>; also filed against {known.join(", ")}</>}.
      </>
    );
  } else if (known.length > 0) {
    line = <>Filed against what you already follow: {known.join(", ")}.</>;
  } else {
    line = <>Filed. No listed company was named in it — kept anyway, so the record stays whole.</>;
  }

  return (
    <div className="mt-2 flex items-start gap-2 px-1 text-xs" role="status">
      {result.stored ? (
        <CheckCircle2 className="mt-px size-3.5 shrink-0 text-good" aria-hidden="true" />
      ) : (
        <AlertTriangle className="mt-px size-3.5 shrink-0 text-caution" aria-hidden="true" />
      )}
      <p className={`min-w-0 flex-1 ${tone}`} title={result.title}>
        {line}
        {result.trust_tier === 1 && result.stored && " Treated as a filing."}
      </p>
      {result.stored && queued.length > 0 && onSee && (
        <button
          type="button"
          onClick={onSee}
          className="shrink-0 font-medium text-primary underline-offset-2 hover:underline"
        >
          See it
        </button>
      )}
      <button
        type="button"
        onClick={onClear}
        aria-label="Dismiss"
        className="touch-target shrink-0 rounded text-muted-foreground hover:text-foreground"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

export default function InboxDrop({
  onFiled,
  onSee,
}: {
  onFiled?: () => void;
  onSee?: () => void;
}) {
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

      {failed && <p className="mt-2 px-1 text-xs text-bad">{failed}</p>}
      {result && (
        <Outcome result={result} onClear={() => setResult(null)} onSee={onSee} />
      )}
    </section>
  );
}
