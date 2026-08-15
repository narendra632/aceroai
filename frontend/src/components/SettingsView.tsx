import { useEffect, useState } from "react";
import { Check, Lock } from "lucide-react";

import { Button } from "@/components/ui/button";
import * as api from "@/lib/api";
import type { Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

const PROVIDER_LABEL: Record<string, string> = { google: "Google (Gemini)", openai: "OpenAI" };

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
  return (
    <div>
      <label className="text-sm font-medium">{label}</label>
      <p className="mt-0.5 mb-2 text-xs text-muted-foreground">{hint}</p>
      <select
        value={known ? value : "__custom__"}
        onChange={(e) => onChange(e.target.value === "__custom__" ? "" : e.target.value)}
        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
      >
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
        <option value="__custom__">Other…</option>
      </select>
      {!known && (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="exact model id"
          className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
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
  const [error, setError] = useState<string | null>(null);

  function apply(s: Settings) {
    setData(s);
    setProvider(s.provider);
    setChat(s.model_chat);
    setDeep(s.model_deep);
  }

  useEffect(() => {
    api.getSettings().then(apply).catch(() => setError("Could not load settings."));
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      apply(await api.updateSettings({ provider, model_chat: chat, model_deep: deep }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  }

  if (!data) {
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-6 text-sm text-muted-foreground">
          {error ?? "Loading…"}
        </div>
      </div>
    );
  }

  const models = data.model_catalog[provider] ?? [];
  const dirty =
    provider !== data.provider || chat !== data.model_chat || deep !== data.model_deep;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <h1 className="mb-1 hidden text-xl font-semibold tracking-tight md:block">Settings</h1>
        <p className="mb-5 text-sm text-muted-foreground">
          Choose which AI answers you. This applies everywhere — web and Telegram.
        </p>

        <section className="rounded-xl border border-border bg-card p-4">
          <h2 className="mb-3 font-medium">Provider</h2>
          <div className="flex flex-wrap gap-2">
            {data.available_providers.map((p) => (
              <button
                key={p}
                onClick={() => {
                  setProvider(p);
                  // jump to that provider's defaults so the models always match
                  const next = data.model_catalog[p] ?? [];
                  setChat(next[0] ?? "");
                  setDeep(next[0] ?? "");
                }}
                className={cn(
                  "rounded-lg border px-3 py-2 text-sm transition",
                  p === provider
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border hover:bg-accent",
                )}
              >
                {PROVIDER_LABEL[p] ?? p}
              </button>
            ))}
          </div>
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
            {error && <span className="text-sm text-destructive">{error}</span>}
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
      </div>
    </div>
  );
}
