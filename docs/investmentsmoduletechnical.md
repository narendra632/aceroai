# Investments Module — Build Specification

*Target: hand this to a Claude Code session in VS Code as the build spec for Acero.*
*Written 3 September 2026. Verify every price and rate limit at build time — see §0.3.*

---

## 0. Read this first

### 0.1 What this document assumes

| # | Assumption | If wrong |
|---|---|---|
| A1 | Acero is as described in the briefing: FastAPI + sync SQLAlchemy 2.0, Postgres 17 + pgvector, Alembic at 013, React 19/Vite/Tailwind v4/shadcn, single user, `services/` is the single source of truth for both `api/` and `core/tools/`. | Re-map the component boundaries in §3. |
| A2 | Server is a 1 GB e2-micro, ~10 GB disk at 77%. ≈2.3 GB free, `disk_watch` alerts at 80% (≈300 MB of headroom before the alert fires). | The storage budget in §2.2 is the first thing to revisit. |
| A3 | ₹90 = $1. All rupee costs derived from USD API pricing use this. | Scale §14 linearly. |
| A4 | Real-world investing continues at roughly ₹15,000–30,000/month across 6–10 holdings, horizon weeks to quarters. Tracked universe ≈ 40 instruments (holdings + watchlist). | Row counts in §2.2 and rate-limit headroom in §9 scale linearly. |
| A5 | You are willing to open one additional broker account **purely as a market-data pipe** (never funded, never traded). See §9.1 — this is the single biggest open question. | Fall back to §9.1 Option C, which is materially worse. |
| A6 | The system's output is never shown to any third party. | See §0.4 — the regulatory analysis changes completely. |
| A7 | Timezone is Asia/Kolkata throughout; all storage is `timestamptz`. | Convention 4 already covers this. |

### 0.2 The four decisions everything else follows from

**D1 — Hybrid ledger, not manual-ledger-vs-live-tracker.** The briefing (§8.2) frames this as the biggest fork. It is a false binary. **Transactions are manual and authoritative; prices are fetched and are append-only observations.** A wrong price is visible and self-correcting. A wrong transaction is silent poison. Splitting them means the system can never be wrong about *what is held*.

**D2 — Three scores, never blended.** The frameworks produce an AB score (structural demand), a Buffett score (quality and price), and a signed Soros score (reflexivity). They are never summed into one number, because the most important finding these frameworks produce — *structurally essential, genuinely excellent, and still a bad purchase today* (GE Vernova at 90×, Solar at 98×) — is exactly the finding an average destroys.

**D3 — The model never produces a number.** Every figure is a `SourcedNumber` bound to a stored record, validated by a literal echo check against that record's text (§13.2). Every ratio is computed in Python. This is enforced by a validator, not by prompt instruction. Justification: FinanceBench measured GPT-4 Turbo with retrieval failing **81%** of questions about real filings, and ~**21%** even with the full document in context ([Patronus AI](https://www.patronus.ai/announcements/patronus-ai-launches-financebench-the-industrys-first-benchmark-for-llm-performance-on-financial-questions)).

