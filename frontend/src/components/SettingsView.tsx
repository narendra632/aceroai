import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Lock } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ErrorState } from "@/components/ui/states";
import { useToast } from "@/hooks/useToast";
import * as api from "@/lib/api";
import type { Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

const PROVIDER_LABEL: Record<string, string> = { google: "Google (Gemini)", openai: "OpenAI" };
const CUSTOM = "__custom__";

/** A model picker that also accepts a model we don't list yet, so a newly released
 *  model is usable before the catalog is updated. */
function ModelField({
  label,
  hint,
  value,
  options,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  const known = options.includes(value);
  // Remember that the user chose "custom" even while the box is briefly empty,
  // so the field doesn't snap back to the dropdown mid-typing.
  const [custom, setCustom] = useState(!known && value !== "");
  const showCustom = custom || (!known && value !== "");

  return (
    <div>
      <span className="text-sm font-medium">{label}</span>
      <p className="mt-0.5 mb-2 text-xs text-muted-foreground">{hint}</p>
      <Select
        value={showCustom ? CUSTOM : value}
        onValueChange={(v) => {
          if (v === CUSTOM) {
            setCustom(true);
          } else {
            setCustom(false);
            onChange(v);
          }
        }}
      >
        <SelectTrigger className="w-full" aria-label={label}>
          <SelectValue placeholder="Choose a model" />
        </SelectTrigger>
        <SelectContent>
          {options.map((m) => (
            <SelectItem key={m} value={m}>
              {m}
            </SelectItem>
          ))}
          <SelectSeparator />
          <SelectItem value={CUSTOM}>Another model…</SelectItem>
        </SelectContent>
      </Select>
      {showCustom && (
        <input
          value={known ? "" : value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="exact model id, e.g. gemini-3.9-flash"
          aria-label={`${label} — custom model id`}
          className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30"
        />
      )}
    </div>
  );
}

export default function SettingsView() {
  const [data, setData] = useState<Settings | null>(null);
  const [provider, setProvider] = useState("");
  const [chat, setChat] = useState("");
  const [deep, setDeep] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [switchNote, setSwitchNote] = useState<string | null>(null);

  // Remembers each provider's models, so switching away and back doesn't silently
  // throw your choices away.
  const remembered = useRef<Record<string, { chat: string; deep: string }>>({});
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toast = useToast();

  useEffect(() => () => { if (savedTimer.current) clearTimeout(savedTimer.current); }, []);

  const apply = useCallback((s: Settings) => {
    setData(s);
    setProvider(s.provider);
    setChat(s.model_chat);
    setDeep(s.model_deep);
    remembered.current[s.provider] = { chat: s.model_chat, deep: s.model_deep };
  }, []);

  const load = useCallback(() => {
    setLoadError(false);
    api
      .getSettings()
      .then(apply)
      .catch(() => setLoadError(true));
  }, [apply]);

  useEffect(load, [load]);

  function pickProvider(p: string) {
    if (p === provider || !data) return;
    remembered.current[provider] = { chat, deep };
    const catalog = data.model_catalog[p] ?? [];
    const prior = remembered.current[p];
    if (prior) {
      setChat(prior.chat);
      setDeep(prior.deep);
      setSwitchNote(null);
    } else {
      setChat(catalog[0] ?? "");
      setDeep(catalog[0] ?? "");
      // Say it out loud rather than silently replacing what the user picked.
      setSwitchNote(
        `Models set to ${PROVIDER_LABEL[p] ?? p} defaults — ${catalog[0] ?? "none available"}.`,
      );
    }
    setProvider(p);
  }

  async function save() {
    setSaving(true);
    try {
      apply(await api.updateSettings({ provider, model_chat: chat, model_deep: deep }));
      setSwitchNote(null);
      setSaved(true);
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-6">
          <ErrorState
            title="Couldn't load settings"
            detail="Your saved provider and models are unchanged."
            onRetry={load}
          />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-6 text-sm text-muted-foreground">
          Loading…
        </div>
      </div>
    );
  }

  const models = data.model_catalog[provider] ?? [];
  const dirty = provider !== data.provider || chat !== data.model_chat || deep !== data.model_deep;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-1 hidden text-xl font-semibold tracking-tight md:block">Settings</h1>
        <p className="mb-5 text-sm text-muted-foreground">
          Choose which AI answers you. This applies everywhere — web and Telegram.
        </p>

        {/* What is ACTUALLY answering right now — saved state, not the pending picker. */}
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-3">
          <span className="relative flex size-2.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-60" />
            <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
          </span>
          <span className="text-sm">
            Answering with <strong>{PROVIDER_LABEL[data.provider] ?? data.provider}</strong>
            <span className="text-muted-foreground"> · </span>
            <span className="font-mono text-xs">{data.model_chat}</span>
          </span>
          {dirty && (
            <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground">
              unsaved changes — press Save to switch
            </span>
          )}
        </div>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 font-medium">Provider</h2>
          <div className="flex flex-wrap gap-2">
            {data.available_providers.map((p) => {
              const picked = p === provider;
              const live = p === data.provider;
              return (
                <button
                  key={p}
                  onClick={() => pickProvider(p)}
                  className={cn(
                    "flex min-h-11 items-center gap-2 rounded-lg border px-3 py-2 text-sm transition",
                    picked
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border hover:bg-accent",
                  )}
                >
                  {picked && <Check className="size-4" />}
                  {PROVIDER_LABEL[p] ?? p}
                  {live && (
                    <span
                      className={cn(
                        "rounded-full px-1.5 py-0.5 text-[10px] tracking-wide uppercase",
                        picked ? "bg-primary-foreground/20" : "bg-accent text-accent-foreground",
                      )}
                    >
                      active
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {switchNote && <p className="mt-3 text-xs text-muted-foreground">{switchNote}</p>}

          {data.available_providers.length < 2 && (
            <p className="mt-3 text-xs text-faint">
              Only providers with credentials configured on the server are shown. Add another
              provider's key to the server's environment to enable it here.
            </p>
          )}

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <ModelField
              label="Chat model"
              hint="Everyday replies — fast."
              value={chat}
              options={models}
              onChange={setChat}
            />
            <ModelField
              label="Think-harder model"
              hint="Used with the 🧠 toggle and /think."
              value={deep}
              options={models}
              onChange={setDeep}
            />
          </div>

          <div className="mt-5 flex items-center gap-3">
            <Button onClick={save} disabled={saving || !dirty}>
              {saving ? "Saving…" : "Save"}
            </Button>
            {saved && (
              <span className="flex items-center gap-1 text-sm text-muted-foreground">
                <Check className="size-4" /> Saved
              </span>
            )}
          </div>
        </section>

        {/* Pinned on purpose — changing this would invalidate stored memory. */}
        <section className="mt-4 rounded-xl border border-border bg-secondary/50 p-4">
          <h2 className="mb-1 flex items-center gap-2 font-medium">
            <Lock className="size-4 text-muted-foreground" /> Memory model
            <span className="rounded-full bg-accent px-2 py-0.5 text-xs font-normal text-accent-foreground">
              fixed
            </span>
          </h2>
          <p className="text-sm">
            <span className="font-mono text-xs">{data.embedding.model}</span>{" "}
            <span className="text-muted-foreground">
              · {data.embedding.dimensions} dimensions · {data.embedding.provider}
            </span>
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {data.embedding.note}
          </p>
        </section>

        <section className="mt-4 rounded-xl border border-border p-4">
          <h2 className="mb-2 font-medium">Keyboard shortcuts</h2>
          <dl className="grid gap-1.5 text-sm sm:grid-cols-2">
            {[
              ["Ctrl / ⌘ + K", "New chat"],
              ["/", "Jump to the message box"],
              ["Enter", "Send · Shift+Enter for a new line"],
              ["Esc", "Close the menu or a panel"],
            ].map(([key, what]) => (
              <div key={key} className="flex items-center gap-2">
                <kbd className="rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-xs">
                  {key}
                </kbd>
                <dd className="text-muted-foreground">{what}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
