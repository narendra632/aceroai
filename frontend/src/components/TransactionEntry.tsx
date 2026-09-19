import { useEffect, useState } from "react";
import { AlertTriangle, Plus, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import DatePicker from "@/components/ui/date-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ListSkeleton } from "@/components/ui/states";
import * as api from "@/lib/api";
import type { Draft, DraftInput, InvestmentTransaction } from "@/lib/api";
import { formatDay, formatPrice, formatQuantity, formatRupees } from "@/lib/format";
import { useToast } from "@/hooks/useToast";

/* Recording a transaction, and reading what has been recorded.
 *
 * Two rules shape this whole file:
 *
 *   1. **Nothing is written in one step.** The form asks the server to cost the entry and
 *      shows what came back — charges, net rupees, every warning — and only then offers to
 *      record it. The confirm sends the same raw inputs again rather than the costed draft,
 *      so a charge figure can never originate on this side of the wire.
 *
 *   2. **Nothing is ever deleted.** The ledger is append-only, so the correction action
 *      records an entry that supersedes the original, and says so in those words. Calling
 *      it "delete · undo" would tell the user something false about the one record in this
 *      system whose worth depends on being unrewritable.
 */

const ACTIONS = [
  { value: "BUY", label: "Bought" },
  { value: "SELL", label: "Sold" },
  { value: "SIP", label: "SIP instalment" },
  { value: "DIVIDEND", label: "Dividend" },
  { value: "BONUS", label: "Bonus shares" },
  { value: "SPLIT", label: "Split" },
];

const CURRENCIES = [
  { value: "INR", label: "₹ INR" },
  { value: "USD", label: "$ USD" },
];

/* An instrument the book has never seen needs three more facts before it can be recorded:
 * where it trades, what kind of thing it is, and what it is called. They are asked for only
 * when the server says the symbol is new — putting them on the form permanently would make
 * every ordinary entry look like a data-entry chore, and the common case is a holding that
 * already exists. */
const ASSET_CLASSES = [
  { value: "EQUITY_IN", label: "Indian equity", exchange: "NSE", currency: "INR" },
  { value: "MF_IN", label: "Mutual fund", exchange: "MF_IN", currency: "INR" },
  { value: "EQUITY_US", label: "US equity", exchange: "NASDAQ", currency: "USD" },
  { value: "CRYPTO", label: "Crypto", exchange: "CRYPTO", currency: "INR" },
];

const EXCHANGES = ["NSE", "BSE", "NASDAQ", "NYSE", "AMEX", "CRYPTO", "MF_IN"];

/** The server's wording when a symbol is not in the book yet. Matched rather than guessed
 *  from a status code, because only this particular rejection is answerable by showing more
 *  fields — every other one means the entry itself is wrong. */
const IS_NEW = "is new, so it needs";

/* A half-typed transaction survives leaving the page.
 *
 * The view unmounts when you switch to Chat, so its state would otherwise be gone — and
 * losing a partly-entered trade because you looked something up is exactly the behaviour
 * the interface standard forbids. Session storage rather than local: this is an unfinished
 * sentence, not a preference, and it should not still be waiting next week.
 *
 * ⚠ Every access is wrapped. Private windows and blocked site data make `sessionStorage`
 * throw on read as well as write, and a form that cannot render is worse than one that
 * forgets. */
const DRAFT_KEY = "aceroai_txn_draft";

type Kept = {
  symbol: string;
  action: string;
  quantity: string;
  price: string;
  when: string;
  currency: string;
  fxRate: string;
  isNew: boolean;
  assetClass: string;
  exchange: string;
  name: string;
};

function readKept(): Kept | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    return raw ? (JSON.parse(raw) as Kept) : null;
  } catch {
    return null;
  }
}

function writeKept(value: Kept | null) {
  try {
    if (value) sessionStorage.setItem(DRAFT_KEY, JSON.stringify(value));
    else sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    // Nothing to do and nothing to say: the form still works, it just will not be
    // remembered across a view switch.
  }
}

