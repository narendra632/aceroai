# Phase 2 inputs: A-imperatives, B-taxonomy, ten flags, fair multiples, Indian fundamentals

*Prepared 20 Sep 2026 for the Claude Code session building aceroai Investments Phase 2.*
*Sources: Narendra's project docs: `india-AB-framework-v2-exhaustive.md` (6 Apr 2026, "the framework"), `buffet-reflexivity.md` ("the checklist prompt"), `buffett-soros-analysis-updated-june8.html` ("the June 8 analysis"). Item 5 is web research plus live checks of NSE endpoints, run on 20 Sep 2026.*

**Legend.** **NOTES**: stated in his material, quoted or closely paraphrased. **DERIVED**: I read it off his material mechanically (for example, counting a list). **PROPOSAL**: my suggestion; his material doesn't say it. **UNRESOLVED**: his material is silent or contradicts itself, and a human has to decide.

---

## 1. The A-imperatives

**Authoritative count: 10** (NOTES: "India must build sovereign capability across 10 critical domains"). They're ranked by urgency, so the order matters. **Only one B in the whole framework reaches ≥6 crossings (B1.1).** The top AB-breadth tier is effectively reserved for transmission.

| id | Name | What it means (his framing) | Urgency (NOTES) | Crisis accelerant named (NOTES) |
|---|---|---|---|---|
| A1 | Energy Sovereignty & Grid Transformation | India imports ~85% of its crude and ~50% of its gas and has ~9.5 days of strategic reserves, while 50 GW of renewables sit stranded for lack of grid. Every other imperative depends on this one: fabs, data centres, defence and EV charging all need reliable power. | CRITICAL (survival) | Hormuz closure, LPG rationing, 50 GW stranded renewables |
| A2 | Semiconductor & Electronics Self-Reliance | India imports ~100% of its chips, so every phone, missile and car depends on foreign supply. The goal is OSAT → components → fab, moving from assembly to real value-add. | CRITICAL | US–China chip war, supply-chain fragmentation, defence electronics import dependency |
| A3 | AI & Compute Sovereignty | India generates ~20% of the world's data but owns under 5% of compute. The realistic play is to lead in vertical and Global-South AI applications, not frontier model training. | HIGH (window closing) | US–China concentration of AI gains |
| A4 | Defense Self-Reliance | India is the world's largest defence importer, and a real war (May 2025) used up stocks. Defence is shifting from platforms to electronics, drones and munitions, with a target of 70% indigenous procurement by 2027. | HIGH | May 2025 India–Pakistan conflict; Iran war |
| A5 | Pharma & Biotech Sovereignty | India is the world's generics supplier but imports ~35% of its API demand, mostly from China. The Biosecure Act opens a CDMO/API share-shift window. | HIGH (window open now) | US Biosecure Act; API diversification away from China |
| A6 | Electronics Manufacturing & China+1 Capture | The wider manufacturing base (electronics, auto components, textiles and more) must capture China+1. Manufacturing is 13–14% of GDP, and logistics costs 16–17% of GDP. | HIGH (window closing) | US 50% tariffs on Indian exports |
| A7 | Space Economy | India holds 2–3% of the global space market and targets 8–10% (US$44B by 2033). Space Policy 2023 opened the sector to private players. | MEDIUM-HIGH | None (a catalyst, not a crisis) |
| A8 | Digital Economy & Fintech Dominance | India is already a leader here: UPI, Aadhaar, GIFT City, 1,800+ GCCs. The job is to export India Stack and scale it. | MEDIUM-HIGH | None (a strength signal) |
| A9 | Electric Vehicles & Clean Mobility | The target is 30% EV penetration by 2030. The critical gap is that ~100% of Li-ion cells are imported. | MEDIUM | None (a catalyst) |
| A10 | Food & Water Security | India imports ~28–30% of its fertiliser and faces severe water stress. Hormuz showed that fertiliser shares the oil chokepoint. | MEDIUM (slow-burning) | Hormuz threat to fertiliser imports; groundwater depletion |

**Government-commitment figures** (useful for the AB "government commitment" point) are stated per A in the framework, e.g. A1 "₹200+ trillion by 2047", A2 "₹76,000 Cr ISM + ₹22,919 Cr ECMS PLI". **UNRESOLVED:** the spec requires a `source_item_id` for that point. His framework doc isn't a `source_item`, so each figure needs an official source (budget document, PIB release) ingested before it can score.

---

## 2. The B-bottleneck taxonomy

### 2.1 How to read the crossings column

- The framework says: *"When a B appears under 3+ As, it's a 'master bottleneck'."*
- **Explicit crossings exist only for the 8 rows in his "Master Bottleneck Map".** For every other B, his notes put it under its parent A and give nothing more. For those I give **count = 1 (parent only)**, list any cross-references his text mentions, and mark the count provisional.
- **Aliases** (NOTES): B8.2 ≡ B3.1 ("Same as B3.1"), and B9.1 ≡ B1.2 ("Same as B1.2"). **PROPOSAL:** store one canonical id with an alias table so a crossing can't be counted twice.

