import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, Gauge, ListChecks, Radio, ScrollText, Wallet } from "lucide-react";

import BenchmarksPanel from "@/components/BenchmarksPanel";
import BooksPanel from "@/components/BooksPanel";
import ForeignHoldings from "@/components/ForeignHoldings";
import FrameworkPanel from "@/components/FrameworkPanel";
import InboxDrop from "@/components/InboxDrop";
import HoldingsTab from "@/components/investments/HoldingsTab";
import { severityTone } from "@/components/investments/attention";
import { RANGES, type RangeKey, type SortKey } from "@/components/investments/holdings";
import { Count } from "@/components/investments/kit";
import MeasuresPanel from "@/components/investments/MeasuresPanel";
import NeedsYou from "@/components/investments/NeedsYou";
import PositionSheet from "@/components/PositionSheet";
import ProposalsPanel from "@/components/ProposalsPanel";
import ReadingPanel from "@/components/ReadingPanel";
import ResearchPanel from "@/components/ResearchPanel";
import ReviewsPanel from "@/components/ReviewsPanel";
import ThemesStrip from "@/components/ThemesStrip";
import TransactionEntry from "@/components/TransactionEntry";
import VerdictPanel from "@/components/VerdictPanel";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useRememberedTab,
} from "@/components/ui/tabs";
import { ErrorState, ListSkeleton, Skeleton } from "@/components/ui/states";
import * as api from "@/lib/api";
import type {
  Attention,
  Curve,
  HoldingDetail,
  InvestmentSummary,
  InvestmentTransaction,
  Waiting,
} from "@/lib/api";

/* The portfolio, and the research half beside it.
 *
 * ⚠ Six tabs, each named for what is in it. They answer questions asked at different
 * frequencies — what is it worth (daily), what needs deciding (when something arrives), how
 * does each company score (when one is being assessed), what is being read (when a source is
 * added), is any of it working (monthly), what is on record (at tax time) — and stacked in one
 * column they were ordered by nothing but the order they were written in.
 *
 * ⚠ The page says what is waiting on you before you go looking. Before this, a company waiting
 * for agreement lived in the third tab and a channel waiting for approval inside a collapsed
 * panel at the bottom of it, and nothing on the tab bar said either existed. `/attention`
 * answers "what, and where" in one request; the tab counts and the "Needs you" list both read
 * it, and every action that could change it asks for it again.
 */