**D4 — No backtest. Ever.** LLMs carry measurable lookahead contamination: the "Lookahead Propensity" diagnostic shows the memorisation component accounts for roughly **32%** of the apparent signal in LLM return forecasts, and the effect vanishes on post-cutoff windows ([arXiv 2512.23847](https://arxiv.org/html/2512.23847v2)). A backtest of this system would produce a confident, wrong, and very persuasive answer. Forward paper-trading is the only valid evidence. Build no backtest engine.

### 0.3 Where this document may be stale

Flagged inline as ⚠. In summary: all LLM per-token prices (§14) come from third-party trackers dated 2 September 2026, not vendor pages — re-check before committing. Gemini's YouTube-URL ingestion is a preview feature explicitly stated as "pricing and rate limits are likely to change". Kite Connect pricing shows a discrepancy between sources (₹500/mo on Zerodha's own pages vs ₹2,000/mo in a March 2025 article) — treat ₹500 as current but verify at signup. YouTube channel RSS is reported as increasingly unreliable in 2026, which is why §9.5 makes it the fallback rather than the primary.

### 0.4 Regulatory position (India) — why the architecture is shaped this way

- **Not an execution algorithm.** SEBI's retail algo framework applies to "orders generated using automated execution logic". Systems that *generate suggestions without placing orders* fall outside the definition; the own-account registration threshold is 10 orders/second/exchange, which is irrelevant to a system that places zero ([QuantInsti](https://www.quantinsti.com/articles/algorithmic-trading-india/)). **Therefore: never add order placement. It changes the system's legal category.**
- **Not investment advice.** Single user, own account, output never published. SEBI has been actively enforcing against unregistered advice and AI-driven tip services. **Therefore: no sharing endpoint, no public artifact, no export intended for anyone else.**
- **Market data licensing.** NSE's data policy prohibits redistribution outside a licensing agreement; Kite Connect's own FAQ states that displaying or redistributing its data on external platforms violates exchange data-vending policy. Personal, non-display, single-user consumption is the safe posture ([NSE data policy](https://www.nseindia.com/static/market-data/nse-data-policy)). **Therefore: no public dashboard, ever.**
- ⚠ SEBI's 30-day-lag rule for market data in *educational* content takes effect 1 July 2026 but binds market infrastructure institutions and intermediaries publishing educational content, not private personal use ([summary](https://www.kotakneo.com/news/market-news/sebi-30-day-lag-market-data-educational-content-2026/)). Relevant only if you ever publish.

---

## 1. Scope, non-goals, OpenSpec mapping

### 1.1 New and modified capabilities

| Capability | New/Modified | Why |
|---|---|---|
| `investments` | **New** | Ledger, valuation, proposals, decisions, shadow book, reviews. |
| `market-data` | **New** | Ingestion, data quality, staleness, provenance. Separate from `investments` because its behavioural contract is about *freshness and correctness of external facts*, not about portfolio rules. Keeping them apart means the ledger's spec never has to talk about rate limits. |
| `assistant-tools` | Modified | New `core/tools/investments.py`. |
| `scheduled-jobs` | Modified | 8 new jobs; one (`evening_synthesis`) runs longer than any existing job — see §7.4. |
| `notifications` | Modified | New notification kind carrying an approval action payload. |
| `observability` | Modified | Per-agent cost attribution beyond the existing per-turn tracing. |
| `ui-standards` | Modified | Chart standards applied to an equity curve and an allocation view. |

### 1.2 Non-goals (state these explicitly in `proposal.md`)

Not building: brokerage integration of any kind; order placement; real-holdings sync; tax computation or ITR preparation (tax *flags*, yes; tax *liability*, no); multi-portfolio or multi-user; intraday trading, derivatives, options; a backtesting engine (D4); automatic application of self-proposed tuning; storage of full documents, PDFs, audio, or intraday bars; any public or shared output; a mobile app beyond the existing PWA.

### 1.3 Alternatives considered and rejected

| Considered | Rejected because |
|---|---|
| Broker API sync for holdings | Defeats the paper-first premise, adds regulatory surface (§0.4), and removes the forcing function: typing "bought 1 Apar at 13,422 because the Q1 margin read confirmed" is where the decision gets articulated. |
| One blended 0–100 conviction score | Averages away the framework's central finding (D2). |
| LLM computes ratios / valuations | 81% failure rate on filing-based QA (D3). |
| Storing `current_value` on a position row | Violates convention 3 and drifts silently. Positions are a fold over transactions; ~500 transactions/year folds in well under a millisecond. |
| Backtesting the frameworks over 2020–2026 | Lookahead contamination (D4). |
| `quantstats` / `pyfolio` / `empyrical` | Pulls matplotlib + seaborn + scipy + **yfinance** onto a 1 GB box to obtain about ten formulas that are ~150 lines of pure Python. `pyfolio` is effectively unmaintained. Rejected on convention 8. |
| `yt-dlp` + Whisper for transcripts | YouTube ToS, documented cloud-IP blocking from GCP/AWS ([issue #593](https://github.com/jdepoix/youtube-transcript-api/issues/593)), plus disk and CPU cost on an e2-micro. A hosted transcript API costs ~$0.001/video. |
| WebSocket real-time price streaming | A persistent socket on a 1 GB box, for an investor with a months-long horizon. Pure cost. |
| Seven scheduled runs/day (the brief's sketch) | Noise, cost, notification fatigue. Reduced to four marks + one thinking run (§8). |
| pgvector search over research notes in v1 | The existing `recall.py` is tuned for user facts. The investment corpus in year 1 is a few thousand short rows — Postgres full-text is sufficient and free. Revisit at v3. |
| Editable notes on proposals | Append-only (§4.1). Corrections are new rows with `supersedes_id`. |

---

## 2. Phase 0 prerequisites (blocking)

### 2.1 Database backup

The briefing names this as the highest-priority known problem and records your own rule that backups ship when Investments ships. **Make it ship first.** Nightly `pg_dump --format=custom` → GCS bucket with lifecycle rules (7 daily, 4 weekly, 6 monthly), plus a `restore_check` job that monthly restores the newest dump into a scratch database and asserts row counts on three tables. An untested backup is not a backup.

### 2.2 Storage budget — hard numbers

Reserve **250 MB** for this module; alert at 200 MB. Projected year-1 growth:

| Table | Rows/yr | Bytes/row (incl. index) | MB/yr |
|---|---:|---:|---:|
| `price_observations` (40 instruments × 5 obs/day × 250 d + MF NAV) | 51,250 | ~140 | 7 |
| `source_items` (raw excerpt capped at 2 KB) | 12,500 | ~2,400 | 30 |
| `mentions` | 2,000 | ~200 | 0.4 |
| `fundamentals` | 3,200 | ~150 | 0.5 |
| `daily_valuations` (per-instrument + per-portfolio) | 16,500 | ~120 | 2 |
| `proposals` + `framework_scores` + `claims` + `invalidation_triggers` | ~3,000 | ~3,000 | 9 |
| `agent_runs` | 2,200 | ~400 | 1 |
| `transactions`, `corporate_actions`, `instruments`, `ab_mappings` | ~800 | ~300 | 0.3 |
| **Total** | | | **≈ 50 MB/yr** |

**Forbidden by design** (each would blow the budget): intraday OHLCV bars (1-minute bars for 40 instruments ≈ 2 GB/yr), PDF/document blobs, full video transcripts (store first 8 KB + structured extraction, keep the URL), tick data, per-minute valuations, embeddings of source items.

Add a `investments_disk_watch` check to the existing vitals service reporting module bytes via `pg_total_relation_size` on the module's tables.

### 2.3 Flaky memory tests

The briefing notes five memory tests failing randomly in CI and blocking deploys. This will interrupt this build at a random moment. Quarantine or fix them in Phase 0; do not discover them mid-Phase-2.

---

## 3. Architecture

```
                        ┌────────────────────────────────────────┐
  Browser ────────────▶ │  api/investments.py  api/market_data.py│  thin HTTP
  (React SPA)           └───────────────┬────────────────────────┘
                                        │
  Scheduled jobs ──────▶ ┌──────────────▼────────────────────────┐
  jobs/investments/*     │  services/                            │
                         │    portfolio.py    ledger + valuation │
  AI tool calls ───────▶ │    pricing_feed.py quotes + staleness │◀── core/tools/
  core/tools/            │    frameworks.py   AB/Buffett/Soros   │    investments.py
  investments.py         │    proposals.py    gates + lifecycle  │
                         │    shadowbook.py                      │
                         │    ingestion.py    sources + dedupe   │
                         │    corpactions.py                     │
                         │    review.py       metrics + calib.   │
                         │    taxrules.py     lots + flags       │
                         │    costmodel.py    charges            │
                         └──────────────┬────────────────────────┘
                                        │
                         ┌──────────────▼────────────────────────┐
                         │  db/models.py  (14 → 32 tables)       │
                         └───────────────────────────────────────┘

  External (all via adapters/ with a single retry+circuit-breaker wrapper):
    prices_in · prices_us · prices_crypto · nav_mf · fx
    rss_nse · rss_bse · edgar · rbi · fred · news
    youtube_uploads · transcripts · llm (existing core/llm.py facade)
```

**Convention 2 compliance**: every rule below lives in `services/`. `api/` marshals HTTP; `core/tools/investments.py` marshals tool calls; both call the same service function. Concretely, `services/proposals.approve(proposal_id, actor, reason, amount_override)` is called by `POST /api/investments/proposals/{id}/approve` **and** by the assistant tool `approve_proposal`. There is no second implementation of the gate checks.

**New adapter layer.** `adapters/` is new to Acero. Justification: eight external HTTP dependencies with different failure modes, all of which need the same retry/backoff/circuit-breaker/staleness semantics. Putting that in `services/` would mix "what the rule is" with "how the network behaved". Each adapter exposes a pure function returning `Result[T]` and never raises past its boundary.

---

## 4. Data model

Conventions applied throughout: `Numeric`, never float. `Text` + CHECK, never Postgres enums (convention 9). All timestamps `timestamptz` (convention 4). New Alembic migration per change (convention 5).

### 4.1 The append-only rule

These tables are **INSERT-only**. No UPDATE, no DELETE, no `deleted_at`:

`transactions` · `price_observations` · `fx_observations` · `fundamentals` · `source_items` · `mentions` · `framework_scores` · `proposals` · `decisions` · `agent_runs` · `claims` · `reviews`

Corrections are new rows carrying `supersedes_id`. Readers filter to rows not superseded. Enforce with a Postgres rule or a trigger raising on UPDATE/DELETE, plus a test asserting the trigger fires. This is what makes §12.5 hindsight review honest, and it is the one place where convention 6 (soft delete with undo) does **not** apply — a sale is an event, not a deletion; a wrong entry is corrected by a reversing entry, exactly as a ledger works. The UI still offers undo, implemented as "insert the reversing row".

`instruments`, `ab_mappings`, `sources`, `portfolios`, `invalidation_triggers` are mutable with soft delete per convention 6. `daily_valuations` is a rebuildable cache (§4.6).

### 4.2 Reference

```
instruments
  id PK · symbol Text · exchange Text CHECK IN (NSE,BSE,NASDAQ,NYSE,AMEX,CRYPTO,MF_IN)
  isin Text NULL · amfi_scheme_code Text NULL · name Text
  asset_class Text CHECK IN (EQUITY_IN, EQUITY_US, CRYPTO, MF_IN)
  currency Text CHECK IN (INR, USD) · sector Text NULL · industry Text NULL
  is_tracked Bool · deleted_at timestamptz NULL
  UNIQUE (exchange, symbol) WHERE deleted_at IS NULL

framework_versions
  id PK · family Text CHECK IN (india_ab, buffett_soros, gates)
  version Int · spec Jsonb        -- weights, thresholds, gate definitions
  effective_from timestamptz · notes Text · approved_at timestamptz NULL
  UNIQUE (family, version)

ab_mappings                       -- human-approved, NOT LLM-authored
  id PK · instrument_id FK · a_imperatives Text[]      -- {A1,A2,A4,A7}
  b_bottleneck Text                                     -- 'B2.1'
  crosses_a_count Int · is_crisis_accelerated Bool
  inflection_quarter Text                               -- 'FY27' | 'NOW'
  investability Text CHECK IN (GREEN, AMBER, RED)
  rationale Text · proposed_by Text CHECK IN (USER, AGENT)
  approved_at timestamptz NULL · approved_note Text NULL
  framework_version_id FK · superseded_by_id FK NULL
  -- A row with approved_at IS NULL is a suggestion and scores 0.
```

### 4.3 Ledger

```
portfolios
  id PK · name Text
  kind Text CHECK IN (MIRROR, SHADOW_VETO, SHADOW_BUDGET, SHADOW_GATE, PARALLEL_HYPERACTIVE)
  base_currency Text DEFAULT 'INR' · mode Text CHECK IN (BALANCED, HYPERACTIVE)
  monthly_budget_inr Numeric(14,2) DEFAULT 30000

transactions                      -- APPEND ONLY
  id PK · portfolio_id FK · instrument_id FK
  txn_type Text CHECK IN (BUY, SELL, DIVIDEND, BONUS, SPLIT, RIGHTS, IPO_ALLOT,
                          SIP, TRANSFER_IN, TRANSFER_OUT, FEE, TDS, ADJUSTMENT)
  trade_date Date · quantity Numeric(28,8) · price Numeric(20,6)
  currency Text · fx_rate_inr Numeric(18,8)          -- 1.0 for INR
  charges_inr Numeric(18,2)                          -- from services/costmodel
  entry_source Text CHECK IN (CHAT, SCREENSHOT, PROPOSAL_APPROVAL, CORP_ACTION, IMPORT)
  entry_ref Text NULL · note Text NULL
  supersedes_id FK NULL · created_at timestamptz
  INDEX (portfolio_id, instrument_id, trade_date)
```

`quantity` at 8 decimals so crypto and fractional US shares work. `price` at 6 so a ₹0.0025 penny NAV and a $73,412.115 BTC both fit. `fx_rate_inr` is **stored per transaction**, not looked up later — it is a fact about that moment, and §12.4 depends on it.

### 4.4 Market facts (append-only)

```
price_observations
  instrument_id FK · observed_at timestamptz · source Text
  kind Text CHECK IN (LAST, CLOSE, NAV, ADJ_CLOSE)
  price Numeric(20,6) · currency Text
  quality Text CHECK IN (OK, QUARANTINED) DEFAULT 'OK' · quarantine_reason Text NULL
  PK (instrument_id, observed_at, source, kind)

fx_observations
  pair Text · observed_at timestamptz · rate Numeric(18,8) · source Text
  PK (pair, observed_at, source)

corporate_actions
  id PK · instrument_id FK
  action_type Text CHECK IN (SPLIT, BONUS, DIVIDEND, RIGHTS, MERGER, BUYBACK, DEMERGER)
  ex_date Date · ratio_num Int NULL · ratio_den Int NULL
  amount_per_share Numeric(20,6) NULL
  announced_at timestamptz · source_item_id FK
  status Text CHECK IN (PENDING, APPLIED, IGNORED, NEEDS_REVIEW)
  applied_at timestamptz NULL · applied_txn_id FK NULL
  INDEX (instrument_id, status)

fundamentals
  instrument_id FK · fiscal_period Text          -- 'FY26Q4'
  metric_key Text                                -- roe, roce, pat, revenue,
                                                 -- ebitda_margin, ocf, capex,
                                                 -- net_debt, shares_out, book_value,
                                                 -- working_capital_days, order_book
  value Numeric(24,6) · unit Text                -- pct | inr_cr | days | ratio | count
  as_reported_at timestamptz · source_item_id FK
  PK (instrument_id, fiscal_period, metric_key, source_item_id)
```

### 4.5 Ingestion

```
sources
  id PK · kind Text CHECK IN (RSS_EXCHANGE, RSS_NEWS, YOUTUBE, EDGAR, MACRO, USER_DROP)
  name Text · handle Text                        -- channel_id | feed url | CIK
  trust_tier Int CHECK BETWEEN 1 AND 3           -- 1 = filing/official, 2 = press, 3 = commentary
  is_active Bool · deleted_at timestamptz NULL

source_items                      -- APPEND ONLY
  id PK · source_id FK · external_id Text · url Text · title Text
  published_at timestamptz · fetched_at timestamptz
  content_hash Text                              -- dedupe across feeds
  excerpt Text                                   -- HARD CAP 2 KB (8 KB for transcripts)
  extraction Jsonb NULL                          -- structured output, schema-validated
  materiality Text CHECK IN (NONE, LOW, MEDIUM, HIGH) · materiality_reason Text
  llm_cost_usd Numeric(10,6) · processed_at timestamptz NULL
  UNIQUE (source_id, external_id)
  INDEX (published_at DESC), INDEX on content_hash

mentions                          -- APPEND ONLY. The survivorship-bias killer.
  id PK · source_item_id FK · instrument_id FK
  stance Text CHECK IN (BULL, BEAR, NEUTRAL, MENTION_ONLY)
  claim_excerpt Text · became_proposal_id FK NULL
  -- EVERY instrument a source mentions is written here, acted on or not.
  -- Without this, source attribution (§12.6) is measuring only its own hits.
```

### 4.6 Decision layer

```
framework_scores                  -- APPEND ONLY
  id PK · instrument_id FK · scored_at timestamptz · as_of Date
  framework_version_id FK · model Text · prompt_hash Text
  ab_score Numeric(4,2) · ab_components Jsonb
  buffett_score Numeric(4,2) · buffett_points_available Numeric(4,2)
  buffett_components Jsonb                       -- each: {value, points, source_ref, status}
  soros_score Numeric(4,2)                       -- signed, -5..+5
  soros_flags Jsonb                              -- 10 flags: {verdict, evidence_ref, verifier_agreed}
  quadrant Text CHECK IN (Q1, Q2, Q3, Q4, BORDERLINE)
  loop_direction Text CHECK IN (UP, DOWN, INVERTED, NONE)
  loop_state Text CHECK IN (FORMING, ACTIVE, PEAKING, BREAKING)

proposals                         -- APPEND ONLY
  id PK · batch_id · created_at · agent_run_id FK
  portfolio_id FK · instrument_id FK
  action Text CHECK IN (INITIATE, ADD, HOLD, TRIM, EXIT)
  target_amount_inr Numeric(14,2) NULL · target_qty Numeric(28,8) NULL
  horizon_days Int · thesis Text · confidence Numeric(4,3)
  framework_score_id FK · framework_version_id FK
  price_snapshot Jsonb            -- {price, observed_at, source, fx_rate} FROZEN
  input_refs Jsonb                -- source_item_ids, fundamental keys, price_observation keys
  gate_results Jsonb              -- {gate_id: pass|fail|na, detail}
  urgency Text CHECK IN (BATCH, IMMEDIATE)
  model Text · prompt_hash Text · tokens_in Int · tokens_out Int · cost_usd Numeric(10,6)
  status Text CHECK IN (PENDING, APPROVED, REJECTED, MODIFIED, EXPIRED, BLOCKED, SUPERSEDED)

decisions                         -- APPEND ONLY
  id PK · proposal_id FK · decided_at timestamptz
  outcome Text CHECK IN (APPROVE, REJECT, MODIFY)
  modified_amount_inr Numeric(14,2) NULL · reason_text Text NOT NULL
  decided_via Text CHECK IN (PUSH, WEB, CHAT)
  resulting_transaction_id FK NULL · shadow_entry_id FK NULL

invalidation_triggers             -- mutable status only
  id PK · proposal_id FK · instrument_id FK
  metric_key Text · comparator Text CHECK IN (LT, LTE, GT, GTE, EQ, CROSSES_BELOW, CROSSES_ABOVE)
  threshold Numeric(24,6) · unit Text · window_until Date
  description Text                -- human-readable, shown at approval time
  status Text CHECK IN (ARMED, FIRED, EXPIRED, CLEARED, SUPERSEDED)
  fired_at timestamptz NULL · fired_evidence_ref Jsonb NULL

claims                            -- APPEND ONLY. The large-sample measurement set.
  id PK · proposal_id FK · claim_text Text
  metric_key Text NULL · comparator Text NULL · threshold Numeric(24,6) NULL
  due_by Date
  status Text CHECK IN (OPEN, TRUE, FALSE, UNVERIFIABLE)
  resolved_at timestamptz NULL · resolved_evidence_ref Jsonb NULL

shadow_entries                    -- the what-if book
  id PK · portfolio_id FK (a SHADOW_* portfolio) · proposal_id FK
  reason Text CHECK IN (VETOED, BUDGET_EXHAUSTED, GATE_BLOCKED)
  entry_price Numeric(20,6) · entry_date Date · quantity Numeric(28,8)
  exit_price Numeric(20,6) NULL · exit_date Date NULL · exit_reason Text NULL

agent_runs                        -- APPEND ONLY. Records NO-OP runs too.
  id PK · agent_name Text · occurrence_key Text UNIQUE   -- idempotency, convention 12
  started_at · finished_at · status Text CHECK IN (OK, PARTIAL, FAILED, SKIPPED)
  inputs_seen Int · inputs_material Int · proposals_emitted Int
  sources_unavailable Text[] · tokens_in Int · tokens_out Int · cost_usd Numeric(10,6)
  notes Text

reviews                           -- APPEND ONLY (a review is a document that was sent)
  id PK · period_kind Text CHECK IN (WEEK, MONTH, QUARTER)
  period_start Date · period_end Date · metrics Jsonb · narrative Text · created_at

daily_valuations                  -- REBUILDABLE CACHE, not a source of truth
  portfolio_id FK · instrument_id FK NULL   -- NULL row = portfolio total
  as_of Date · market_value_inr · cost_basis_inr · unrealised_inr · realised_to_date_inr
  fx_component_inr · rebuilt_at timestamptz
  PK (portfolio_id, instrument_id, as_of)
```

### 4.7 Stored vs computed — answering the briefing's §8.1

The line: **a value is stored if and only if it is a fact about a moment that could not be recomputed identically later.**

| Value | Stored? | Why |
|---|---|---|
| Price of INFY on 3 Sep 2026 15:30 | **Stored** | Observation. Unrecoverable later. |
| USD/INR at the moment of a US buy | **Stored** | Same. §12.4 depends on it. |
| Which price the proposal actually used | **Stored** (`price_snapshot`) | What the system *saw* is a different fact from what the market *did*. Directly parallel to `core/pricing.py` freezing LLM cost at write time — same discipline, same reason. |
| Current position quantity and cost basis | **Computed** | Fold over transactions. ~500 rows/yr; measured fold cost is sub-millisecond. Storing it invites drift. |
| Current value, absolute and % ROI, allocation % | **Computed** | Pure functions of positions × latest price. |
| XIRR, TWR, Sharpe, calibration, attribution | **Computed** | Pure functions of the ledger. |
| Framework scores | **Stored** | A score is a judgement made at a time with the data then available and the rule version then in force. Recomputing it later with today's data would silently rewrite history. |
| Daily equity curve points | **Cached** (`daily_valuations`) | Derivable, but an 18-month chart means ~550 folds per page load. Cached, with `POST /api/investments/valuations/rebuild` and a test that rebuilds a random 30-day window and asserts equality to the penny. The cache is allowed to be wrong; it is never allowed to be authoritative. |
| Review metrics | **Stored** | A review is a document that was sent to you. What it said is a fact. |
| Source attribution scores | **Computed** | Recompute from `mentions` + `proposals` + `claims` every time. |

---

## 5. Framework operationalisation

All weights live in `framework_versions.spec` as JSON. Changing a weight = a new version row = a new comparability epoch. Every `framework_scores` and `proposals` row carries `framework_version_id`, so a review can always ask "under which rules?"

### 5.1 AB Score — structural demand (0–10, deterministic)

**No LLM involvement in the arithmetic.** Computed from the approved `ab_mappings` row.

| Component | Points | Rule |
|---|---:|---|
| Bottleneck breadth | 0–4 | `crosses_a_count` ≥6 → 4; 3–5 → 3; 2 → 2; 1 → 1; unmapped → 0 |
| Crisis acceleration | 0–2 | `is_crisis_accelerated` → 2 |
| Timing fit | 0–2 | inflection = NOW → 2; inflection within `horizon_days` → 1; beyond → 0 |
| Government commitment | 0–1 | A verifiable committed spend figure exists with a `source_item_id` → 1 |
| Investability | 0–1 | GREEN → 1; AMBER → 0.5; RED → 0 |

**The critical guard:** an agent may *propose* an `ab_mappings` row, but until `approved_at` is set the AB score is **0** and gate G1 (§5.5) blocks any INITIATE. This is what prevents the model narrating an unrelated small-cap into master-bottleneck status. Approval is a one-click action in the UI, and the approval note is stored.

### 5.2 Buffett Score — quality and price (0–10, arithmetic in Python)

Computed entirely from `fundamentals` rows. The model contributes nothing here.

| Component | Points | Rule |
|---|---:|---|
| ROE | 0–2 | ≥15% in ≥3 of last 5 FY → 2; in 2 → 1; else 0 |
| ROCE | 0–2 | 5-yr average ≥15% → 2; ≥12% → 1; else 0 |
| Cash conversion | 0–2 | 3-yr mean OCF/PAT ≥0.8 → 2; ≥0.6 → 1; else 0 |
| Retained-earnings test | 0–1 | Δ market cap ÷ cumulative retained earnings (5 yr) ≥1.0 → 1 |
| Balance sheet | 0–1 | net debt / EBITDA < 2.0 → 1 |
| Margin of safety | 0–2 | MoS ≥25% → 2; 0–25% → 1; negative → 0 |

**Missing inputs score `null`, never zero.** The result is reported as `7.0 / 8.0 available` with the unavailable components named. A quality company rejected because a filing had not been ingested yet is a failure mode, not a conservative default.

**Margin of safety** requires an intrinsic value. Use a deliberately dumb, reproducible method rather than a DCF the model can flex: `IV = normalised_owner_earnings × fair_multiple`, where `owner_earnings = PAT + D&A − maintenance_capex` (maintenance capex proxied as 3-yr median D&A when not disclosed — flag it), and `fair_multiple` comes from a stored per-sector table in `spec`, not from the model. Then `MoS = (IV − market_cap) / IV`. A crude number computed the same way every time beats a sophisticated number computed differently each time; only the former can be compared across months.

### 5.3 Soros Score — reflexivity (−5 to +5, LLM-judged, evidence-gated)

The ten-flag checklist, answered `YES | NO | UNKNOWN`, **each requiring a `source_item_id` or `fundamental` reference**. No citation → forced `UNKNOWN`.

Flags 1–5 (Buffett quality flags) act as qualitative overrides recorded on the score but do not alter the arithmetic in §5.2. Flags 6–10 (Soros flags) drive the reflexivity magnitude.

**Two flags are computed, not judged** — the model's verdict is overwritten:

- **Flag 6** (multiple expanded faster than earnings): `MER = Δ(P/E over 12m) / Δ(EPS over 12m)`. `MER > 2.0` → forced `YES` regardless of what the model said.
- **Flag 10** (rapid sentiment shift): 52-week range ratio `(high − low) / low`. `> 0.60` → forced `YES`.

`soros_score` = signed intensity: `+1` per Soros YES when `loop_direction = UP`, `−1` per Soros YES when `DOWN` or `INVERTED`. This makes an inverted loop (HDFC Bank's exact situation — negative narrative over an intact business) score *negatively on reflexivity while remaining a buy*, which is the correct and non-obvious behaviour.

`loop_direction` and `loop_state` are model outputs, each requiring a one-sentence mechanism (capital access, prestige/hiring, credit terms, customer confidence) with evidence.

**Verifier pass.** A second, cheaper model receives only `{flag_text, verdict, cited_excerpt}` and answers "does this excerpt support this verdict?" Disagreement → the flag becomes `UNKNOWN` and `verifier_agreed: false` is stored. Cost ≈ $0.02/candidate (§14).

### 5.4 Quadrant (deterministic)

```
buffett_high = buffett_score / buffett_points_available >= 0.60
soros_high   = abs(soros_score) >= 3 AND loop_direction == UP

Q1 Supercharged Compounder  = buffett_high AND soros_high
Q2 Reflexive Bubble         = NOT buffett_high AND soros_high
Q3 Ignored Compounder       = buffett_high AND NOT soros_high
Q4 Structural Value Trap    = NOT buffett_high AND NOT soros_high
BORDERLINE                  = ratio within ±0.05 of 0.60, or >2 components null
```

### 5.5 Gates — hard rules in `services/proposals.py`, not in a prompt

| Gate | Rule | Rationale |
|---|---|---|
| **G1** | INITIATE requires an approved `ab_mappings` row, **or** an explicit `off_framework: true` flag. Off-framework positions are capped at 5% of portfolio in aggregate. | The framework already tolerates off-thesis positions (Rolex Rings) but must bound them. |
| **G2** | No BUY/ADD into `Q2` or `Q4`. Hard block, no override. | The frameworks' own conclusion. Q2 collapses when the narrative breaks; Q4 gets cheaper. |
| **G3** | MoS < 0 → BUY only if `mode = HYPERACTIVE` **and** size ≤ 50% of normal **and** thesis contains an explicit `paying_for_growth` field naming the years of growth being purchased. | The GE Vernova / Solar case. Allowed, but must be said out loud. |
| **G4** | ≥2 `invalidation_triggers`, each machine-checkable: metric_key + comparator + threshold + window_until. Prose triggers rejected. | "If the story changes" is unfalsifiable and therefore worthless. |
| **G5** | Every number in `thesis` resolves to a `SourcedNumber` in `input_refs` and passes the echo check (§13.2). Failures are stripped; if stripping removes >30% of numeric claims, the proposal is demoted to a research note. | D3. |
| **G6** | No proposal on an instrument within 14 days of a REJECTED proposal on the same instrument, unless a `HIGH` materiality `source_item` published after that rejection is cited. | Anti-nagging; also breaks confirmation loops. |
| **G7** | Instrument has a `PENDING` or `NEEDS_REVIEW` corporate action → no proposals, no trigger firing, P&L flagged unreliable. | §13.4. The highest-damage failure mode. |
| **G8** | Newest `OK`-quality price older than the staleness limit for that market state → no proposal. | §13.3. |
| **G9** | Daily/weekly proposal caps by mode (§6). | Overtrading. |
| **G10** | If trailing 30-day Brier score > 0.30, module degrades to research-notes-only and notifies. | Calibration circuit breaker (§13.6). |

Gate results are stored on every proposal — including for blocked ones, which are written with `status = BLOCKED` and fed to the `SHADOW_GATE` book so the cost of the rails is measurable.

---

## 6. Modes and sizing

| Parameter | Balanced (default) | Hyperactive |
|---|---|---|
| Monthly budget | ₹30,000 (editable) | same |
| Position size | 20–33% of monthly budget | up to 50% |
| Max new/add proposals per month | 4 | 8 |
| Max proposals per evening batch | 3 | 5 |
| Max single-holding weight | 20% | 30% |
| Max theme (B-bottleneck) weight | 33% | 45% |
| Max off-framework aggregate | 5% | 12% |
| Minimum confidence to propose | 0.60 | 0.45 |
| MoS < 0 permitted | No (G3 blocks) | Yes, half size, `paying_for_growth` required |
| Asset classes eligible for proposals | EQUITY_IN, EQUITY_US | + micro/small-cap tier, capped at 15% aggregate |
| Target cash reserve | 10–15% | 5% |
| Reaction latency | evening batch only | `IMMEDIATE` urgency permitted on HIGH materiality |
| Cooling-off after reject (G6) | 14 days | 7 days |

Crypto and MF are `is_tracked` and valued in both modes but never proposed in v1. Crypto's reason is arithmetic, not taste: India taxes VDA gains at a flat 30% under s.115BBH with **no set-off of losses against any income and no carry-forward**, plus 1% TDS on transfers. A strategy with a 55% hit rate that is allowed to net losses looks very different from the same strategy that is not.

**Sizing rule.** `target_amount = clamp(budget_remaining × f(confidence, ab_score, buffett_ratio), min_ticket, max_position)` where `min_ticket` is the price of one share (India has no fractional equity — a name at ₹17,000/share simply cannot be sized at ₹8,000, and the system must say so rather than round). If `one_share_price > max_position`, emit an `ACCUMULATE_POOL` proposal instead: earmark ₹X/month until a share is affordable. The existing analysis already reasons this way about Neuland; encode it.

---

## 7. Agents

Each agent = one `@job(...)` in `jobs/investments/`, calling services. Idempotent via `occurrence_key` (convention 12). Every run writes an `agent_runs` row **including no-op runs**.

### 7.1 `premarket_sweep` — 07:45 IST, Mon–Fri, `uses_ai=True`, `catch_up=2h`

- **Inputs**: US closes and FX from overnight; NSE/BSE announcement RSS delta since 16:30 yesterday; SEC filings for US holdings; RBI/FRED macro releases.
- **Deterministic first**: filter announcements to tracked instruments by symbol/ISIN. 400+ daily items collapse to 20–40.
- **LLM responsibility**: classify each surviving item's materiality (NONE/LOW/MEDIUM/HIGH) with a one-line reason, extract entities, extract any numeric facts as `SourcedNumber`s. Structured output only.
- **Outputs**: `source_items` rows; 3–6 lines contributed to the existing `morning_brief`.
- **Cannot generate proposals.**

### 7.2 `intraday_watch` — 12:30 IST, Mon–Fri, `uses_ai=False`, `catch_up=1h`

- Refresh prices for tracked instruments (1–3 batched calls). Evaluate all `ARMED` triggers. Check for HIGH-materiality items arriving since the sweep.
- **Escalation only**: if a trigger fires or a HIGH item lands on a held position, invoke `event_synthesis` (a scoped version of §7.4 covering one instrument) which *may* emit an `IMMEDIATE` proposal — Hyperactive only; in Balanced it queues for the evening.
- Zero LLM cost on a normal day. This is deliberate: the run exists for the rare event, not for a daily opinion.

### 7.3 `india_close_mark` — 16:15 IST, Mon–Fri, `uses_ai=False`

- Persist `CLOSE` observations. Apply any `PENDING` corporate actions with `ex_date <= today` (§13.4). Recompute `daily_valuations`. Evaluate triggers against closes. Run cross-source price agreement checks.

### 7.4 `evening_synthesis` — 21:00 IST, daily, `uses_ai=True`, `catch_up=4h`

The only expensive run. **Longest-running job in Acero** — budget 90–180 s wall clock, which exceeds anything currently in the registry. Two consequences: (a) run it as a chunked job that checkpoints per candidate so a timeout loses one candidate, not the batch; (b) confirm the job runner's timeout accommodates it before Phase 2, or add a `long_running=True` flag.

- **Inputs**: today's `MEDIUM`/`HIGH` source items; open positions with theses and trigger states; watchlist with last scores; `fundamentals` for candidates; framework `spec`; budget remaining; mode; market context (index level, FX, and a one-line regime note in v1 — full regime assessment is v3).
- **Sequence**:
  1. *Triage* (cheap model): which instruments warrant scoring tonight? Typically 0–3.
  2. *Score* (mid model, per candidate): produce Soros flags with evidence + loop direction/state. AB and Buffett scores computed in Python around this call.
  3. *Verify* (cheap model): the flag-evidence check (§5.3).
  4. *Propose* (mid model): for candidates surviving the gates, write action, size, horizon, thesis, confidence, triggers, claims.
  5. *Gate* (Python): apply G1–G10. Blocked proposals are written with `status=BLOCKED` and pushed to `SHADOW_GATE`.
  6. *Batch and notify*.
- **Output**: 0–3 proposals (Balanced), one notification, one `agent_runs` row. Zero proposals is a normal and frequently correct outcome.

### 7.5 `us_close_mark` — 02:15 IST (≈16:30 ET), Tue–Sat, `uses_ai=False`

Persist US closes, refresh USD/INR, evaluate US position triggers, update valuations. ⚠ Handle US DST: the offset moves between 9.5 h and 10.5 h. Store the schedule in ET and convert, do not hardcode IST.

### 7.6 `youtube_ingest` — 13:00 and 20:00 IST, `uses_ai=True`

- Poll each channel's uploads playlist. Detect new video ids against `source_items.external_id`.
- Fetch transcript (§9.5 chain). Store **first 8 KB only** plus the structured extraction.
- **LLM responsibility**: extract `{instruments_discussed[], stance, thesis_summary, verdict, claims[], timestamps[]}`. Every instrument mentioned is written to `mentions` — including ones already held, ones not tracked, and ones dismissed.
- **Trust tier 3.** Cannot itself justify a proposal; it can only raise an instrument into the scoring queue. Enforced: a proposal whose `input_refs` contain *only* tier-3 sources fails G5.

### 7.7 `inbox_processor` — event-driven, `uses_ai=True`

Triggered when you drop a URL, video link, PDF or note. Fetches, extracts, classifies materiality, attaches to instruments, writes `source_items` + `mentions`, and replies in chat with what it understood and what it did with it. Trust tier is `USER_DROP` (tier 2 by default, tier 1 if the URL resolves to an exchange or regulator domain).

### 7.8 `weekly_review` — Saturday 09:00 IST, `uses_ai=True`

Computes the §12 metrics for the week; compares against all four benchmarks; lists open triggers approaching thresholds; reports budget remaining, research queue age, and shadow-book divergence; writes a `reviews` row; sends one notification.

### 7.9 `monthly_review` — 1st of month 09:00 IST, `uses_ai=True`

Weekly plus: attribution, calibration curve and Brier score, claim resolution rate, source table with explicit `n` and an `insufficient data` state below n=20. Emits *suggested* changes to weights/thresholds/sources as **proposals requiring approval** — never applied automatically.

### 7.10 `quarterly_deep_review` — `uses_ai=True`

Full re-scoring of every holding against fresh results; framework-level review (are the A-imperatives' own claims holding?); go/no-go criteria dashboard (§12.7).

### 7.11 `screenshot_ingest` — event-driven, v1.5

See §11.

---

## 8. Schedule

| # | Job | Cron (IST) | AI | Can propose | Data touched | Est. cost/run |
|---|---|---|---|---|---|---|
| 1 | `premarket_sweep` | `45 7 * * 1-5` | ✅ cheap | ❌ | US closes, FX, NSE/BSE RSS, EDGAR, RBI/FRED | $0.03 |
| 2 | `intraday_watch` | `30 12 * * 1-5` | conditional | Hyperactive only | prices, triggers | $0.00 / $0.05 |
| 3 | `india_close_mark` | `15 16 * * 1-5` | ❌ | ❌ | closes, corp actions, valuations | $0.00 |
| 4 | `evening_synthesis` | `0 21 * * *` | ✅ **main** | ✅ | everything | $0.28 |
| 5 | `us_close_mark` | `15 2 * * 2-6` ⚠DST | ❌ | ❌ | US closes, FX | $0.00 |
| 6 | `youtube_ingest` | `0 13,20 * * *` | ✅ cheap | ❌ | channel uploads, transcripts | $0.02 |
| 7 | `inbox_processor` | event | ✅ | ❌ | user drop | $0.05 |
| 8 | `weekly_review` | `0 9 * * 6` | ✅ mid | ❌ | ledger, proposals, claims | $0.14 |
| 9 | `monthly_review` | `0 9 1 * *` | ✅ mid | tuning proposals only | as above + calibration | $0.26 |
| 10 | `quarterly_deep_review` | `0 9 1 1,4,7,10 *` | ✅ mid | rescoring only | full history | $0.60 |

**What was cut and why.** The brief sketched pre-open, open+30, midday, pre-close, post-close+1h, evening, US cadence, weekend — eight or more touches. Reduced to five scheduled plus event-driven. The open+30 and pre-close runs are removed outright: for a weeks-to-quarters horizon they can only produce reactions to intraday noise, and every one of them costs money, adds a notification, and raises the probability of an unnecessary trade. If a genuinely material event lands at 10:00, `intraday_watch` and the event path catch it; if it lands at 14:00, it waits five hours, and five hours is immaterial to a six-month thesis.

---

## 9. External integrations

Every adapter: exponential backoff (3 attempts), circuit breaker opening after 5 consecutive failures with a 15-minute cooldown, a `sources_unavailable` entry in `agent_runs` when open, and a UI banner. Never raises past its boundary.

### 9.1 Indian equity prices — the one real decision

There is no free, reliable, licensed Indian equity price API that does not require a broker account. Three honest options:

| Option | Cost | Reliability | Cost of the choice |
|---|---|---|---|
| **A. Angel One SmartAPI** ⭐ | **₹0/month** | Official broker API. Historical data free across NSE/BSE/NFO/BFO/MCX/CDS. Rate limits: historical **3/s, 180/min, 5,000/hr**; quote **10/s, 500/min, 5,000/hr** ([rate limits](https://smartapi.angelone.in/smartapi/forum/topic/4387/changes-in-api-rate-limit), [free historical](https://smartapi.angelone.in/smartapi/forum/topic/4012/release-note-free-historical-data-access-for-indices-nse-nfo-bse-bfo-mcx-and-cds-with-smartapi)) | Requires opening an Angel One account. |
| B. Zerodha Kite Connect | ⚠ ₹500/month ([Zerodha](https://zerodha.com/products/api/)) | Best-documented Indian broker API; live + historical bundled. Free "Personal" tier explicitly excludes market data. | Requires a Zerodha account **and** ₹500/month. |
| C. `yfinance` (`.NS` / `.BO`) | ₹0 | Unofficial, ToS-grey, and documented 429 rate-limiting from cloud IPs since late 2024 ([issue #2128](https://github.com/ranaroussi/yfinance/issues/2128)). | Silent, intermittent data loss on a system whose entire value is an honest record. |

**Recommendation: A, with C as a gap-filler only.** Open an Angel One account used *exclusively* as a data pipe: never funded, never traded.

This does not violate the "no brokerage connection" rule. That rule is about the **portfolio**, not about **prices**. Enforce it in code: the adapter wraps the SDK behind an **endpoint allowlist** containing only `getCandleData`, `quote`, and instrument-master download. Calls to `getHolding`, `getPosition`, `getTradeBook`, `placeOrder` and every order/GTT endpoint raise at the adapter boundary. Add a test asserting the deny-list. Note the request rate is generous but the **holdings/position endpoints are capped at 1/s** — a useful signal that they are not the intended use here anyway.

**EOD truth source**: NSE bhavcopy (free, official) fetched daily and reconciled against the intraday feed. ⚠ NSE's site is hostile to datacenter IPs and requires a cookie-priming request with browser-like headers; treat bhavcopy as a *reconciliation* source that is allowed to fail, not as the primary.

### 9.2 US equity prices

**Primary: Twelve Data free tier** — 800 requests/day, 8/minute, covers US equities, FX and crypto in one vendor. At 40 instruments and 4 marks/day using batch symbol lists, usage is well inside the free tier. **Fallback: Finnhub free tier.** Both have free tiers as of 2026 ([EODHD scorecard](https://eodhd.com/financial-academy/financial-faq/the-2026-market-data-api-scorecard-comparing-6-leading-providers)). ⚠ Twelve Data's NSE coverage is EOD-only and gated behind a paid tier, which is why India stays on Angel One.

### 9.3 Crypto

**CoinGecko Demo (free)** — 10,000 monthly call credits, 100 calls/min, flat 1-request-1-credit model, attribution required ([pricing](https://www.coingecko.com/en/api/pricing)). One `/simple/price` call returns all held coins, so usage is ~200 credits/month against 10,000. Fallback: Binance public ticker endpoint.

### 9.4 Indian mutual fund NAV

**Primary: `mfapi.in`** — free, no auth, no key, no rate limit, 10,000+ schemes, 5+ years of history, refreshed six times daily ([mfapi.in](https://www.mfapi.in/)). **Fallback: AMFI's own daily `NAVAll.txt`**, which is the upstream source and is what `mfapi.in` wraps. Implement the AMFI parser in v1 even though it is the fallback — `mfapi.in` is a community service and is a genuine single point of failure.

### 9.5 YouTube

**Discovery — primary: YouTube Data API v3 `playlistItems.list`** against each channel's uploads playlist. Cost is **1 quota unit per call** against a 10,000/day free quota; 6 channels × 2 polls/day = 12 units. (Do **not** use `search.list` — 100 units per call, and it is the standard way people exhaust this quota.) **Fallback: channel RSS** at `youtube.com/feeds/videos.xml?channel_id=…` — free and keyless, but reported in 2026 as an unsupported endpoint with intermittent 404/500s, silent multi-day outages and a 10–15 item window ([1](https://rsscribe.com/blog/youtube-rss-feeds-explained), [2](https://thecodersblog.com/youtube-rss-feed-functionality-issues-2026/)). Primary/fallback are this way round because of that.

**Transcripts — chain, in order:**

1. **Hosted transcript API (Supadata or equivalent).** ~$0.99 per 1,000 requests, free tier 100 credits/month ([comparison](https://supadata.ai/blog/best-youtube-transcript-api)). At ~30 videos/month this is $0.03–0.18/month or free.
2. **Gemini native YouTube URL ingestion.** The API accepts a YouTube URL directly; free tier allows up to **8 hours of YouTube video per day**, public videos only, currently in preview at no charge ([docs](https://ai.google.dev/gemini-api/docs/video-understanding.md.txt)). Use for videos with no captions. Note the free tier may train on inputs — acceptable here because the content is already public, but see §9.8.
3. **`youtube-transcript-api` direct.** Expect it to fail: cloud IPs are blocked, and the free proxy tiers are datacenter proxies which are also blocked ([issue #593](https://github.com/jdepoix/youtube-transcript-api/issues/593)). Keep it as a zero-cost first attempt with a fast timeout, nothing more.
4. **Do not** download audio with `yt-dlp` and transcribe. ToS violation, same IP blocking, and CPU/disk cost on an e2-micro — for a saving of about $0.15/month over option 1.

### 9.6 Exchange filings and announcements — the best free source in this whole design

**NSE publishes official RSS feeds**, verified live on 3 September 2026 returning 250+ items with company name, subject category, description, IST timestamp and a PDF link:

| Feed | URL |
|---|---|
| Announcements | `nsearchives.nseindia.com/content/RSS/Online_announcements.xml` |
| Corporate actions | `…/Corporate_action.xml` |
| Financial results | `…/Financial_Results.xml` |
| Board meetings | `…/Board_Meetings.xml` |
| Shareholding pattern | `…/Shareholding_Pattern.xml` |
| Insider trading | `…/InsiderTrading.xml` |
| Annual reports | `…/Annual_Reports.xml` |

([index](https://www.nseindia.com/static/rss-feed)) Free, official, no key, no scraping, no quota. **`Corporate_action.xml` is the single most important feed in the system** — it is what prevents §13.4.

BSE has no equivalent official feed; use the community `BseIndiaApi` pattern for BSE-only holdings, and treat BSE as best-effort.

**US: SEC EDGAR.** Free. **10 requests/second**, `User-Agent` header with contact email mandatory, JSON APIs at `data.sec.gov` for submissions and XBRL company facts, plus full-text search ([SEC](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)).

### 9.7 Macro

**FRED** (free API key, generous limits) for US rates, USD/INR (`DEXINUS`), and India series such as the real broad effective exchange rate. **RBI** press releases and the Database on Indian Economy for domestic policy and data releases — RBI publishes no API; poll the press-release page with a conservative cadence and a content hash. FII/DII daily activity: NSE's own FII/DII report and CDSL's daily FPI trends, both free, T+1.

Benchmarks: **Nifty 50 Total Return Index** (not the price index — see §12.3) and **S&P 500 TR**.

### 9.8 LLM providers

Route through the existing `core/llm.py` facade.

- **Cheap tier** (triage, materiality, verification): a Flash-Lite / nano class model.
- **Mid tier** (scoring, proposals, reviews): a Flash / Sonnet class model.
- ⚠ **Do not use the Gemini free tier for anything containing portfolio data.** Google states free-tier inputs and outputs may be used to improve models; paid tier and Vertex AI do not. Public YouTube content on the free tier is fine; your holdings are not. Your $10/month of GCP credits are best spent here, on Vertex.

---

## 10. Proposal → notification → approval → state change

```
evening_synthesis
  └─ services/proposals.create_batch(candidates, mode, budget_remaining)
       ├─ frameworks.score(instrument, as_of)          → framework_scores (INSERT)
       ├─ apply G1..G10                                → gate_results
       ├─ INSERT proposals (status=PENDING | BLOCKED)  [price_snapshot FROZEN here]
       ├─ INSERT invalidation_triggers (status=ARMED)
       ├─ INSERT claims (status=OPEN)
       └─ BLOCKED → shadowbook.record(reason=GATE_BLOCKED)

  └─ services/notifications.create(kind='investment_proposal_batch', payload={batch_id})
       ├─ 1. INSERT notifications row          ← convention 13: store, THEN deliver
       ├─ 2. attempt web push
       └─ 3. respect quiet hours; batch is valid for catch_up window

User taps → PWA opens /investments/proposals/{batch_id}
  Each card: action · amount · horizon · thesis · 3 scores (never a blended one)
             · quadrant · triggers · confidence · sources (clickable) · price at proposal
  Actions:  [Approve] [Modify amount…] [Reject — reason required]

POST /api/investments/proposals/{id}/approve|reject|modify
  → services/proposals.decide(...)          ← SAME function the assistant tool calls
       ├─ INSERT decisions (reason_text NOT NULL)
       ├─ APPROVE/MODIFY:
       │     ├─ INSERT transactions (entry_source=PROPOSAL_APPROVAL)
       │     │     charges_inr from services/costmodel
       │     └─ triggers stay ARMED, bound to the new position
       ├─ REJECT:  shadowbook.record(reason=VETOED)
       │           triggers → SUPERSEDED; claims stay OPEN (still measurable!)
       └─ recompute daily_valuations for today
```

Two details that matter:

**Rejected proposals keep their claims open.** This is the whole point — you learn nothing from a veto unless you find out later whether the thesis was right. A rejected proposal that would have worked and a rejected proposal that would have failed are the two most informative rows in the database.

**Expiry.** A `PENDING` proposal older than 3 trading days expires with `status=EXPIRED` and is routed to the shadow book as `VETOED` with reason "not actioned". Silence is a decision and is recorded as one.

**Assistant tool surface** (`core/tools/investments.py`), all calling the same services:
`record_transaction` · `get_portfolio` · `get_position` · `list_proposals` · `approve_proposal` · `reject_proposal` · `add_to_watchlist` · `drop_source` · `explain_decision(proposal_id)` · `set_budget` · `set_mode` · `get_performance(period)`

So `"add 10 shares of Apar at 13,400"` works in chat, and so does `"approve the Apar one but only 1 share, I want to keep powder for HDFC"`.

---

## 11. Screenshot ingestion (v1.5, not v1)

**Why not v1.** Plain-language entry (`"bought 1 Apar at 13,422 today"`) is faster to type than taking and uploading a screenshot, and it fails loudly rather than quietly. A misread screenshot writes a wrong transaction, which is the one class of error §0.2/D1 exists to prevent.

**Pipeline when built:**

1. Upload → store bytes **temporarily only** (`/tmp`, deleted after processing — never in Postgres, see §2.2).
2. Vision model with a strict JSON schema: `{broker_hint, as_of_date, rows:[{symbol_text, quantity, avg_price, current_price, pnl}], totals:{invested, current}}`.
3. **Symbol resolution** against `instruments` by fuzzy match. Ambiguous or unmatched → user disambiguates. Never guess.
4. **Arithmetic self-check**: for each row assert `|quantity × avg_price − implied_invested| / invested < 0.01`, and assert row totals reconcile to the stated totals. A screenshot that does not internally reconcile is rejected wholesale — this catches the majority of OCR digit errors for free, without any model confidence score.
5. **Diff, not overwrite**: compute the delta against the current computed position and present *proposed transactions* for confirmation. Nothing is written until confirmed.
6. Confirmed → `transactions` with `entry_source=SCREENSHOT`, `entry_ref` = the image hash.

Never infer a trade date from a screenshot; always ask. Broker dashboards show holdings, not trade dates, and a wrong date corrupts XIRR, holding-period tax classification, and every review.

---

## 12. Performance and attribution

All in `services/review.py`, pure Python + `Decimal`. No numpy, no scipy, no pandas (convention 8).

### 12.1 XIRR (money-weighted — measures *you*)

Solve for `r`: `Σᵢ CFᵢ / (1+r)^(dᵢ/365) = 0`, where `CFᵢ` are signed INR cash flows (buys negative, sells and dividends positive, terminal market value positive on the valuation date), `dᵢ` = days from the first flow.

Newton–Raphson from `r₀ = 0.10`, 100 iterations, tolerance 1e-7; on divergence fall back to bisection over `[-0.9999, 10.0]`. Pure Python, ~40 lines. **Test**: assert to 6 decimals against a reference case computed independently (a spreadsheet's `XIRR`), and against a known-hard case with flows clustered near the end.

### 12.2 TWR (time-weighted — measures *the strategy*)

Chain sub-period returns across every external cash flow:

```
TWR = Π (1 + (V_end,ᵢ − V_start,ᵢ − CFᵢ) / V_start,ᵢ) − 1
```

Where cash-flow timing within a day is unknown, use Modified Dietz for that sub-period: `R = (V_end − V_start − CF) / (V_start + Σ CFⱼ × wⱼ)`.

**Both numbers, always shown together.** XIRR judges the investor's timing; TWR judges the ideas. The AI is judged on TWR; you are judged on XIRR; the gap between them is one of the more interesting things this system produces.

### 12.3 Benchmarks

Four, all computed on the same date grid:

1. **Nifty 50 TRI** and **S&P 500 TR**, weighted by the portfolio's actual geographic split. ⚠ Use the *total return* index. The price index understates the real alternative by roughly the dividend yield (~1.2–1.5%/yr for Nifty), and benchmarking against it is winning by accounting.
2. **Equal-weight buy-and-hold of every INITIATE the system ever proposed**, approved or not, never sold. If the live portfolio cannot beat this, the system has ideas but no timing — a specific, actionable finding.
3. **The real-world portfolio** (from your own entries).
4. **The shadow book.**

### 12.4 Currency decomposition (mandatory for USD assets)

```
r_total_inr = (1 + r_local) × (1 + r_fx) − 1
r_fx        = FX_end / FX_start − 1
```

Report `r_local`, `r_fx` and `r_total_inr` separately on every US position and on the portfolio. Without this, a depreciating rupee silently credits the AI with skill it does not have.

### 12.5 Transaction costs and tax (Indian equity delivery)

Modelled on every simulated fill, both books. Current rates ([Zerodha charges](https://zerodha.com/charges/)):

```
brokerage         = 0                                   (delivery, most discount brokers)
stt               = 0.001 × turnover                    (both buy and sell)
exchange_txn      = 0.0000307 × turnover (NSE) | 0.0000375 (BSE)
sebi_charges      = turnover × 10 / 10_000_000          (₹10 per crore)
stamp_duty        = 0.00015 × turnover                  (buy side only)
gst               = 0.18 × (brokerage + sebi_charges + exchange_txn)
dp_charge         = 15.34 per scrip                     (sell side only)
```

⚠ Rates are broker- and date-dependent; store them in a versioned `charge_schedules` table keyed by effective date, exactly as `core/pricing.py` handles LLM prices. Freeze the applicable schedule id onto each transaction.

**Tax flags** (surfaced, never computed as a liability):

| Asset | Long-term after | LTCG | STCG | Note |
|---|---|---|---|---|
| Listed Indian equity / equity MF | 12 months | 12.5% above ₹1.25 L/yr | 20% | Budget 2026 left both unchanged; STT on commodity futures rose 0.02%→0.05%; buyback proceeds now taxed as capital gains ([Angel One](https://www.angelone.in/news/taxation/union-budget-2026-ltcg-tax-unchanged-at-12-5-stt-on-commodity-futures-hiked)) |
| US equity | **24 months** | 12.5%, no indexation | slab rate | Dividends withheld at 25% with W-8BEN; FTC via Form 67 ([Winvesta](https://www.winvesta.in/blog/investors/complete-guide-to-tax-on-us-stocks-for-indian-investors-2026)) |
| Crypto (VDA) | n/a | flat 30% (s.115BBH) | flat 30% | 1% TDS; **no loss set-off, no carry-forward** |

**Three things the system must surface at proposal time:**

1. **Days to long-term** on every TRIM/EXIT. Selling an Indian holding on day 364 versus day 366 is the difference between 20% and 12.5%.
2. **FIFO lot matching** for realised P&L — Indian demat sales are FIFO. Weighted average is fine for *display*; FIFO is required for the tax view. Implement both; label which is which.
3. **Schedule FA obligation** for any US holding. Reporting is on a **calendar year** basis (not the financial year), requires initial / peak / closing value and dividends per security in INR at SBI TT buying rates, and has **no minimum threshold** — one fractional share must be reported. Black Money Act penalties are severe ([Vested](https://vested.blog/posts/schedule-fa-for-ay-2026-27-step-by-step)). The system should therefore capture, at every US transaction, the data Schedule FA will later need: date, INR value at TTBR, and running peak. Capturing it later is impossible. ⚠ TCS on LRS remittances is 20% above ₹10 lakh/FY — irrelevant at this scale but worth a flag if budgets grow.

### 12.6 Source attribution (log in v1, score in v2)

For each source `s`, over window `W`:

```
leads(s)      = |mentions where source=s|                     -- ALL mentions
converted(s)  = |mentions where source=s AND became_proposal| 
approved(s)   = |proposals from s that were approved|
claim_hit(s)  = resolved claims TRUE / all resolved claims, for proposals citing s
precision(s)  = claim_hit(s)
lift(s)       = precision(s) / base_rate_all_sources
```

**Display rules, enforced in code:** `n < 20` → show `insufficient data`, no number. `20 ≤ n < 50` → show the number with an explicit confidence interval. `n ≥ 50` → allow it into the source-weighting proposal. Wilson score interval for the proportion.

The `leads` denominator is why `mentions` records everything. Computing precision only over acted-on ideas measures the filter, not the source.

### 12.7 Skill vs luck — the honest framing

At ₹30,000/month and 2–4 decisions in it, expect **30–45 decisions per year**. The conventional statistical floor for saying anything is ~30 observations, with 200–500 wanted for real confidence and multiple regimes required regardless of count ([sample-size guide](https://www.backtestbase.com/education/how-many-trades-for-backtest)). Additionally, the standard error of a Sharpe estimate is approximately

```
SE(SR) ≈ sqrt( (1 + SR²/2) / N )
```

With `N = 12` monthly observations and a true `SR = 1.0`, `SE ≈ 0.35`. A genuinely good strategy and a mediocre one are statistically indistinguishable over one year. **Build the dashboard to display this standard error next to every return statistic.** A number without its error bar is the mechanism by which this system would mislead you.

**Therefore measure the process, where the sample is 5–10× larger.** Each proposal generates 3–5 `claims` and ≥2 `invalidation_triggers` — 150–300 checkable predictions per year rather than 35 outcomes.

| Metric | Definition | Reaches usable n in |
|---|---|---|
| Claim accuracy | resolved TRUE / (TRUE + FALSE) | ~4 months |
| Calibration / Brier | `(1/N) Σ (pᵢ − oᵢ)²`, plus a decile reliability curve | ~6 months |
| Trigger discipline | fired triggers acted on within 2 sessions / fired triggers | immediate |
| Source precision | §12.6 | 6–12 months |

**Go/no-go criteria for real capital — pre-commit these now, in `spec`, so they cannot be softened later:**

1. ≥ 12 months continuous operation, spanning ≥ 2 distinguishable regimes.
2. ≥ 40 completed decisions (acknowledged as a small sample; the conclusion is provisional).
3. Brier score ≤ 0.20 and no systematic overconfidence in the reliability curve.
4. Claim accuracy ≥ 0.60 over ≥ 150 resolved claims.
5. Trigger discipline = 1.00. Not statistical — a system that rationalised past its own invalidation conditions even once does not get real money.
6. TWR > Nifty 50 **TRI**, net of modelled costs and taxes. Deliberately last and least informative.

Even on a clean sweep, the sane action is a small sleeve run in parallel for another year.

---

## 13. Error handling, data quality, anti-hallucination

### 13.1 Structured output everywhere

Every LLM call returns JSON validated against a Pydantic schema. Free prose is confined to designated `narrative` / `thesis` fields. A schema violation is retried once with the validation error appended, then the call fails and the run records `PARTIAL`. Never parse prose.

### 13.2 `SourcedNumber` and the echo check

```python
class SourcedNumber(BaseModel):
    value: Decimal
    unit: str
    source_ref: str        # "source_item:1234" | "fundamental:INFY/FY26Q4/roe" | "price_obs:..."
    as_of: date
```

Validation, in order:
1. `source_ref` resolves to an existing row.
2. **Echo check**: the literal value appears in that row's stored text after normalisation (strip commas, handle lakh/crore/₹/%/$, tolerate ±0.5% rounding). For `fundamental` refs, compare against the stored `value` directly.
3. Failure → the field is dropped, a `hallucination_event` is logged with the model, prompt hash and offending value, and G5 evaluates the remaining density.

This catches the specific failure mode from §0.2/D3: a plausible number in the right shape that no source contains.

### 13.3 Deny-list: computed fields the model may not emit

`roe`, `roce`, `pe`, `pb`, `ev_ebitda`, `margin_of_safety`, `intrinsic_value`, `owner_earnings`, `xirr`, `twr`, `position_weight`, `portfolio_value`, `ab_score`, `buffett_score`, `quadrant`, `multiple_expansion_ratio`.

If any appears in model output it is stripped before parsing and the Python-computed value substituted. The model provides *inputs and judgement*; code provides *arithmetic and classification*.

### 13.4 Corporate actions — the highest-damage failure mode

A 1:1 bonus halves the quoted price overnight. Unhandled: the portfolio shows −50%, an invalidation trigger fires on a phantom loss, and the evening run proposes an exit from a position that did nothing wrong. This is the single most likely way this system does real damage.

Guard, in order:
1. `corporate_action.xml` ingested every run; actions land as `PENDING`.
2. `india_close_mark` applies actions with `ex_date <= today` by inserting `BONUS`/`SPLIT` transactions that adjust quantity and per-unit cost basis while leaving total cost basis unchanged.
3. **G7**: while any action on an instrument is `PENDING` or `NEEDS_REVIEW`, P&L for that instrument is flagged `unreliable`, no proposals may reference it, and no trigger on it may fire.
4. **Independent trip-wire**: if a close moves more than 25% against the previous close with no matching corporate action and no exchange circuit-limit note, quarantine the observation, mark `NEEDS_REVIEW`, and notify. This catches actions the feed missed.

### 13.5 Price quality

- **Sanity band**: reject/quarantine an observation outside ±25% of the previous close absent a corporate action.
- **Cross-source agreement**: daily, compare primary close against the fallback for every *held* instrument. Divergence > 0.5% → quarantine both, notify, and hold valuations at yesterday's mark rather than publishing a number you cannot defend.
- **Staleness (G8)**: max age 30 minutes during market hours, 20 hours after close, 48 hours for MF NAV, 4 hours for crypto. Beyond that, prices render greyed with an explicit age, and proposals are blocked. **Never silently show a stale price as current.**

### 13.6 Circuit breakers

| Breaker | Threshold | Action |
|---|---|---|
| Calibration (G10) | 30-day Brier > 0.30 | Degrade to research-notes-only; notify |
| Hallucination rate | > 5 `hallucination_event`s in 7 days | Block proposals; notify; require manual re-enable |
| Cost | month-to-date LLM spend > 150% of the module budget | Skip `evening_synthesis`; notify (reuses the existing `budget_watch` machinery) |
| Volume | > mode's max proposals in a rolling 7 days | Suppress further proposals until the next review |
| Source outage | any tier-1 source unavailable > 24 h | Banner + `sources_unavailable` recorded on every run; reviews must state which runs were degraded |

### 13.7 Date fencing

Every prompt carries an explicit `as_of` date, and inputs are filtered `published_at <= as_of`. This is not about backtesting (there is none) but about reviews and reprocessing: a quarterly re-score that accidentally sees post-period news produces a hindsight-flavoured judgement recorded as if it were contemporaneous. Assert the filter in a test.

### 13.8 Job failure semantics

Failure of one agent never blocks another (existing registry guarantee). An agent that cannot reach prices still evaluates non-price triggers and records `sources_unavailable`. `occurrence_key` makes every run idempotent, so a catch-up run after a server restart cannot double-write transactions or duplicate proposals — assert this with a test that runs the same occurrence twice.

---

## 14. Cost estimate

⚠ Per-token prices below are from third-party trackers dated 2 September 2026, not vendor pages. Re-verify before committing.

**Reference rates** ($/1M tokens, input/output): a Flash-Lite/nano class model ≈ $0.10–0.25 / $0.40–1.50; a Flash/Sonnet class model ≈ $1.50–2.00 / $7.50–10.00. Prompt caching ≈ 10% of input; Batch API ≈ 50% off ([Gemini](https://benchlm.ai/google/api-pricing), [Anthropic](https://benchlm.ai/anthropic/api-pricing), [OpenAI](https://benchlm.ai/openai/api-pricing)).

| Agent | Runs/mo | Tokens in/out per run | Tier | $/mo |
|---|---:|---|---|---:|
| `premarket_sweep` | 22 | 16k / 3k + brief 8k / 0.5k | cheap + mid | 0.66 |
| `intraday_watch` | 22 | escalations only, ~3/mo | mid | 0.15 |
| `india_close_mark` | 22 | — | none | 0.00 |
| `evening_synthesis` | 30 | 60k in (15k cached) / 8k out, +2 candidates | mid | 6.20 |
| `us_close_mark` | 22 | — | none | 0.00 |
| `youtube_ingest` | 60 polls, ~30 videos | 10k / 2k per video | cheap | 0.35 |
| `inbox_processor` | ~20 | 15k / 2k | mid | 1.00 |
| `weekly_review` | 4 | 40k / 6k | mid | 0.60 |
| `monthly_review` | 1 | 80k / 10k | mid | 0.26 |
| `quarterly_deep_review` | 0.33 | 200k / 20k | mid | 0.20 |
| Verifier passes | ~60 | 2k / 0.2k | cheap | 0.10 |
| **LLM subtotal** | | | | **≈ $9.50** |

| Data source | $/mo |
|---|---:|
| Angel One SmartAPI (India equity) | 0.00 |
| Twelve Data free / Finnhub free (US) | 0.00 |
| CoinGecko Demo (crypto) | 0.00 |
| mfapi.in / AMFI (MF NAV) | 0.00 |
| NSE + BSE RSS, SEC EDGAR, RBI, FRED | 0.00 |
| YouTube Data API (12 units/day of 10,000) | 0.00 |
| Transcript API | 0.00–0.18 |
| **Data subtotal** | **≈ $0.20** |

**Total ≈ $9.70/month ≈ ₹875/month** at ₹90/$, against a stated tolerance of ₹2,000–3,000. That leaves genuine headroom for: switching `evening_synthesis` to a frontier model (~3× → ₹2,400/mo total), adding Kite Connect at ₹500/mo, or raising the candidate depth. **Do not spend the headroom in v1.** Establish the baseline cost per proposal first — `agent_runs.cost_usd` divided by `proposals_emitted` is the number that tells you whether a more expensive model is buying anything, and you cannot know that until you have a baseline.

Your $10/month of GCP credits should go to **Vertex AI** specifically, because Vertex does not train on inputs and the evening run is the one call that carries portfolio data.

---

## 15. Phased build plan

### Phase 0 — Foundations (blocking, ~1 week)

Backups with a tested restore (§2.1). Flaky memory tests quarantined (§2.3). `investments_disk_watch` in place.

**Done when**: a dump has been restored into a scratch database and row counts asserted; CI is green three consecutive runs; disk headroom is measured and documented.

### Phase 1 — The honest ledger (no AI decisions, ~3 weeks)

`instruments`, `portfolios`, `transactions`, `price_observations`, `fx_observations`, `corporate_actions`, `daily_valuations`. `services/portfolio`, `pricing_feed`, `corpactions`, `costmodel`, `taxrules`. Adapters for Indian equity, US equity, crypto, MF NAV, FX, NSE/BSE RSS, EDGAR. Jobs 1, 2, 3, 5. `core/tools/investments.py` with `record_transaction` / `get_portfolio` / `get_position`. The Investments page: holdings table, equity curve, allocation view, transaction entry. Morning-brief integration.

**Done when**:
- One full month where every real-world transaction was entered in plain language and the mirror portfolio reconciles with Groww's own figures to within modelled transaction costs.
- At least one corporate action ingested and applied correctly, with cost basis preserved and total value unchanged across the ex-date.
- XIRR and TWR verified to 6 decimals against an independently computed reference.
- Measured disk growth extrapolates to under the 250 MB budget.
- Staleness rendering verified by deliberately disabling a feed.

### Phase 2 — Scoring, gates and proposals (~4 weeks)

`framework_versions`, `ab_mappings` with the approval UI, `framework_scores`, `proposals`, `decisions`, `invalidation_triggers`, `claims`, `shadow_entries`, `agent_runs`. `services/frameworks`, `proposals`, `shadowbook`. Job 4 (`evening_synthesis`), notification kind + approval flow, `SourcedNumber` validators, deny-list, all circuit breakers.

**Done when**:
- 30 consecutive evenings produced either a batch or an explicit empty batch, with an `agent_runs` row every time.
- Zero unsourced numbers reached a notification — proven by `hallucination_event` counts and a red-team test that injects a fabricated figure into a source and asserts the echo check rejects it.
- Every approved proposal carries ≥2 armed, machine-checkable triggers, and at least one trigger has been observed firing correctly on real data.
- Gate G2 has blocked at least one real candidate, and that block appears in the `SHADOW_GATE` book.
- A proposal's frozen `price_snapshot` matches an independently recorded price for that moment.

### Phase 3 — Sources and review (~4 weeks)

`sources`, `source_items`, `mentions`, `reviews`. Jobs 6–10. YouTube ingestion with the full fallback chain. Inbox drop. Weekly/monthly/quarterly reviews with calibration, Brier, claim resolution, attribution and the four benchmarks. `PARALLEL_HYPERACTIVE` book. Screenshot ingestion (v1.5).

**Done when**:
- 90 days of reviews delivered.
- ≥150 claims resolved; calibration curve rendered with the Brier score and its error bar.
- Source table shows explicit `n` and an `insufficient data` state below n=20 — verified by confirming no source displays a precision figure prematurely.
- The Hyperactive parallel book has a measurable, explainable divergence from Balanced.
- A screenshot with a deliberately corrupted digit is rejected by the reconciliation check in step 4 of §11.

### Phase 4 (v3) — Regime, self-tuning, and the verdict (~4 weeks)

Market and sector regime assessment (breadth, valuations, rates, currency, FII/DII, sentiment). Source scoring with significance gating. Framework-tuning proposals — generated, versioned, human-approved, never auto-applied. The go/no-go dashboard (§12.7). Reconsider crypto/MF proposals on the evidence.

**Done when**:
- All six go/no-go criteria compute and render, each with its error bar.
- At least one framework revision has been proposed, approved, versioned, and applied — with the review able to compare pre- and post-revision performance under their respective `framework_version_id`s.
- A 12-month TWR-vs-Nifty-TRI comparison exists with its standard error displayed alongside.

---

## Appendix A — Prior art: what to borrow, what to avoid

### A.1 Open-source projects

| Project | License · scale | What it does well | **Take this** | **Avoid this** |
|---|---|---|---|---|
| [**TradingAgents**](https://github.com/TauricResearch/TradingAgents) (Tauric Research) | Apache 2.0 · ~98k ★, active (v0.3.1, Jul 2026) | Multi-agent firm simulation: analyst team → bull/bear researcher debate → trader → risk manager → PM approval, on LangGraph. The [paper](https://arxiv.org/pdf/2412.20138) is worth reading. | **The adversarial pattern.** A bull agent and a bear agent arguing before a decision is the cheapest known mitigation for confirmation loops. Adopt it inside `evening_synthesis` as a two-persona pass over the same evidence — but as *prompt structure*, not as a second framework. | The whole framework. LangGraph on a 1 GB box is a large dependency for orchestration you can express in ~200 lines of service code. Its own README concedes results are **not reproducible** — "two runs of the same ticker and date can differ" — which is disqualifying for a system whose product is an audit trail. Its data layer leans on Yahoo Finance and Reddit/StockTwits sentiment; both are wrong for this use case. |
| [**ai-hedge-fund**](https://github.com/virattt/ai-hedge-fund) (virattt) | MIT · ~63k ★, active | Investor-persona agents (Buffett/Munger-style) as pluggable, backtestable alpha models. Explicitly paper-only: "the system does not actually make any trades." | **The persona-as-pluggable-model idea**, which maps cleanly onto `framework_versions`: each scoring family is a versioned, swappable unit. Also its clean separation of signal generation from portfolio construction. | Its Financial Datasets API dependency — **no free tier**, $20 for 1,000 requests, and India coverage is not the product's focus. Also its backtester: see D4. |
| [**OpenBB**](https://github.com/OpenBB-finance/OpenBB) | **AGPLv3** · ~72.5k ★, very active | The best provider-abstraction layer in open finance — one interface over many vendors, which is precisely the `adapters/` problem. | **The provider-abstraction design.** Read `openbb_core`'s provider interface and copy the shape: a standard model per data type, per-provider mappers, graceful degradation. | **Do not depend on it.** AGPLv3 is a real consideration for a personal project you may later share, and the dependency tree is far too heavy for an e2-micro. Copy the pattern, not the package. India coverage also runs through third-party providers rather than being first-class. |
| [**QuantStats**](https://github.com/ranaroussi/quantstats) | Apache 2.0 · maintained | Tearsheets, drawdown analysis, Monte Carlo, ~40 performance statistics. | **The metric definitions.** Read `stats.py` as a reference implementation and port the six formulas you actually need. | The dependency: pandas + numpy + scipy + matplotlib + seaborn + **yfinance**, to obtain ~10 formulas. Rejected on convention 8. `pyfolio` (Quantopian) is worse — effectively unmaintained since Quantopian's shutdown. |
| **Beancount / Firefly III / Actual** | Various OSS, all maintained | Double-entry ledgers with proper handling of lots, corporate actions and multi-currency. | **The double-entry discipline and the lot model.** Beancount's treatment of a stock split as an event that conserves total cost basis is exactly §13.4. Read its cost-basis booking methods before writing `services/portfolio`. | Running any of them alongside Acero. This is a schema lesson, not a component. |
| `jugaad-data`, `nsepython`, `BseIndiaApi`, `mftool` | MIT-ish, community, variable upkeep | Indian market data scraping wrappers. | **Read them for the endpoint shapes and the header/cookie dance NSE requires.** Especially useful for the bhavcopy reconciliation path (§9.1). | Depending on them. They scrape endpoints that change without notice, and they carry the same datacenter-IP problem. Vendor the two or three functions you need, pinned and tested. |

**The meta-lesson from this survey**: every popular agentic-trading repo optimises for *demonstrating a decision loop*. None of them optimise for *producing an honest, immutable, measurable record* — which is this system's entire purpose. Borrow their prompt structures and their data abstractions; write the ledger, the provenance and the review yourself.

### A.2 Commercial products

| Product | What it gets right — copy this | Where it falls short — your opening |
|---|---|---|
| **Zerodha Console / Groww / INDmoney** | Transaction-level truth: every charge itemised, XIRR computed correctly, tax P&L reports with FIFO lot matching. Groww is your source of truth for reconciliation in Phase 1. | No reasoning layer at all. They record what you did; they never ask whether you should have. Zero memory of *why*. |
| **Tickertape / Trendlyne / Screener.in** | Excellent Indian fundamentals coverage, screeners, and — Trendlyne especially — event calendars and result-date tracking. Trendlyne is ~₹310/mo. | No API for any of them at retail tier, so none can be a data source. Screens are stateless: they tell you what passes a filter today, never what you concluded three months ago or whether it held. |
| **Sharesight / Snowball Analytics / Kubera / Capitally** | Multi-currency handling done properly — separating local return from FX return is standard here, which is why §12.4 is non-negotiable. Sharesight's corporate-action automation is the benchmark. | Indian coverage is weak-to-absent in most; none reason about theses; and all are subscription products that own your data. |
| **Composer (SoFi)** | Strategies as explicit, inspectable, backtestable objects rather than opaque signals — and automated rebalancing with the logic visible. | It backtests, which is exactly the trap (D4), and its users overwhelmingly select strategies *by* backtest performance. US-only. |
| **Danelfin** | A single AI score with a *published, historical, verifiable* track record — the honesty of publishing the score's realised performance is genuinely good practice. | A single blended score, which is precisely what D2 rejects: it cannot tell you that a company is excellent *and* too expensive. Also a black box — no reasoning to audit. |
| **AlphaSense / Fiscal.ai (formerly FinChat) / Boosted.ai** | Document-grounded answers with citations back to the source paragraph. Fiscal.ai's citation UX is the model for how §13.2 should *render*. AlphaSense's coverage of transcripts and broker research is genuinely unmatched. | AlphaSense is five figures a year. Fiscal.ai is retail-priced but has thin India coverage. Neither maintains a portfolio, holds a thesis over time, or grades itself. |
| **Ghostfolio** (self-hosted, OSS) | The closest existing thing to Phase 1: privacy-first, self-hosted, multi-asset, decent analytics. Worth an afternoon of reading. | No decision layer, no research ingestion, no frameworks, weak Indian instrument coverage. |

**The gap none of them fill** — and therefore the thing worth building — is the join between *the record of what you did*, *the reasoning that produced it*, and *a scheduled, honest grading of that reasoning*. Every product above does one of those three well and ignores the other two.

---

## Appendix B — Failure modes and where each is mitigated

| # | Failure mode | How it would show up here | Mitigation | Where |
|---|---|---|---|---|
| 1 | **Hallucinated figures** | A thesis citing "ROE 24%" for a company whose filings say 13%. FinanceBench: 81% failure with retrieval. | `SourcedNumber` + literal echo check + computed-field deny-list + `hallucination_event` circuit breaker | D3, §13.2, §13.3, §13.6 |
| 2 | **Lookahead / memorisation bias** | Impressive-looking historical validation that is recall, not reasoning. Measured at ~32% of apparent signal. | No backtest engine is built. Forward paper-trading only. Date fencing on every prompt. | D4, §13.7 |
| 3 | **Recency bias** | The last thing read dominates the thesis. | AB score is human-approved and slow-moving; Buffett score uses 3–5 year windows; G6 cooling-off; trust tiers cap commentary's weight | §5.1, §5.2, §5.5 |
| 4 | **Narrative chasing** | Buying the loudest story at the worst price. | G2 hard-blocks Q2; G3 forces `paying_for_growth` to be stated; flags 6 and 10 are computed, overriding the model | §5.3, §5.5 |
| 5 | **Overtrading** | A daily system finds daily reasons to act. Barber & Odean's finding is the base rate. | Runs cut 8→5; per-mode proposal caps (G9); modelled transaction costs and the STCG/LTCG differential in every proposal; "propose nothing" is a first-class, logged outcome | §8, §6, §12.5 |
| 6 | **Survivorship bias in source scoring** | Judging a channel only on the ideas you acted on. | `mentions` records **every** instrument every source names, acted on or not, as the denominator | §4.5, §12.6 |
| 7 | **Confirmation loops** | The system re-reads its own prior conclusions as evidence. | Prior `framework_scores` are not fed back as inputs, only as a delta for the review; adversarial bull/bear pass (A.1); the verifier model sees only evidence, never the prior verdict | §5.3, §7.4 |
| 8 | **Hindsight distortion** | Reviews that explain why the outcome was obvious. | Append-only proposals with frozen `price_snapshot`, `prompt_hash`, `model` and `framework_version_id`; UPDATE/DELETE triggers raise | §4.1, §4.6 |
| 9 | **Corporate actions corrupting P&L** | A bonus issue reads as a 50% loss; a trigger fires; an exit is proposed. **Highest-damage mode.** | Corporate-action RSS ingestion; G7 blocks proposals and trigger firing while pending; independent >25% move trip-wire | §13.4 |
| 10 | **Stale prices shown as current** | Valuations quietly frozen at a dead feed's last tick. | Per-market-state staleness limits; G8 blocks proposals; UI greys stale values with an explicit age | §13.5 |
| 11 | **FX flattering returns** | Credit taken for rupee depreciation. | Mandatory decomposition into `r_local` and `r_fx` on every USD asset | §12.4 |
| 12 | **Benchmark gaming** | Beating the price index instead of the total-return index. | Nifty 50 **TRI** and S&P 500 **TR**, plus three additional benchmarks | §12.3 |
| 13 | **Small-sample self-congratulation** | "Up 18%, the system works" on 20 trades in one bull quarter. | Standard error rendered next to every return statistic; process metrics (claims, calibration) carry the measurement load; six pre-committed go/no-go criteria | §12.7 |
| 14 | **Overconfidence** | Every proposal at 0.85 confidence. | Brier score tracked continuously; G10 degrades the module to research-notes-only above 0.30 | §5.5, §12.7 |
| 15 | **Ignoring its own invalidation triggers** | Rationalising past a fired trigger because the story is still good. | Trigger discipline measured at 1.00 or the system fails go/no-go outright — not a statistical criterion | §12.7 |
| 16 | **Silent data-source degradation** | A feed dies; the system reasons confidently on a partial world. | `sources_unavailable` on every `agent_runs` row; reviews must state which runs were degraded; 24h outage banner | §13.6, §13.8 |
| 17 | **Cost blowout** | An agent loop burns the month's budget in a night. | Per-run cost recorded; 150%-of-budget breaker skips the expensive run; reuses existing `budget_watch` | §13.6 |
| 18 | **Scope creep into a trading system** | "It's so good, let's let it place the order." | Documented as a non-goal, with the regulatory reason attached: order placement changes the system's legal category | §0.4, §1.2 |

---

## 16. Open questions — answer these before Phase 1

1. **Will you open an Angel One account purely as a data pipe?** (§9.1) This is the load-bearing question. Yes → ₹0/month and a reliable feed. No → the fallback is `yfinance`, which drops data silently, and silent data loss in a system whose product is an honest record is a serious compromise. If no, the next-best is paying a data vendor rather than accepting `yfinance`.

2. **Which channels, exactly?** Name the 2–3 India-focused and 2–3 global channels and their channel IDs. The choice materially shapes what the system reads, and swapping them later resets source attribution's sample size to zero.

3. **What is the real starting portfolio?** Seed transactions for the six or seven current holdings — symbol, quantity, average price, and *approximate acquisition dates*. Dates matter more than precision here: they drive XIRR and holding-period tax classification.

4. **Does the AI's paper book start empty, or mirroring your current holdings?** Empty gives a clean measurement of the AI's decisions from day one. Mirroring makes the comparison against your real portfolio like-for-like from day one. **Recommendation: both** — `MIRROR` seeded with your holdings, plus an `AI_CLEAN` portfolio starting from zero cash. The second is the one that actually measures the AI.

5. **Web push only, or Telegram too?** The briefing mentions a `telegram` capability. Proposal notifications during quiet hours are a real design question given that quiet hours currently delay warnings by up to a day (known problem #3).

6. **Confirm the ₹30,000/month is notional or real.** If the paper book deploys ₹30,000/month but the real one deploys ₹15,000, the two are not comparable and the shadow book's budget ledger is measuring the wrong constraint.

7. **US holdings — do any exist today?** If yes, Schedule FA capture (§12.5) must start in Phase 1, because the peak-value figure for the calendar year cannot be reconstructed later.

8. **Job runner timeout.** Confirm `evening_synthesis` at 90–180 s fits the existing runner, or agree the `long_running` flag before Phase 2 (§7.4).

9. **Are you willing to pre-commit the §12.7 go/no-go criteria now, in writing, before any results exist?** This is the single highest-value discipline in the whole plan, and it is worth nothing if the thresholds are set after you have seen how the system performs.

---

## Sources

[Zerodha Kite Connect pricing](https://zerodha.com/products/api/) · [Kite Connect FAQs](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs) · [Zerodha charges](https://zerodha.com/charges/) · [Angel One SmartAPI rate limits](https://smartapi.angelone.in/smartapi/forum/topic/4387/changes-in-api-rate-limit) · [SmartAPI free historical data](https://smartapi.angelone.in/smartapi/forum/topic/4012/release-note-free-historical-data-access-for-indices-nse-nfo-bse-bfo-mcx-and-cds-with-smartapi) · [Dhan data API pricing](https://dhan.co/support/platforms/dhanhq-api/how-can-i-access-live-market-data-through-dhan/) · [mfapi.in](https://www.mfapi.in/) · [AMFI NAVAll.txt](https://portal.amfiindia.com/spages/NAVAll.txt) · [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing) · [EODHD 2026 API scorecard](https://eodhd.com/financial-academy/financial-faq/the-2026-market-data-api-scorecard-comparing-6-leading-providers) · [Twelve Data NSE](https://twelvedata.com/exchanges/XNSE) · [Financial Datasets pricing](https://www.financialdatasets.ai/pricing) · [yfinance rate limiting](https://github.com/ranaroussi/yfinance/issues/2128) · [NSE RSS feeds](https://www.nseindia.com/static/rss-feed) · [NSE announcements feed](https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml) · [NSE all reports](https://www.nseindia.com/all-reports) · [NSE data policy](https://www.nseindia.com/static/market-data/nse-data-policy) · [SEC EDGAR access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [Gemini video understanding](https://ai.google.dev/gemini-api/docs/video-understanding.md.txt) · [Gemini free tier limits](https://pecollective.com/tools/gemini-free-tier-guide/) · [youtube-transcript-api cloud blocking](https://github.com/jdepoix/youtube-transcript-api/issues/593) · [YouTube transcript API comparison](https://supadata.ai/blog/best-youtube-transcript-api) · [YouTube RSS feeds explained](https://rsscribe.com/blog/youtube-rss-feeds-explained) · [YouTube RSS reliability 2026](https://thecodersblog.com/youtube-rss-feed-functionality-issues-2026/) · [Whisper API pricing](https://tokenmix.ai/blog/whisper-api-pricing) · [TradingAgents](https://github.com/TauricResearch/TradingAgents) · [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) · [OpenBB](https://github.com/OpenBB-finance/OpenBB) · [quantstats](https://github.com/ranaroussi/quantstats) · [FinanceBench](https://www.patronus.ai/announcements/patronus-ai-launches-financebench-the-industrys-first-benchmark-for-llm-performance-on-financial-questions) · [Detecting Lookahead Bias in LLM Forecasts](https://arxiv.org/html/2512.23847v2) · [Backtest sample size](https://www.backtestbase.com/education/how-many-trades-for-backtest) · [Union Budget 2026 capital gains](https://www.angelone.in/news/taxation/union-budget-2026-ltcg-tax-unchanged-at-12-5-stt-on-commodity-futures-hiked) · [LTCG FY2026-27](https://www.bajajfinserv.in/investments/understanding-long-term-capital-gains-tax) · [Tax on US stocks for Indian investors](https://www.winvesta.in/blog/investors/complete-guide-to-tax-on-us-stocks-for-indian-investors-2026) · [Schedule FA AY 2026-27](https://vested.blog/posts/schedule-fa-for-ay-2026-27-step-by-step) · [SEBI algo trading framework](https://www.quantinsti.com/articles/algorithmic-trading-india/) · [SEBI 30-day data lag](https://www.kotakneo.com/news/market-news/sebi-30-day-lag-market-data-educational-content-2026/) · [Gemini API pricing](https://benchlm.ai/google/api-pricing) · [Anthropic API pricing](https://benchlm.ai/anthropic/api-pricing) · [OpenAI API pricing](https://benchlm.ai/openai/api-pricing) · [Barber & Odean, Behavior of Individual Investors](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/behavior%20of%20individual%20investors.pdf) · [TradingAgents paper](https://arxiv.org/pdf/2412.20138) · [Ghostfolio overview](https://www.pistack.xyz/posts/ghostfolio-self-hosted-portfolio-tracker-wealth-management-guide-2026/) · [Portfolio tracker comparison 2026](https://www.mycapitally.com/blog/best-portfolio-tracker-for-the-modern-diy-investor) · [Composer review](https://alphagaindaily.com/en/blog/composer-ai-trading-review) · [Danelfin review](https://alphagaindaily.com/en/blog/danelfin-ai-stock-analysis-review) · [AlphaSense pricing](https://www.vendr.com/marketplace/alphasense) · [Fiscal.ai (formerly FinChat) review](https://www.fintipster.com/fiscal-ai-review/) · [Trendlyne pricing](https://www.stockmaniacs.net/trendlyne-review/) · [jugaad-data](https://github.com/jugaad-py/jugaad-data) · [BseIndiaApi](https://github.com/BennyThadikaran/BseIndiaApi)