### 2.2 Crisis flag, inflection and investability

- **Crisis flag.** `EXPLICIT` means his text ties this B to one of the three named shocks (the Aug 2025 tariffs, the Feb 2026 Hormuz crisis, the May 2025 India–Pakistan conflict). `IMPLIED` means only the parent A has an accelerant. `NO` means nothing is stated. **PROPOSAL:** set `is_crisis_accelerated = true` only for EXPLICIT.
- **Inflection** is taken from each B's "Inflection:" line and the Timeline table.
- **Investability** maps his emoji: 🟢 = GREEN, 🟡 = AMBER, 🔴 = RED.

### 2.3 The table

| id | Name | One line | Crosses (A-ids) | Count | Crisis | Inflection | Invest. |
|---|---|---|---|---:|---|---|---|
| **B1.1** | Power Transmission & HVDC | 50 GW of renewables stranded without lines; inter-regional capacity must go 120 → 168 GW by 2032 | **CONFLICT** (see U1) | **6** | IMPLIED | NOW (peak FY26–30) | GREEN |
| **B1.2** (≡B9.1) | BESS / Cell Manufacturing | Needs 236 GWh of storage by 2032 against <1 GWh today; 100% of cells imported | A1, A3, A9 | 3 | **EXPLICIT** ("pulled forward 2–3 years") | FY27–28 (text: "may pull to FY26–27") | AMBER |
| **B1.3** | Smart Grid & Metering | 25 crore meters mandated, 5.83 crore installed; AT&C losses ~15% | A1, A6, A8 | 3 | **EXPLICIT** (portfolio table: "demand management during crises") | NOW (FY26–29) | GREEN |
| B1.4 | Nuclear Energy | 7.5 GW today, 100 GWe target by 2047; SHANTI Act opens it to private players | A1 | 1 | **EXPLICIT** ("Nuclear energy budget boosted") | FY28–30 SMRs; FY32+ thorium | AMBER |
| **B2.1** | OSAT & Packaging | India's semiconductor on-ramp; Kaynes is the first private OSAT | A2, A3, A4, A7 | 4 | **EXPLICIT** ("Kaynes OSAT became a strategic national asset") | FY27 | GREEN |
| B2.2 | Electronics Component Manufacturing | 60–70% of output is still assembly; PCBs, displays and passives are missing | A2 (portfolio table also maps Syrma → A4, A6) | 1 (provisional) | NO | FY27–28 | AMBER |
| B2.3 | Fab Manufacturing | Tata-PSMC 28 nm fab, Gujarat | A2 | 1 | NO | FY28–29 at earliest | AMBER |
| B2.4 | Ultra-Reliable Power & Water | Fabs need 100+ MW of continuous power and ultra-pure water | A2 (cross-refs B1.1, B1.2) | 1 | NO | not stated | GREEN |
| **B3.1** (≡B8.2) | Data Centre & Compute Infrastructure | 1.4 GW today against 9 GW needed by 2030 | A1, A3, A8 | 3 | NO | FY27–30 | AMBER |
| B3.2 | AI Chip Access & Domestic Alternatives | Nvidia holds 80–95% of the market; no Indian alternative | A3 | 1 | NO | FY30+ | RED |
| B3.3 | Talent Retention & Development | AI brain drain; PhD pipeline gap | A3 | 1 | NO | "Gradual, 3–5 yr" | AMBER |
| B4.1 | Defense Electronics & EMS | Without domestic electronics, "indigenous" defence is just assembly | A4 | 1 | IMPLIED ("restocking cycle + accelerated procurement") | NOW | GREEN |
| **B4.2** | Ammunition & Explosives | Stock consumed in conflict must be replaced | A4 | 1 | **EXPLICIT** ("crisis-driven") | NOW (FY26–28) | GREEN |
| B4.3 | Advanced Materials & Propulsion | Superalloys, composites, propellants | A4 | 1 | NO | FY27–28 | AMBER |
| **B5.1** | Bulk Drug & API Scale | Fermentation, complex and high-potency APIs where China dominates | A5, A10 | 2 | NO (Biosecure isn't one of the three shocks; see U4) | NOW | GREEN |
| **B5.2** | CDMO / CRAMS | India's "IT outsourcing" for pharma | A5, A10 | 2 | NO (see U4) | NOW | GREEN |
| B5.3 | Biotech & Biosimilars | GMP-grade biomanufacturing at scale | A5 | 1 | NO | FY27–30 | AMBER |
| **B6.1** | Logistics & Supply Chain | Logistics costs 16–17% of GDP (vs 8% in China) | A5, A6 | 2 | IMPLIED (tariffs → A6) | FY27–28 | GREEN |
| B6.2 | Skilled Manufacturing Workforce | CNC operators, clean-room and process engineers | A6 | 1 | NO | not stated | AMBER (no listed play) |
| B6.3 | Industrial Land & Infrastructure | Plug-and-play parks | A6 | 1 | NO | FY28–30 | AMBER |
| B7.1 | Private Launch Vehicles | ISRO-dependent; PSLV failures | A7 | 1 | NO | FY28–30 | AMBER |
| B7.2 | Satellite Mfg & Space Electronics | Rad-hard electronics, SAR | A7 | 1 | NO | FY28–30 | AMBER |
| B7.3 | Space Applications & Data | EO and geospatial services | A7 | 1 | NO | FY28–30 | AMBER |
| B8.1 | Cybersecurity & Data Protection | 702 attacks/min; DPDP Act, CERT-In audits | A8 | 1 | NO | NOW | AMBER ("Investability: Poor") |
| B8.3 | Digital Payments & Financial Infra | UPI internationalisation, rupee settlement, GIFT City | A8 | 1 | NO | NOW | GREEN |
| B9.2 | Charging Infrastructure | 22,100 fast chargers planned; 10x more needed | A9 (text: "links to A1") | 1 | NO | not stated | AMBER |
| B9.3 | EV Power Electronics & Motors | SiC MOSFETs and IGBTs are imported | A9 (text: "Links to A2") | 1 | NO | not stated | AMBER (text: "no clean listed play") |
| **B10.1** | Fertilizer Self-Sufficiency | ~28% of urea, ~90% of potash, ~50% of DAP imported | A10 | 1 | **EXPLICIT** ("became urgent") | FY27 ("post-crisis") | GREEN |
| B10.2 | Water Treatment & Recycling | Industrial-grade water for fabs and data centres | A10 (A10 intro links water → A2, A3) | 1 (provisional) | NO | FY28+ | AMBER |
| B10.3 | Agri-Tech & Supply Chain | 30–40% of produce lost to poor cold chain | A10 | 1 | NO | not stated | AMBER |

### 2.4 What the scoring should know from this

- **"Crisis-accelerated Bs > normal Bs for 12–18 month returns"** is his Principle 4.
- **"Survival-driven spending > aspiration-driven spending"** is his stated principle.
- His three "super-bottlenecks" are **B1.1, B1.2/B9.1 and B2.1**.

### 2.5 UNRESOLVED items in the taxonomy

- **U1: B1.1's crossing set contradicts itself.** The Master Map says **A1, A2, A3, A5, A6, A9**. The June 8 analysis (Apar panel and glossary) says **A1, A2, A3, A4, A5, A6**. The count is 6 either way, so the score is unaffected. The stored `a_imperatives` array needs a decision.
- **U2: Bs with no inflection stated.** These are B2.4, B6.2, B9.2, B9.3 and B10.3. Scoring them 0 on timing is the conservative reading.
- **U3: `inflection_quarter` holds one token, but his notes give ranges** ("FY27–28", "FY28–30"). **PROPOSAL:** store the range start plus the raw string in `rationale`. B1.2 needs a decision on whether it's FY27 (range) or FY26 (the crisis pull-forward).
- **U4: Does the Biosecure Act count as a crisis?** It sits outside his three named shocks but is described as a window "open NOW". My default is NO.
- **U5: One B per instrument.** `ab_mappings.b_bottleneck` holds a single B, but his portfolio table maps Syrma SGS to **B2.2 and B4.1** and Kaynes to B2.1 while describing it across B2.2 and B4.1. Pick a primary B, or allow many.
- **U6: Holdings that don't map cleanly to a B.**
  - **HDFC Bank** is labelled "B8.1 financial infrastructure" in the June 8 analysis, but B8.1 is **Cybersecurity** in the framework. B8.3 (Digital Payments & Financial Infrastructure) is the likely intended id.
  - **Premier Energies** is described only as "Solar generation → creates demand for B1.1", with no B id.
  - **Rolex Rings** is explicitly "not in the framework" and therefore off-framework under G1.
  - **GE Vernova T&D** is B1.1.
  - **Sai Life and Neuland** are B5.2.
  - **Genus Power** is B1.3.
  - **Solar Industries** is B4.2.
  - **Apar Industries** is B1.1.
- **U7: Crossing counts for B2.2 and B10.2 are probably understated** by the parent-only rule (see the cross-references in the table). Whoever approves `ab_mappings` has to decide those crossings. The count shouldn't be inflated here.

---

## 3. The ten-flag checklist

Source: `buffet-reflexivity.md`, Phase 3. The wording is **verbatim**. Every flag is a *red* flag, so **YES = bad**.

| # | Verbatim question | What justifies YES (evidence type) | Can it be computed? |
|---|---|---|---|
| 1 | Is the business model heavily complex, highly vulnerable to rapid technological obsolescence, or outside a standard circle of competence? | Segment/business description in the annual report or investor presentation (**filing text**); a technology-substitution **news event**. The weakest-evidenced flag: expect UNKNOWN often. | No |
| 2 | Is the company's ROE or ROCE consistently declining or below 15%? | **Filing line items** → computed ROE/ROCE series (≥3 FY) | **Yes. PROPOSAL:** compute and force it like flags 6 and 10 |
| 3 | Does the company require massive, continuous capital expenditures just to maintain its current competitive position (weak Owner Earnings)? | **Filing line items**: purchase of PPE vs D&A vs OCF (capex/OCF, FCF sign); a management **statement** of capex guidance | Partly (see U9) |
| 4 | Is management destroying value through expensive, dilutive acquisitions or buying back shares at historically overvalued multiples? | **Exchange announcement / news event**: acquisition, QIP, preferential allotment, buyback with its price; share-count change from paid-up capital; the multiple at the time (a **price/multiple fact**) | Partly (dilution from share count) |
| 5 | Is there a lack of candor in management communications (e.g., hiding poor performance behind adjusted EBITDA or changing key metrics)? | **Filing**: the auditor-qualification section of the Integrated Filing (it has a mandatory "Impact of Audit Qualifications" part); **news/announcement**: credit-rating watch, SEBI order or settlement, restatement; a **management statement** that changes KPIs | No |
| 6 | Has the stock price or valuation multiple (P/E, P/B, P/S) expanded dramatically faster than underlying metric growth (revenue, operating cash flow)? | **Price/multiple fact** + filing line items | Yes (in spec). **See U10** |
| 7 | Is the business model heavily dependent on the *continuation* of a high stock price or cheap capital access to fuel its growth or survival? | **Filing line items**: negative OCF funded by equity or debt raises; **announcements**: QIP, rights issue, refinancing | Partly |
| 8 | Are unit economics or operational margins deteriorating even as the company scales up or reports higher top-line revenues? | **Filing line items**: EBITDA margin trend against revenue growth; working-capital days trend | **Yes. PROPOSAL:** compute (e.g. revenue YoY > 0 and EBITDA margin down >100 bps over 4 quarters) |
| 9 | Is there a highly concentrated, hype-driven narrative dominating social media and institutional research that ignores execution risks? | **News / commentary** (tier-2/3 `source_items`, `mentions` density). No filing can evidence this. | No |
| 10 | Has the market's emotional tone shifted rapidly in the last 12–18 months (e.g., from completely ignored to a highly speculative market darling)? | **Price fact** (52-week range) | Yes (in spec) |

**How his notes actually aggregate the flags** (NOTES): count the YES flags, then band them: **0–3 Low Risk, 4–6 Moderate Risk, 7–10 High Speculative Risk**. All ten are counted together; the prompt doesn't split them into 1–5 and 6–10.

### UNRESOLVED items in the checklist

- **U8: He uses a fourth verdict, PARTIAL.** It appears throughout the June 8 analysis, which states: *"PARTIAL flags excluded from count."* The spec allows only YES/NO/UNKNOWN. Choose one:
  - (a) Add PARTIAL, scored like NO for counting. This matches his rule.
  - (b) Map PARTIAL to NO and lose the information.
- **U9: Flag 3's wording and his usage disagree.** The wording says "just to maintain". In practice he marked Solar and Sai Life **YES because *growth* capex made FCF negative**, and GE Vernova NO because it's asset-light. Decide whether the test is "maintenance capex" or "FCF-negative due to capex of any kind".
- **U10: Flag 6's definition differs across three places.**
  - His wording compares the multiple with **revenue / operating cash flow** growth.
  - The spec's MER uses **ΔEPS**.
  - In practice he also justified YES with **"PE ~90x vs sector median 24x"** (GE Vernova), which is a cross-sectional test, not a time-series one.
  - The spec's version is defensible, but it isn't his wording.
- **U11: Flag 10 is directional in his wording** ("ignored → darling"), but he applied it both ways: **Kaynes YES for a *downward* shift** (−45%). The spec's 52-week range ratio is direction-agnostic, which matches his usage. For reference, Solar's range (₹11,641 → ₹18,874 = 0.62) crosses the 0.60 threshold, consistent with his YES.
- **U12: Flags 1–5 vs 6–10.** The spec treats flags 1–5 as overrides that don't feed the score. His prompt folds all ten into one risk band. Confirm the spec's choice is intentional.

---

## 4. The fair-multiple table

### 4.1 What his notes contain

**His notes have no sector table.** They contain only these scattered fair-value judgements:

| Company (sector) | Fair multiple in his notes | Basis |
|---|---|---|
| GE Vernova T&D (power equipment) | "fair PE **25–30x** for a top-quality industrial" | P/E |
| Solar Industries (explosives/defence) | "fair PE **30–35x** for a best-in-class industrial on **FY27E** PAT" | forward P/E |
| HDFC Bank (private bank) | "Fair value ~₹993 at PE **20x**"; buy rule "below PE **18x**" | P/E |
| Apar Industries (conductors) | "PE **~26x FY27E** … already have the margin of safety" | forward P/E (implies fair ≥26x) |
| Rolex Rings (auto components) | "PE ~**20x** … not expensive" | adjusted P/E |
| Glossary | Indian cost of capital "roughly **10–12%**" | anchor |

### 4.2 Three problems to know before using these numbers

- **U13: Forward vs trailing earnings.** His two cleanest MoS calls use **FY27E** (forecast) earnings. A forecast can't be a `SourcedNumber`, because no filing contains it. The system *must* use trailing reported owner earnings, so its MoS will differ from his notes by design. **PROPOSAL:** set `normalised_owner_earnings` = mean of the last 3 reported FY.
- **U14: His MoS numbers don't match his own formula on the negative side.**
  - Positive case: HDFC with IV ₹993 and price ₹739 gives (993−739)/993 = 25.6%, which matches his "≈25%".
  - Negative case: GE Vernova at a "fair PE 25–30x" against an actual ~90x gives (IV−P)/IV ≈ **−200%**. His note says "~50%", which is closer to (IV−P)/P.
  - This doesn't change the score, since any negative value scores 0. The dashboard magnitudes will just never match his notes.
- **U15: Banks break the owner-earnings method.** For HDFC Bank, D&A and capex are immaterial, "net debt/EBITDA" and "OCF/PAT" mean nothing, and ROCE isn't used. The bank XBRL taxonomy also carries different line items. **PROPOSAL:** for `sector = BANK`, set cash conversion, balance sheet and ROCE to `null` (not 0), and value on P/E × PAT (or P/B). Otherwise G2 will misclassify the portfolio's anchor holding.

### 4.3 PROPOSED table (my construction, not his notes)

**Anchors:**
- A no-growth business at a 10–12% cost of equity is worth ~8–10x owner earnings.
- The Nifty 50 trades at **19.74x** (18 Sep 2026) against a **10-year average of 23.31x** and a range of 17.15x (Mar 2020) to 42x (Feb 2021) ([source](https://craytheon.com/charts/nifty_pe_ratio_pb_value_dividend_yield_chart.php)). Nifty moved to consolidated EPS in 2021, so long-run averages across that break aren't strictly comparable.
- Where his notes give a number, I stay inside his range.

Multiples apply to owner earnings. With the spec's proxy (maintenance capex = 3-yr median D&A), owner earnings ≈ PAT, so P/E intuition carries over.

| `sector` key | Fair multiple | One-line reasoning |
|---|---:|---|
| `DEFAULT` | 20 | ≈ Nifty's long-run level, below its 10-yr average: a neutral, slightly conservative anchor |
| `CAPITAL_GOODS_POWER_EQUIPMENT` | 28 | Middle of his 25–30x for top-quality T&D equipment |
| `DEFENCE_MANUFACTURING` | 30 | Low end of his 30–35x for Solar; kept at the low end because the demand is order-book/government-lumpy |
| `CABLES_CONDUCTORS` | 24 | Just below his implied ≥26x for Apar (which he rated at a discount); commodity-linked input costs, thin EBITDA (~9%) |
| `EMS_ELECTRONICS` | 25 | Asset-light but low margin and working-capital-heavy (Kaynes 116–179 days); quality lower than capital goods |
| `SMART_METERING` | 22 | Concession/AMISP annuity-like revenue, but DISCOM receivables risk |
| `PHARMA_CDMO` | 30 | Sticky multi-year client lock-in (his "11-yr tenure" argument); his notes give no number |
| `PHARMA_GENERICS_API` | 22 | US-FDA and pricing-erosion risk; lower stickiness than CDMO |
| `PRIVATE_BANK` | 18 on PAT | His own buy threshold (below 18x); his "fair" 20x includes re-rating optimism. See U15 |
| `AUTO_COMPONENTS` | 18 | Cyclical, price-taker ("weak moat" in his notes); just below his "~20x not expensive" |
| `SPECIALTY_CHEMICALS` | 24 | Mid-cycle Indian specialty-chem level; high variance |
| `IT_SERVICES` | 22 | Mature, cash-generative, slowing growth |
| `LOGISTICS_PORTS` | 20 | Infrastructure-like, capital-heavy |
| `EXCHANGES_MARKET_INFRA` | 30 | High-ROE, asset-light near-monopolies (BSE, CAMS, CDSL) |
| `REGULATED_UTILITY_TRANSMISSION` | 12 | Regulated-ROE assets (Power Grid, NTPC): bond-like, near the no-growth anchor |
| `FERTILISERS` | 12 | Subsidy-regulated, low growth |
| `EPC_WATER_INFRA` | 15 | Execution-heavy, working-capital-heavy, cyclical order flow |
| `COMMODITY_METALS` | 8 | Cyclical; the no-growth anchor. Shouldn't appear in this universe |

**U16:** his notes vary the multiple **by quality within the same sector** (25–30x for GE Vernova against 30–35x for Solar, both "industrial"), and a sector-only table can't express that. **PROPOSAL:** accept the crudeness in v1, which fits the spec's "dumb, reproducible" intent. Don't add a quality modifier: it would couple the MoS component to the ROCE component.

---

## 5. Indian fundamentals: where the numbers come from

### 5.1 Headline finding

**There is a free, official, structured source, and it is better suited to the echo check than any paid API.** Every NSE-listed company files its quarterly results to the exchange in **XBRL**. NSE exposes those files at **stable, unauthenticated URLs**, and the half-yearly and annual files carry the **balance sheet and cash flow statement**, not just a P&L summary. I checked this live today against Apar Industries.

It isn't EDGAR `companyfacts`: there's no pre-aggregated per-company JSON. You fetch one filing at a time and parse the XML. But the underlying data is the same kind of thing: tagged facts filed by the company.

### 5.2 How I verified it (20 Sep 2026)

**Two NSE JSON endpoints.** Their response fields and URLs are quoted verbatim below.

1. **Old-system results (up to Q3 FY25, Dec 2024):**
   `https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly&symbol=APARINDS`
   - Fields: `audited, bank, broadCastDate, companyName, consolidated, … indAs, … period, … toDate, xbrl`.
   - `xbrl` is a direct file URL, e.g. `https://nsearchives.nseindia.com/corporate/xbrl/INDAS_117941_1363971_29012025110018.xml`.
   - For Apar, XBRL links go back to at least Sep 2022 (standalone and consolidated). Earlier half-year rows (2005–2010) have `xbrl: "-"`, i.e. no XBRL.
2. **Integrated Filing (from Q4 FY25, i.e. Mar 2025 onwards):**
   `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=APARINDS`
   - Fields: `attFileSize, audited, broadcast_Date, cmName, consolidated, creation_Date, diff, ixbrl, ixbrlFileSize, pdf_attach, qe_Date, revised_Date, revision_Remark, seq_Id, smName, symbol, type, type_Sub, xbrl, xbrlFileSize`.
   - Filter on `type == "Integrated Filing- Financials"` (the endpoint also returns "Governance" filings).
   - Example: `…/corporate/xbrl/INTEGRATED_FILING_INDAS_1675395_28052026085114_WEB.xml` (FY26 audited, consolidated, 81.6 KB).
   - **Important:** the old endpoint *stops* at Dec 2024. A pipeline built only on it silently loses every result from Mar 2025 on.

**What the files contain (verified by reading the XML):**

| Filing period | Contains | Example tags (local names) |
|---|---|---|
| Every quarter | Full P&L, EPS, share capital | `RevenueFromOperations`, `OtherIncome`, `FinanceCosts`, `DepreciationDepletionAndAmortisationExpense`, `ProfitBeforeTax`, `TaxExpense`, `ProfitLossForPeriod`, `ProfitOrLossAttributableToOwnersOfParent`, `BasicEarningsLossPerShare…`, `PaidUpValueOfEquityShareCapital`, `FaceValueOfEquityShareCapital`, plus segment revenue/assets |
| **Sep (H1) and Mar (FY)** | + Statement of assets & liabilities, + cash flow statement | `TradeReceivablesCurrent`, `Inventories`, `TradePayablesCurrent`, `BorrowingsCurrent`, `BorrowingsNoncurrent`, `CashAndCashEquivalents`, `EquityShareCapital`, `OtherEquity`, `EquityAttributableToOwnersOfParent`, `CashFlowsFromUsedInOperatingActivities`, `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities` |

Verified in the Sep-2024 and Mar-2024 old-system files and the Mar-2026 Integrated Filing. The Q3 (Dec) file had the P&L only.

**Echo-check fit, a verbatim fact line from the FY26 file:**

```xml
<in-capmkt:RevenueFromOperations contextRef="FourD" decimals="-5" unitRef="INR">229021200000</in-capmkt:RevenueFromOperations>
```

That is ₹22,902.12 Cr, matching the "Record FY26 revenue ₹22,902 Cr" in his June 8 notes. One fact line is ~120 bytes, so **store the raw fact line(s) as the `source_items.excerpt`** (well under 2 KB) and discard the file after parsing. No document is stored, and the echo check runs against text the company itself filed.

### 5.3 Coverage map against the Buffett-score inputs

| Needed | Source in XBRL | Frequency | Note |
|---|---|---|---|
| Revenue, PAT, D&A, finance costs, other income | Direct tags | Quarterly | |
| EBITDA / EBITDA margin | Computed: PBT + finance costs + D&A (− other income, per your definition) | Quarterly | Define once; no EBITDA tag exists |
| Shares outstanding | `PaidUpValueOfEquityShareCapital ÷ FaceValueOfEquityShareCapital` | Quarterly | Treasury shares and partly-paid capital are edge cases |
| Book value | `EquityAttributableToOwnersOfParent` (or `EquityShareCapital + OtherEquity`) | Half-yearly | |
| Net debt | `BorrowingsCurrent + BorrowingsNoncurrent − CashAndCashEquivalents` | Half-yearly | Decide whether current investments and bank balances count as cash |
| OCF, capex | Cash-flow tags | Half-yearly, **cumulative YTD** | FY value comes from the March file; H2 = FY − H1 |
| Working-capital days | Receivables, inventories, payables vs revenue | Half-yearly | Quarterly WC days are **not** available |
| ROE, ROCE | Computed (ROCE = (PBT + finance costs) ÷ (equity + borrowings)) | Annual | |
| **Order book** | **Not in XBRL** | — | Comes from investor presentations/press releases (PDF). Store only the extracted sentence as a tier-1 excerpt. **UNRESOLVED** extraction path |
| Maintenance capex | **Not disclosed anywhere** | — | Spec's D&A proxy stands |
| Market cap history (retained-earnings test) | Your price feed × shares | — | Not a filing item |

### 5.4 Implementation notes

**Parsing and storage**
- **Parse with the standard library** (`xml.etree.ElementTree`) by *local name*. The namespace has changed at least once: `http://www.bseindia.com/xbrl/fin/2020-03-31/in-bse-fin` in 2024 files, `http://www.sebi.gov.in/xbrl/IntegratedFinance_IndAS/2026-01-31/in-capmkt/in-capmkt-ent` in 2026 files. No XBRL library is needed.
- **Resolve contexts by their `<period>` start/end dates, not their ids.** Ids like `OneD` and `FourD` are just labels. Each file also carries the prior-year comparatives, so 2 filings/year back-fill more history than they appear to.
- **Values are in rupees, rounded** (`decimals="-5"` = to the lakh). The echo normaliser must handle rupees → crore (÷1e7).
- **Pick consolidated where it exists** and store the choice. Standalone and consolidated are separate files.
- **Banks and NBFCs use different taxonomies** (the NSE XBRL page lists Ind AS, Banks, NBFC and Insurance separately). HDFC Bank needs its own tag map. See U15.
- **Revisions exist** (`revised_Date`, `revision_Remark`). Treat a revised filing as a new `source_item` that supersedes the old one, which is what the append-only design wants anyway.

**Volume and rate**
- ~40 instruments × 4 filings/yr × up to 2 files ≈ 320 files/yr, each 17–215 KB, parsed in memory.
- The 5-year back-fill is ~40 × 20 quarters ≈ 800–1,600 fetches, run once.
- Only extracted facts are persisted (the spec's ~0.5 MB/yr estimate for `fundamentals` holds).

**Retrieval requirements (UNRESOLVED)**
- **NSE's JSON API needs cookie priming and browser-like headers**, the same dance the spec already describes for bhavcopy. The `nsearchives.nseindia.com` file URLs are static.
- My fetches ran from a cloud environment, **not from your GCP e2-micro IP**. **UNRESOLVED:** run a smoke test from the box before committing.
- Vendoring the session/header function from `NseIndiaApi` ([docs](https://bennythadikaran.github.io/NseIndiaApi/api.html)) is the obvious 2–3-function vendor. **Check its licence before copying.**
- **Fallback:** BSE hosts the same filings. I didn't find a documented public URL pattern for BSE XBRL instance files ([BSE XBRL page](https://www.bseindia.com/static/about/xbrl_info.aspx) describes only the filing utility). **UNRESOLVED.**

**Licensing (UNRESOLVED, not verified)**
- The filings are statutory public disclosures, and the use is personal, non-display and single-user, matching the spec's posture.
- I did **not** read NSE's website terms of use for automated access. Read them before relying on this.

### 5.5 All options, with verdicts

| Option | Cost | What it covers for NSE companies | Licence | Verdict |
|---|---|---|---|---|
| **NSE results / Integrated Filing XBRL** ([XBRL info](https://www.nseindia.com/static/companies-listing/xbrl-information), [results page](https://www.nseindia.com/companies-listing/corporate-filings-financial-results), [integrated filing page](https://www.nseindia.com/companies-listing/corporate-integrated-filing)) | ₹0 | Quarterly P&L; half-yearly BS + CF; all listed companies; XBRL from ≈FY22 onward (verified back to Sep 2022 for one company) | Public statutory filings; site ToS unread | **Viable with caveats.** The caveats are cloud-IP access (untested from GCP), two endpoints, no order book, quarterly WC impossible, and banks need a separate map. **Recommended primary.** |
| NSE `results-comparision` endpoint ([NseIndiaApi](https://bennythadikaran.github.io/NseIndiaApi/api.html)) | ₹0 | Revenue, net profit, EPS only; ~5 quarters | Same | **Not viable** as primary (summary only). Fine as a cross-check |
| Anything EDGAR-`companyfacts`-like (SEBI, MCA, RBI, data.gov.in) | — | Nothing found that publishes per-company structured financials as an API. SEBI's Integrated Filing framework ([SEBI circular](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/SEBI%20Circular_0.pdf), [FAQ summary](https://mmjc.in/frequently-asked-questions-on-integrated-filing-financials-for-quarter-ended-december-31-2024/)) routes filings to the exchanges, which makes the exchange XBRL the closest equivalent | — | **Not available.** The honest answer: exchange XBRL *is* India's nearest equivalent |
| MCA21 AOC-4 XBRL ([MCA XBRL](https://www.mca.gov.in/MinistryV2/xbrl.html)) | Paid per-document viewing on the portal; no public API found | Full annual statements with notes (including a more complete cash flow) | Government portal | **Not viable** (manual, per-document, captcha portal, annual only, filed months after year-end) |
| EODHD Fundamentals Data Feed ([pricing](https://eodhd.com/pricing), [fundamentals](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)) | **US$59.99/mo** (~₹5,400 at ₹90/$) or $599.90/yr | IS/BS/CF quarterly + annual; "non-US symbols from 2000". Their fundamentals docs give **no explicit India/NSE coverage statement** | Personal-use plan | **Viable with caveats, but a poor fit.** Over the ₹2–3k/month tolerance on its own. Returns vendor-normalised numbers, so the echo check would verify against the *vendor's JSON*, not the company's filing. That weakens D3 |
| Financial Modeling Prep ([pricing](https://site.financialmodelingprep.com/developer/docs/pricing)) | Global statements only on **Ultimate, $99/mo**; Premium ($49) is US/UK/Canada only | Global coverage claimed; India depth unverified | Personal plan | **Not viable** at this budget |
| Indian aggregators (e.g. [indianapi.in](https://indianapi.in/indian-stock-market)) and Apify scrapers of Screener/Tickertape ([example](https://apify.com/scrapyx/screener-in-stocks-scraper/api)) | Varies; pricing not published on the page I checked | Varies | Scrapers resell data from sites the spec already ruled out | **Not viable.** Provenance is laundered, which fails the "traceable to a filing" rule |
| Screener.in / Tickertape / Trendlyne / yfinance / Financial Datasets | — | — | — | Already ruled out in spec. Nothing I found changes that |

**Bottom line on 5:** the paid APIs aren't the honest answer here. The official XBRL route is free, covers every line item except order book and maintenance capex, and has *better* provenance for the echo check than any vendor. The real open risk is **whether NSE's JSON API answers from the GCP e2-micro's IP**. If it doesn't, the fallback isn't a paid vendor. It's a small fetch run from somewhere that can reach NSE, with the same XBRL and the same parser.

---

## 6. Consolidated list of UNRESOLVED items

| # | Decision needed | My default if forced |
|---|---|---|
| U1 | B1.1 crossing set (A9 vs A4) | Master Map: A1, A2, A3, A5, A6, A9 |
| U2 | Bs with no inflection | Timing score 0 |
| U3 | Ranges vs single `inflection_quarter` | Range start; raw text in `rationale` |
| U4 | Biosecure Act as a "crisis"? | No |
| U5 | One B per instrument | Primary B only |
| U6 | HDFC Bank's B id; Premier Energies' B | B8.3; Premier = off-framework until mapped |
| U7 | B2.2 / B10.2 crossing counts | Parent-only (1) until a human approves |
| U8 | PARTIAL verdict | Add PARTIAL; counts as NO |
| U9 | Flag 3: maintenance vs growth capex | His usage (FCF-negative from any capex) |
| U10 | Flag 6 definition | Keep spec MER; record his wording |
| U11 | Flag 10 direction | Direction-agnostic (as spec) |
| U12 | Flags 1–5 counted in the risk band? | Spec's choice, confirmed by a human |
| U13 | Forward vs trailing earnings for IV | Trailing 3-yr mean |
| U14 | His negative-MoS magnitudes | Ignore; formula per spec |
| U15 | Banks in the Buffett score | Null the inapplicable components; P/E on PAT |
| U16 | Quality within sector | Accept crudeness in v1 |
| — | NSE access from the GCP IP; NSE ToS; BSE fallback URL; order-book extraction | Smoke-test before Phase 2 |