const TABS = [
  { key: "holdings", label: "Holdings", icon: Wallet },
  { key: "decisions", label: "Decisions", icon: ListChecks },
  { key: "companies", label: "Companies", icon: Building2 },
  { key: "sources", label: "Sources", icon: Radio },
  { key: "scorecard", label: "Scorecard", icon: Gauge },
  { key: "records", label: "Records", icon: ScrollText },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** A remembered tab from before the tabs were renamed still opens something sensible. */
function known(raw: string): TabKey {
  if (raw === "framework") return "companies";
  return (TABS.find((t) => t.key === raw)?.key ?? "holdings") as TabKey;
}

export default function InvestmentsView() {
  const [summary, setSummary] = useState<InvestmentSummary | null>(null);
  const [curve, setCurve] = useState<Curve | null>(null);
  const [transactions, setTransactions] = useState<InvestmentTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [attention, setAttention] = useState<Attention | null>(null);
  // Bumped when the inbox files something, so the research queue refreshes without a reload —
  // dropping a link and not seeing it land reads as a failure.
  const [researchNonce, setResearchNonce] = useState(0);
  /* ⚠ Remembered across reloads. Someone who came for the research queue should not be
   * returned to "Holdings" every time the page refreshes. */
  const [rawTab, setRawTab] = useRememberedTab("aceroai.investments.tab", "holdings");
  const tab = known(rawTab);
  const [range, setRange] = useState<RangeKey>("all");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "value", desc: true });
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [detail, setDetail] = useState<HoldingDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  /** Where the "needs you" list last sent the reader: a DOM id to bring into view. */
  const [arrival, setArrival] = useState<{ id: string; n: number } | null>(null);

  const since = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days;
    if (!days) return undefined;
    const d = new Date();
    d.setDate(d.getDate() - days);
    const p = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }, [range]);

  /* Two loaders, not one, because these have different lifetimes.
   *
   * Changing the time range is a question about the chart alone — it must not refetch the
   * holdings and re-run the fold. Recording a transaction changes both, so that path calls
   * `load()`. */
  const loadBook = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        api.getInvestmentSummary(),
        api.listInvestmentTransactions(),
      ]);
      setSummary(s);
      setTransactions(t);
      setFailed(false);
    } catch {
      // ⚠ Never rendered as an empty portfolio. "We couldn't load this" and "you own
      // nothing" must never look the same.
      setFailed(true);
    }
  }, []);

  const loadCurve = useCallback(async () => {
    try {
      setCurve(await api.getInvestmentHistory(since));
    } catch {
      // The chart failing is not the portfolio failing.
      setCurve(null);
    }
  }, [since]);

  /* ⚠ A failure here leaves the last answer up rather than clearing it. The counts are a
     convenience on top of panels that each load their own data; a blip must not make it look
     as though nothing is waiting. */
  const refreshAttention = useCallback(() => {
    api
      .getAttention()
      .then(setAttention)
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadBook(), loadCurve()]);
    setLoading(false);
    refreshAttention();
  }, [loadBook, loadCurve, refreshAttention]);

  const [pricesVersion, setPricesVersion] = useState(0);

  useEffect(() => {
    void loadBook().finally(() => setLoading(false));
    refreshAttention();
  }, [loadBook, refreshAttention]);

  useEffect(() => {
    void loadCurve();
  }, [loadCurve, pricesVersion]);

  // ⚠ Live prices are fetched AFTER the page has drawn, never before. The page shows what is
  // recorded at once — with each price's age — and freshens a moment later if anything was
  // stale. Waiting on the refresh first would make every open as slow as the slowest source.
  useEffect(() => {
    let cancelled = false;
    api
      .refreshPrices()
      .then((r) => {
        if (!cancelled && r.written > 0) setPricesVersion((v) => v + 1);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (pricesVersion > 0) void loadBook();
  }, [pricesVersion, loadBook]);

  useEffect(() => {
    if (!openSymbol) return;
    setDetailLoading(true);
    setDetail(null);
    api
      .getHolding(openSymbol)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [openSymbol]);

  /* Bring the row the reader was sent to into view.
   *
   * ⚠ Polled, briefly, rather than scrolled once. Each tab's panels fetch their own data when
   * the tab opens, so the row does not exist at the moment the tab changes — a single scroll
   * would find nothing on exactly the first visit, which is the one that matters. */
  useEffect(() => {
    if (!arrival) return;
    let tries = 0;
    const timer = window.setInterval(() => {
      const el = document.getElementById(arrival.id);
      tries += 1;
      if (el || tries > 25) window.clearInterval(timer);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("arrived");
      void el.offsetWidth; // restart the animation if it is the same row twice
      el.classList.add("arrived");
      window.setTimeout(() => el.classList.remove("arrived"), 2600);
    }, 120);
    return () => window.clearInterval(timer);
  }, [arrival]);

  const goTo = useCallback(
    (next: TabKey, domId: string | null) => {
      setRawTab(next);
      if (domId) setArrival((was) => ({ id: domId, n: (was?.n ?? 0) + 1 }));
    },
    [setRawTab],
  );

  const onWaiting = useCallback(
    (next: Waiting["tab"], ref: string | null) => goTo(next, ref ? `item-${ref}` : `tab-${next}`),
    [goTo],
  );

  if (loading && !summary) {
    return (
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="mx-auto max-w-5xl space-y-4 p-4">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-48" />
            <ListSkeleton rows={5} />
          </div>
        </div>
      </div>
    );
  }

  if (failed || !summary) {
    return (
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="mx-auto max-w-5xl p-4">
            <ErrorState
              title="Couldn't load your portfolio"
              detail="If this is a fresh database, the book has not been seeded yet — run app.scripts.seed_investments."
              onRetry={() => void load()}
            />
          </div>
        </div>
      </div>
    );
  }

  const waitingIn = (key: TabKey) =>
    attention?.items.filter((i) => i.tab === (key as Waiting["tab"])) ?? [];

  return (
    /* ⚠ A two-layer wrapper, not one — and the split is the fix. A single `flex-1
     * overflow-y-auto` div lets content demand more height than its share of the row, and the
     * shell grows: two scrollbars at once. `overflow-hidden` on the sizing layer is a hard clip
     * to the height flexbox gave it; the inner `h-full` fills that and scrolls within it —
     * the pattern MessageList proved against the least forgiving content in the app. */
    <div className="flex-1 overflow-hidden">
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-4 p-4 pb-16">
          {/* ⚠ At the very top, one line, always visible. Friction here kills the whole input
              channel — an inbox that takes three taps to reach is one nobody uses. */}
          <InboxDrop
            onFiled={() => {
              setResearchNonce((n) => n + 1);
              refreshAttention();
            }}
            onSee={() => goTo("decisions", "worth-a-look")}
          />

          <NeedsYou attention={attention} onGo={onWaiting} />

          <Tabs value={tab} onValueChange={(v) => setRawTab(v)} className="space-y-4">
            {/* ⚠ Two rows of three on a phone rather than a sideways scroll. Scrolled, three of
                the six tabs sat off-screen with nothing to say they existed — Sources and
                Records among them, each of which can carry a count. */}
            <TabsList
              aria-label="Investments sections"
              className="grid grid-cols-3 sm:flex"
            >
              {TABS.map(({ key, label, icon: Icon }) => {
                const waiting = waitingIn(key);
                return (
                  <TabsTrigger
                    key={key}
                    value={key}
                    className="justify-center px-2 max-sm:[&>svg]:hidden sm:justify-start sm:px-3"
                  >
                    <Icon aria-hidden="true" />
                    {label}
                    {waiting.length > 0 && (
                      <Count
                        n={waiting.length}
                        tone={severityTone(waiting)}
                        label={waiting.length === 1 ? "thing waiting" : "things waiting"}
                      />
                    )}
                  </TabsTrigger>
                );
              })}
            </TabsList>

            <TabsContent value="holdings" id="tab-holdings">
              <HoldingsTab
                summary={summary}
                curve={curve}
                range={range}
                onRange={setRange}
                sort={sort}
                onSort={setSort}
                onOpen={setOpenSymbol}
                onChanged={() => void load()}
              />
            </TabsContent>

            {/* ⚠ Everything here is waiting on a person, most pressing first: a condition that
                disproved a thesis, then live suggestions, then leads, then the themes they
                came from. What already happened — refusals and past decisions — sits below,
                closed, because it is for judging the rules rather than for acting today. */}
            <TabsContent value="decisions" id="tab-decisions" className="space-y-4">
              <ProposalsPanel onChanged={refreshAttention}>
                <ResearchPanel reloadKey={researchNonce} onChanged={refreshAttention} />
                <ThemesStrip />
              </ProposalsPanel>
            </TabsContent>

            <TabsContent value="companies" id="tab-companies">
              <FrameworkPanel onChanged={refreshAttention} arrival={arrival?.id ?? null} />
            </TabsContent>

            <TabsContent value="sources" id="tab-sources">
              <ReadingPanel onChanged={refreshAttention} />
            </TabsContent>

            {/* ⚠ A tab you choose on purpose. All of it answers "is this experiment worth
                continuing", which is a question for a scheduled sit-down and not for a spare
                minute. The criteria come first because they are the question; the comparison
                with index funds second because it is the one easiest to avoid asking. */}
            <TabsContent value="scorecard" id="tab-scorecard" className="space-y-4">
              <VerdictPanel />
              <BenchmarksPanel />
              <MeasuresPanel />
              <BooksPanel />
              <ReviewsPanel />
            </TabsContent>

            {/* ⚠ Transactions first: they are the only facts on this whole page — everything
                else is a fold over them. The yearly schedule that reads them is for tax time. */}
            <TabsContent value="records" id="tab-records" className="space-y-4">
              <TransactionEntry
                transactions={transactions}
                loading={loading}
                onChanged={() => void load()}
              />
              <ForeignHoldings />
            </TabsContent>
          </Tabs>

          <PositionSheet
            symbol={openSymbol}
            detail={detail}
            loading={detailLoading}
            onClose={() => setOpenSymbol(null)}
          />
        </div>
      </div>
    </div>
  );
}
