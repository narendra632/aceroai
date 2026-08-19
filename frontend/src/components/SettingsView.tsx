import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Info, Lock, Wallet } from "lucide-react";

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
import type { BudgetStatus, Settings, SettingsUpdate } from "@/lib/api";
import { formatINR, formatUSD } from "@/lib/format";
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

/* The spend limit.
 *
 * Kept as its own component with its own state because it saves independently of the
 * model pickers: raising a limit is something you do *while blocked*, and making that
 * share a Save button with an unrelated provider switch would be a trap.
 */
function SpendLimit({ budget, onSaved }: { budget: BudgetStatus; onSaved: (s: Settings) => void }) {
  const [value, setValue] = useState(budget.limit_usd ?? "");
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  const spent = Number(budget.spent_usd);
  const limit = budget.limit_usd == null ? null : Number(budget.limit_usd);
  const pct = Math.min(100, Math.round(budget.used_ratio * 100));
  const resets = new Date(`${budget.resets_on}T00:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
  });

  // One hue per state, so the bar says which state you are in without reading the text.
  const barColor =
    budget.state === "exceeded"
      ? "var(--destructive)"
      : budget.state === "warning"
        ? "#c98a2e"
        : "var(--series-1)";

  async function commit(patch: SettingsUpdate) {
    setSaving(true);
    try {
      onSaved(await api.updateSettings(patch));
      toast.success(patch.clear_budget ? "Spend limit turned off" : "Spend limit updated");
    } catch {
      toast.error("Could not save the spend limit");
    } finally {
      setSaving(false);
    }
  }

  const parsed = Number(value);
  const valid = value.trim() !== "" && Number.isFinite(parsed) && parsed > 0;
  const dirty = valid && String(parsed) !== String(limit ?? "");

  return (
    <section className="mt-4 rounded-xl border border-border p-4">
      <h2 className="mb-1 flex items-center gap-2 font-medium">
        <Wallet className="size-4 text-muted-foreground" /> Spend limit
        {budget.state === "exceeded" && (
          <span className="rounded-full bg-destructive/15 px-2 py-0.5 text-xs font-normal text-destructive">
            reached
          </span>
        )}
      </h2>
      <p className="text-sm text-muted-foreground">
        Pause replies once this month&rsquo;s estimated spend passes a ceiling you set.
      </p>

      <div className="mt-4">
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            <strong className="font-medium">{formatUSD(spent)}</strong>
            {limit != null && <span className="text-muted-foreground"> of {formatUSD(limit)}</span>}
            <span className="text-muted-foreground"> this month</span>
          </span>
          <span className="text-muted-foreground">
            {limit != null && `${pct}% · `}resets {resets}
          </span>
        </div>
        {limit != null && (
          <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full transition-[width] duration-500"
              style={{ width: `${Math.max(1.5, pct)}%`, background: barColor }}
            />
          </div>
        )}
      </div>

      {budget.state === "exceeded" && (
        <p className="mt-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          Replies are paused. Raise the limit below to carry on, or wait until {resets}.
        </p>
      )}
      {budget.state === "warning" && (
        <p className="mt-3 text-sm text-muted-foreground">
          You&rsquo;ve used {pct}% of this month&rsquo;s allowance.
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-muted-foreground">Monthly limit</span>
          <span className="flex items-center gap-1.5">
            <span className="text-muted-foreground">$</span>
            <input
              type="number"
              min="0.01"
              step="0.5"
              inputMode="decimal"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="no limit"
              className="w-28 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              style={{ fontVariantNumeric: "tabular-nums" }}
            />
          </span>
        </label>
        <Button
          onClick={() => commit({ monthly_budget_usd: String(parsed) })}
          disabled={saving || !dirty}
        >
          {saving ? "Saving…" : limit == null ? "Set limit" : "Update"}
        </Button>
        {limit != null && (
          <Button
            variant="ghost"
            onClick={() => {
              setValue("");
              commit({ clear_budget: true });
            }}
            disabled={saving}
          >
            Turn off
          </Button>
        )}
      </div>

      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
        Checked before each message, and it counts everything — replies, recalling what
        Acero knows, and learning from the turn afterwards. A reply already in progress
        finishes, so the total can pass the limit by one message. Spend is an{" "}
        <strong className="font-medium">estimate</strong>, not your provider&rsquo;s bill.
        {limit != null && ` About ${formatINR(limit)} at the rate on the Insights page.`}
      </p>
    </section>
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

          {/* A control that silently does nothing is worse than one that isn't offered.
              Some models have no reasoning setting at all, so choosing one here makes the
              think-harder toggle a no-op — which you would otherwise discover only by
              failing to notice any difference. */}
          {data.no_reasoning_control.includes(`${provider}/${deep}`) && (
            <p
              role="status"
              className="mt-3 flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground"
            >
              <Info className="mt-0.5 size-4 shrink-0" />
              <span>
                <strong className="font-medium text-foreground">{deep}</strong> has no
                reasoning setting, so the 🧠 toggle and <code>/think</code> will behave
                exactly like a normal reply. Pick a model that supports deeper thinking if
                you want that toggle to do something.
              </span>
            </p>
          )}

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

        <SpendLimit budget={data.budget} onSaved={apply} />

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