function todayLocal(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T09:00`;
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

const inputClass =
  "mt-1.5 w-full rounded-lg border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/30";

type Props = {
  transactions: InvestmentTransaction[];
  loading: boolean;
  onChanged: () => void;
};

export default function TransactionEntry({ transactions, loading, onChanged }: Props) {
  const toast = useToast();
  const kept = readKept();
  const [open, setOpen] = useState(kept != null);
  const [symbol, setSymbol] = useState(kept?.symbol ?? "");
  const [action, setAction] = useState(kept?.action ?? "BUY");
  const [quantity, setQuantity] = useState(kept?.quantity ?? "");
  const [price, setPrice] = useState(kept?.price ?? "");
  const [when, setWhen] = useState(kept?.when ?? todayLocal);
  const [currency, setCurrency] = useState(kept?.currency ?? "INR");
  const [fxRate, setFxRate] = useState(kept?.fxRate ?? "");
  const [isNew, setIsNew] = useState(kept?.isNew ?? false);
  const [assetClass, setAssetClass] = useState(kept?.assetClass ?? "EQUITY_IN");
  const [exchange, setExchange] = useState(kept?.exchange ?? "NSE");
  const [name, setName] = useState(kept?.name ?? "");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // Kept only while the form is open and has something in it. An empty form is not a
  // draft, and restoring one would reopen the panel every visit for no reason.
  useEffect(() => {
    const anything = symbol || quantity || price || fxRate || name;
    writeKept(
      open && anything
        ? {
            symbol,
            action,
            quantity,
            price,
            when,
            currency,
            fxRate,
            isNew,
            assetClass,
            exchange,
            name,
          }
        : null,
    );
  }, [
    open,
    symbol,
    action,
    quantity,
    price,
    when,
    currency,
    fxRate,
    isNew,
    assetClass,
    exchange,
    name,
  ]);

  function inputs(): DraftInput {
    return {
      symbol: symbol.trim().toUpperCase(),
      txn_type: action,
      quantity: quantity.trim(),
      price: price.trim(),
      trade_date: when.slice(0, 10),
      currency,
      fx_rate_inr: currency === "INR" ? null : fxRate.trim() || null,
      // Sent only once the server has said the symbol is unknown. For an instrument the
      // book already holds, the ledger's own record of what it is always wins.
      ...(isNew
        ? { asset_class: assetClass, exchange, name: name.trim() || null }
        : {}),
    };
  }

  function reset() {
    setDraft(null);
    setProblem(null);
    setSymbol("");
    setQuantity("");
    setPrice("");
    setFxRate("");
    setIsNew(false);
    setName("");
    setOpen(false);
    writeKept(null);
  }

  async function cost() {
    setBusy(true);
    setProblem(null);
    try {
      setDraft(await api.draftTransaction(inputs()));
    } catch (e) {
      setDraft(null);
      const message = e instanceof Error ? e.message : "that entry could not be costed";
      if (message.includes(IS_NEW)) {
        // Not an error the user did anything wrong to cause — it is the form discovering
        // it needs more from them. Say that, rather than showing a rejection.
        setIsNew(true);
        setProblem(null);
      } else {
        setProblem(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      const written = await api.recordTransaction(inputs());
      toast.success(`Recorded ${written.txn_type.toLowerCase()} ${written.symbol}`);
      reset();
      onChanged();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "that entry could not be recorded");
    } finally {
      setBusy(false);
    }
  }

  async function reverse(t: InvestmentTransaction) {
    try {
      await api.reverseTransaction(t.id);
      // ⚠ Not "Deleted · Undo". Nothing was deleted, and this record's whole value is that
      // it cannot be. The wording is the feature.
      toast.success("Reversed. The original entry stays in the record.");
      onChanged();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "that entry could not be reversed");
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">Transactions</h2>
        <Button
          variant={open ? "ghost" : "outline"}
          size="sm"
          onClick={() => (open ? reset() : setOpen(true))}
        >
          {open ? "Cancel" : <><Plus className="size-4" /> Record one</>}
        </Button>
      </div>

      {open && (
        <div className="space-y-4 rounded-xl border border-border bg-card p-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Instrument" htmlFor="txn-symbol" hint="Ticker or fund symbol">
              <input
                id="txn-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                placeholder="HDFCBANK"
                className={inputClass}
                autoComplete="off"
              />
            </Field>

            <Field label="Action">
              <Select value={action} onValueChange={setAction}>
                <SelectTrigger className="mt-1.5 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ACTIONS.map((a) => (
                    <SelectItem key={a.value} value={a.value}>
                      {a.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field label="Quantity" htmlFor="txn-qty" hint="Units, at full precision">
              <input
                id="txn-qty"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                inputMode="decimal"
                placeholder="4"
                className={inputClass}
              />
            </Field>

            <Field label="Price per unit" htmlFor="txn-price">
              <input
                id="txn-price"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                inputMode="decimal"
                placeholder="722.65"
                className={inputClass}
              />
            </Field>

            <Field label="Trade date">
              <DatePicker value={when} onChange={setWhen} className="mt-1.5" />
            </Field>

            <Field label="Currency">
              <Select value={currency} onValueChange={setCurrency}>
                <SelectTrigger className="mt-1.5 w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CURRENCIES.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            {currency !== "INR" && (
              <Field
                label="Rate to INR"
                htmlFor="txn-fx"
                hint="The rate you actually got, markup included — not a published mid."
              >
                <input
                  id="txn-fx"
                  value={fxRate}
                  onChange={(e) => setFxRate(e.target.value)}
                  inputMode="decimal"
                  placeholder="96.01"
                  className={inputClass}
                />
              </Field>
            )}
          </div>

          {isNew && (
            <div className="space-y-4 rounded-lg border border-border bg-background p-3">
              <p className="text-sm">
                <strong>{symbol.trim().toUpperCase()}</strong> is not in the book yet. Tell it
                what this is, and recording the transaction will start tracking it — there is
                no separate watchlist to keep in step.
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Kind">
                  <Select
                    value={assetClass}
                    onValueChange={(v) => {
                      setAssetClass(v);
                      const preset = ASSET_CLASSES.find((a) => a.value === v);
                      if (preset) {
                        setExchange(preset.exchange);
                        setCurrency(preset.currency);
                      }
                    }}
                  >
                    <SelectTrigger className="mt-1.5 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ASSET_CLASSES.map((a) => (
                        <SelectItem key={a.value} value={a.value}>
                          {a.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field label="Where it trades">
                  <Select value={exchange} onValueChange={setExchange}>
                    <SelectTrigger className="mt-1.5 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EXCHANGES.map((x) => (
                        <SelectItem key={x} value={x}>
                          {x}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field
                  label="Full name"
                  htmlFor="txn-name"
                  hint="Optional — the symbol is used if you leave it blank."
                >
                  <input
                    id="txn-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="HDFC Bank"
                    className={inputClass}
                  />
                </Field>
              </div>
            </div>
          )}

          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}

          {draft ? (
            <div className="space-y-3 rounded-lg border border-border bg-background p-3">
              <p className="text-sm">
                <strong>
                  {draft.txn_type.toLowerCase()} {formatQuantity(draft.quantity)} {draft.symbol}
                </strong>{" "}
                at {formatPrice(draft.price, draft.currency)} on{" "}
                {formatDay(draft.trade_date)}
              </p>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Charges</dt>
                <dd className="text-right tabular-nums">{formatRupees(draft.charges_inr)}</dd>
                {Number(draft.prepaid_tax_inr) !== 0 && (
                  <>
                    <dt className="text-muted-foreground">Tax withheld</dt>
                    <dd className="text-right tabular-nums">
                      {formatRupees(draft.prepaid_tax_inr)}
                    </dd>
                  </>
                )}
                <dt className="font-medium">Total</dt>
                <dd className="text-right font-medium tabular-nums">
                  {formatRupees(draft.net_inr)}
                </dd>
              </dl>

              {draft.creates_instrument && (
                <p className="text-xs text-muted-foreground">
                  New to the book — recording it also starts tracking it.
                </p>
              )}
              {draft.warnings.map((w) => (
                <p key={w} className="flex gap-2 text-xs text-amber-700 dark:text-amber-400">
                  <AlertTriangle className="size-3.5 shrink-0" />
                  {w}
                </p>
              ))}

              <div className="flex gap-2">
                <Button onClick={confirm} disabled={busy}>
                  {busy ? "Recording…" : "Record it"}
                </Button>
                <Button variant="ghost" onClick={() => setDraft(null)} disabled={busy}>
                  Change something
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Once recorded this cannot be edited — a mistake is corrected by a reversing
                entry, and both stay in the record.
              </p>
            </div>
          ) : (
            <Button onClick={cost} disabled={busy || !symbol.trim() || !quantity || !price}>
              {busy ? "Checking…" : "Check it"}
            </Button>
          )}
        </div>
      )}

      {loading ? (
        <ListSkeleton rows={3} />
      ) : transactions.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border">
          {transactions.map((t) => {
            const dead = t.superseded_by_id != null;
            return (
              <li
                key={t.id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2.5 text-sm"
              >
                <span className={dead ? "text-muted-foreground line-through" : "font-medium"}>
                  {t.txn_type.toLowerCase()} {formatQuantity(t.quantity)} {t.symbol}
                </span>
                <span className={`text-muted-foreground ${dead ? "line-through" : ""}`}>
                  @ {formatPrice(t.price, t.currency)}
                </span>
                <span className="ml-auto tabular-nums text-muted-foreground">
                  {formatDay(t.trade_date)}
                </span>
                {dead ? (
                  <span className="w-full text-xs text-muted-foreground">
                    Superseded by a later correction. Kept so the record still shows what was
                    entered at the time.
                  </span>
                ) : t.supersedes_id ? (
                  <span className="w-full text-xs text-muted-foreground">
                    A correction{t.note ? ` — ${t.note}` : ""}.
                  </span>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => reverse(t)}
                    aria-label={`Reverse ${t.txn_type.toLowerCase()} ${t.symbol}`}
                  >
                    <RotateCcw className="size-3.5" /> Reverse
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
