# Transaction Cost Reference — Groww / CoinSwitch / INDmoney

*Verified 6 September 2026. Every figure carries its source and effective date.*
*Companion to `investments-module-technical.md` §12.5. This is the input to `services/costmodel`.*

---

## 0. The three things that matter most

**1. Groww delivery brokerage is NOT zero.** It is **the lower of ₹20 or 0.1% of trade value, minimum ₹5**. Zerodha's ₹0 delivery does not transfer. On a ₹13,422 buy that is ₹13.42 of brokerage where the spec previously assumed ₹0. ⚠ See §A.1 — sources conflict between 0.1% and 0.05%, and there is a one-line test to settle it from your own contract note.

**2. Groww's DP charge is ₹20 + GST, not ₹15.34.** Groww adds ₹16.50 on top of CDSL's ₹3.50, versus Zerodha's ₹9.50. That is **₹23.60 per scrip per sell** — the single largest fixed cost in the model, and it is the reason small positions are expensive.

**3. At your ticket size, costs are material.** A ₹13,422 buy and a ₹15,000 sell costs **₹88.64 round trip — a 0.66% break-even move**, and 5.6% of a ₹1,578 gain. On a ₹5,000 position the sell leg alone is 0.69% of turnover. The cost model must be in place before the first proposal, or the paper book will systematically overstate returns.

---

## A. Indian equity — DELIVERY, on Groww

### A.1 Brokerage — ⚠ sources conflict

**Use: `min(₹20, 0.1% × turnover)`, floored at ₹5.** Charged on **both buy and sell**.

| Source | Claim | Weight |
|---|---|---|
| [Groww help centre](https://groww.in/help/stocks,-f&o,-ipo-&-mtf/sx-demat-account/how-much-does-groww-charge-for-stocks-1) — *"the lower of ₹20 or 0.1% of your trade value. The minimum charge is ₹5."* | **0.1%** | Official |
| [Groww pricing page](https://groww.in/pricing) — *"₹20 or 0.1% per executed order (whichever is lower, minimum ₹5)"* | **0.1%** | Official |
| [comparesharebrokers](https://comparesharebrokers.com/brokerage-charges/groww), "Verified April 2026" | 0.05% | Aggregator |
| [stockcalc.in](https://stockcalc.in/calculator/brokerage/groww) | 0.05% | Aggregator, and its worked example is internally inconsistent — it shows STT of ₹110 on ₹2.10 lakh, which is 0.05%, not the 0.1% delivery rate. Treat as unreliable. |
| Older reviews (2022–24) | ₹0 | Stale. Groww ended zero-delivery brokerage in 2023. |

**Two of Groww's own pages say 0.1%, so that is what to model** — and it is the conservative choice, since overestimating cost is the safe direction for a paper book.

**The test that settles it in ten seconds:** the ₹20 cap binds at ₹20,000 turnover if the rate is 0.1%, and at ₹40,000 if it is 0.05%. Pull any Groww contract note for a trade between ₹20,000 and ₹40,000. Brokerage of exactly ₹20 → 0.1%. Brokerage below ₹20 → 0.05%.

A related datapoint that supports 0.1% being current: Groww raised its **minimum** brokerage from ₹2 to ₹5 effective **21 June 2025**, which matches the "minimum ₹5" wording on both official pages — so those pages are being maintained.

> **Type: percentage of turnover, capped and floored.** Not flat, not per scrip.

### A.2 STT — Securities Transaction Tax

**0.1% on buy AND 0.1% on sell** for equity delivery ([Zerodha STT reference](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated); confirmed on [Groww pricing](https://groww.in/pricing)).

⚠ **Recent change, but not to you.** STT on F&O changed on **1 April 2026** under Budget 2026–27. **Equity delivery and intraday rates are unchanged.** Budget 2026 also raised STT on commodity futures from 0.02% to 0.05%.

Delivery is the only equity mode taxed on both sides — intraday is sell-side only at 0.025%.

> **Type: percentage of turnover, both legs.** No cap, no floor.

### A.3 Exchange transaction charges

| Exchange | Total | Effective |
|---|---|---|
| **NSE** | **0.00307%** (₹307 per crore, each side) | ₹307/crore total has held since 1 Oct 2024 |
| **BSE** | **0.00375%** (₹375 per crore, each side) | 1 Dec 2022 |

**NSE's internal split changed on 1 March 2026** and this will show on your contract note. Circular **NSE/FA/73061** dated 27 Feb 2026 re-split the charge to **₹306.99/crore transaction charge + ₹0.01/crore IPFT**, replacing the previous ₹297 + ₹10. NSE stated the change *"ensures no impact in the overall outflow"* because the IPFT corpus *"has been replenished and is currently adequate"* ([circular](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf)).

⚠ **Groww's pricing page still shows the old split** — 0.00297% transaction + 0.0001% IPFT. Same ₹307 total, so your cost model is unaffected, but if you parse a contract note line-by-line, expect the two line items to have swapped magnitudes since March.

The move to uniform (non-slab) rates came from a SEBI directive, effective 1 Oct 2024 ([Business Standard](https://www.business-standard.com/amp/markets/stock-market-news/nse-and-bse-revise-their-transaction-fees-to-comply-with-sebi-circular-124092701207_1.html)).

BSE's ₹375/crore flat rate was set by notice 20221109-7 dated 9 Nov 2022, effective 1 Dec 2022, for Group A, B and non-exclusive scrips.

> **Type: percentage of turnover, both legs.** Model NSE and BSE separately — the 0.00068 percentage-point gap is real but tiny.

### A.4 SEBI turnover fee

**₹10 per crore = 0.0001% of turnover**, both legs. Set by SEBI's revised turnover fee schedule effective **3 April 2019** and unchanged since ([CSE notice](https://www.cse-india.com/upload/cse_notice/REVISED_SEBI_TURNOVER_FEES.htm)).

> **Type: percentage of turnover, both legs.** Rounds to ₹0.01–0.03 at your ticket sizes — include it anyway so contract notes reconcile to the paisa.

### A.5 Stamp duty

**0.015% (₹1,500 per crore), BUY SIDE ONLY.** Confirmed.

Uniform national rates under the Indian Stamp Act amendments effective **1 July 2020** replaced the old state-by-state regime. Every category is buy-side only ([Zerodha, Uniform Stamp Duty](https://zerodha.com/z-connect/general/uniform-stamp-duty)):

| Instrument | Rate | Side |
|---|---|---|
| **Equity delivery** | **0.015%** (₹1,500/crore) | Buy |
| Equity intraday | 0.003% (₹300/crore) | Buy |
| Futures | 0.002% | Buy |
| Options | 0.003% | Buy |
| **Mutual funds** | **0.005%** (₹500/crore) | Buy |
| Bonds/debentures | 0.0001% | Buy |

⚠ Several third-party charge sheets list 0.003% for equity — that is the **intraday** rate. Delivery is 0.015%, five times higher.

> **Type: percentage of turnover, buy leg only.**

### A.6 GST

**18%, applied to: brokerage + exchange transaction charges + SEBI turnover fee + DP charges.**

**Not applied to: STT or stamp duty.** Those are taxes, not services — you do not pay tax on tax.

```
gst = 0.18 × (brokerage + exchange_txn + sebi_fee + dp_charge)
```

Zerodha states the base as *"brokerage + SEBI charges + transaction charges"* and separately bundles ₹2.34 of GST into its ₹15.34 DP charge — ₹2.34 ÷ 0.18 = ₹13.00 = ₹3.50 + ₹9.50, confirming **GST applies to the full DP charge including the depository's own portion**, not just the broker's markup. Groww's help page says only *"GST is added on top of these charges,"* so model it the same way and verify against a contract note.

> **Type: percentage, but of a computed fee base — not of turnover.**

### A.7 DP charges — the expensive one

**Groww uses CDSL.** Official: *"Groww demat accounts are in CDSL (Central Depository Services Limited)"* ([Groww help](https://groww.in/help/my-account/searchable/is-my-groww-an-nsdl-or-cdsl-account)).

Charged **on sell only, per scrip (per ISIN) per day**, regardless of quantity.

| Sale value | CDSL | Groww | Subtotal | **+ 18% GST** |
|---|---:|---:|---:|---:|
| ≥ ₹100, male first holder | ₹3.50 | ₹16.50 | ₹20.00 | **₹23.60** |
| ≥ ₹100, female first holder | ₹3.25 | ₹16.50 | ₹19.75 | **₹23.31** |
| < ₹100, male | ₹3.50 | ₹0 | ₹3.50 | **₹4.13** |
| < ₹100, female | ₹3.25 | ₹0 | ₹3.25 | **₹3.84** |

Sources: [Groww DP charges help page](https://groww.in/help/stocks,-f&o,-ipo-&-mtf/sx-margin/what-are-dp-charges-depository-participant-charges-1) and [Groww pricing](https://groww.in/pricing). The CDSL side comes from CDSL's own uniform tariff — **₹3.50 flat per debit transaction with no value slabs, and a ₹0.25 concession for female sole/first holders and for mutual fund and bond debits** — effective **1 October 2024** following SEBI's 'True to Label' circular of July 2024 ([CDSL media release, 26 Sep 2024](https://www.cdslindia.com/Downloads/About/Media/Final_26%20Sep%202024%20Media%20Release_Tariffrevised.pdf)).

**Groww's ₹16.50 markup is the single biggest modelling difference versus Zerodha's ₹9.50.** At ₹23.60 per sell, exiting a ₹5,000 position costs 0.47% in DP charge alone.

> **Type: flat, per scrip (ISIN), per sell day.** Selling three different stocks the same day = three charges. Selling one stock in four tranches the same day = one charge. **This creates a real incentive to consolidate exits, which the decision engine should surface.**

### A.8 Other charges that appear on a real Groww contract note or ledger

Things not in your original list:

| Charge | Amount | Type | Notes |
|---|---|---|---|
| **IPFT** (Investor Protection Fund Trust) | Included in the ₹307/crore NSE total | % of turnover | Shown as a **separate line item** on contract notes. Since 1 Mar 2026 it is ₹0.01/crore on NSE — effectively nil, but the line persists. |
| **Demat AMC** | **₹0** | — | Groww official: *"You will not be charged AMC even if you don't trade for a long time or have no holdings"* ([Groww help](https://groww.in/help/stocks,-f&o,-ipo-&-mtf/sx-pricing/what-are-account-maintainance-charges)). Genuinely zero, unlike Angel One's ₹60+GST/quarter. |
| **Account opening** | ₹0 | — | |
| **Auto square-off** | ₹50 per position | Flat, per position | Intraday only — not applicable to delivery, but will appear if a position is ever left open. |
| **Pledge creation** | ₹20 + ₹12 CDSL | Flat, per ISIN | Only if you ever use MTF. |
| **Demat / remat of physical certs** | ₹150 per certificate + courier | Flat | Not applicable. |
| **KYC modification** | ₹50 | Flat | One-off. |
| **Payment gateway / fund transfer** | Not published | — | ⚠ Some brokers charge for net-banking transfers and not for UPI. Groww publishes nothing. Check a ledger entry. |
| **Call & trade** | Not published | — | ⚠ Not applicable to an app-only workflow, but confirm if you ever phone in an order. |

Third-party charge list dates from 17 Oct 2023 ([Chittorgarh](https://www.chittorgarh.com/brokerage_charges/groww/173/)) — treat the ancillary fees as indicative and verify anything you actually incur.

### A.9 The complete formula

```python
from decimal import Decimal as D

NSE_TXN   = D('0.0000307')   # 0.00307%  — incl. IPFT
BSE_TXN   = D('0.0000375')   # 0.00375%
STT       = D('0.001')       # 0.1% both sides, delivery
SEBI_FEE  = D('0.000001')    # ₹10/crore
STAMP     = D('0.00015')     # 0.015%, buy only
GST       = D('0.18')
CDSL_DEBIT      = D('3.50')  # ₹3.25 if female first holder
GROWW_DP_MARKUP = D('16.50') # ₹0 if sale value < ₹100

def charges(turnover, side, exchange='NSE', female=False):
    t = D(str(turnover))

    brokerage = min(D('20'), t * D('0.001'))          # ⚠ verify 0.1% vs 0.05%
    if brokerage < D('5'):
        brokerage = min(D('5'), t * D('0.025'))        # SEBI 2.5% cap floor

    stt   = t * STT                                    # BOTH sides for delivery
    txn   = t * (NSE_TXN if exchange == 'NSE' else BSE_TXN)
    sebi  = t * SEBI_FEE
    stamp = t * STAMP if side == 'BUY' else D('0')     # BUY only

    dp = D('0')
    if side == 'SELL':                                 # per ISIN per day
        dp = (D('3.25') if female else CDSL_DEBIT)
        if t >= 100:
            dp += GROWW_DP_MARKUP

    gst = (brokerage + txn + sebi + dp) * GST          # NOT on STT or stamp
    return brokerage + stt + txn + sebi + stamp + dp + gst
```

**Worked outputs** (male first holder, NSE, 0.1% brokerage):

| Trade | Brok | STT | Txn | SEBI | Stamp | DP | GST | **Total** | **% of turnover** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BUY ₹5,000 | 5.00 | 5.00 | 0.15 | 0.01 | 0.75 | — | 0.93 | **₹11.84** | 0.237% |
| SELL ₹5,000 | 5.00 | 5.00 | 0.15 | 0.01 | — | 20.00 | 4.53 | **₹34.69** | **0.694%** |
| BUY ₹13,422 | 13.42 | 13.42 | 0.41 | 0.01 | 2.01 | — | 2.49 | **₹31.78** | 0.237% |
| SELL ₹15,000 | 15.00 | 15.00 | 0.46 | 0.02 | — | 20.00 | 6.39 | **₹56.86** | 0.379% |
| BUY ₹30,000 | 20.00 | 30.00 | 0.92 | 0.03 | 4.50 | — | 3.77 | **₹59.22** | 0.197% |
| SELL ₹30,000 | 20.00 | 30.00 | 0.92 | 0.03 | — | 20.00 | 7.37 | **₹78.32** | 0.261% |

**Round trip on the ₹13,422 → ₹15,000 example: ₹88.64. Break-even move: 0.660%. Cost as a share of the ₹1,578 gain: 5.6%.**

Note the shape: cost as a percentage of turnover **falls** as ticket size rises, because the ₹20 brokerage cap and the ₹23.60 DP charge are fixed. Below roughly ₹8,000 the sell leg alone exceeds 0.5%. This argues directly for fewer, larger positions — which is what §6 of the spec already says for other reasons, and now has a cost number behind it.

---

## B. Mutual funds — direct plans on Groww

### B.1 Stamp duty on purchase

**0.005% of the invested amount, on purchase and switch-in only.** Effective **1 July 2020**. Groww displays it on the fund page as *"0.005% (from July 1st, 2020)"*.

Deducted from the amount invested *before* units are allotted, so you receive units worth (investment − stamp duty). Applies equally to lump sum, each SIP instalment, and switch-ins. **No stamp duty on redemption or switch-out.**

> **Type: percentage of purchase value, buy side only.**

### B.2 Brokerage / commission

**₹0.** Groww charges zero commission on direct mutual funds. Direct plans carry no distributor trail by definition — that is the whole point of the direct plan, and it is already inside the NAV via the lower TER.

### B.3 Exit loads — verified from the AMC

Both from HDFC AMC's own scheme pages:

| Fund | Exit load | TER (direct) |
|---|---|---|
| [**HDFC Flexi Cap Fund — Direct Plan**](https://www.hdfcfund.com/explore/mutual-funds/hdfc-flexi-cap-fund/direct) | **1.00% if redeemed or switched out within 1 year** from date of allotment. Nil after 1 year. | 0.77% |
| [**HDFC Mid Cap Fund — Direct Plan**](https://www.hdfcfund.com/explore/mutual-funds/hdfc-mid-cap-fund/direct) | **1.00% if redeemed or switched out within 1 year** from date of allotment. Nil after 1 year. *"No Entry/Exit Load shall be levied on bonus units and units allotted on dividend reinvestment."* | 0.74% |

⚠ **Naming change:** the fund you know as *HDFC Mid-Cap Opportunities Fund* is now officially **HDFC Mid Cap Fund**, following SEBI's scheme-naming standardisation. Same scheme, same ISIN (INF179K01XQ0). Your instrument master should carry both names as aliases or the AMFI scheme-code lookup will look like it broke.

Two modelling points:

- **Exit load is applied per allotment lot, FIFO.** A SIP redeemed 14 months in still incurs 1% on every instalment allotted within the trailing 12 months. Your `taxrules` FIFO lot matcher already does this work — reuse it for exit load rather than writing a second matcher.
- **Exit load is deducted from redemption proceeds and credited back to the scheme.** GST on exit load is borne by the scheme, not charged to you. So the investor-side cost is a clean 1% of the redemption value of the affected lots.

> **Type: percentage of redemption value, per lot, conditional on holding period.**

### B.4 Does demat-mode holding change anything?

**Yes — and it costs you money for no benefit.**

Groww lets you hold mutual fund units in either **SOA** (statement of account, the registrar's book) or **demat** mode. Stamp duty, exit load and TER are identical either way. But units held in demat are debited from your CDSL account on redemption, so **DP charges apply** — CDSL's ₹3.50 less the ₹0.25 mutual fund and bond concession = ₹3.25, plus whatever Groww adds.

⚠ **Unverified:** whether Groww levies its ₹16.50 markup on mutual fund debits or only on equity. Groww's DP help page discusses share sales only. If it does, redeeming a demat-held fund costs ₹23.31 versus ₹0 in SOA mode.

**Recommendation: hold mutual funds in SOA mode.** There is no upside to demat for a fund you buy and hold, and the downside is a per-redemption charge. If your existing holdings are already in demat, the model must include the DP charge on any MF redemption — check one redemption contract note to settle whether the ₹16.50 applies.

---

## C. Crypto — CoinSwitch

### C.1 The 1% TDS — when it actually applies

Under **Section 194S**, effective **1 July 2022**:

| Transaction | TDS? | On what |
|---|---|---|
| **Buy crypto with INR** | **No** | You are the buyer; nothing is deducted from you |
| **Sell crypto for INR** | **Yes, 1%** | Deducted from your sale consideration |
| **Crypto-to-crypto swap** | **Yes, on both legs** | Each party is transferring a VDA, so each is a transferor |
| **Transfer to your own wallet** | No | Not a transfer of beneficial ownership |

**The 1% is deducted from the seller's proceeds**, and on an Indian exchange **the exchange deducts and deposits it** ([Quicko](https://learn.quicko.com/tds-crypto-nft-vda-section-194s)). Koinly confirms CoinSwitch *"automatically deduct[s]"* it.

**Thresholds, cumulative per financial year:**
- **₹50,000** — for "specified persons": individuals/HUFs with no business income, or with business turnover under ₹1 crore / professional receipts under ₹50 lakh. **This is almost certainly you.**
- **₹10,000** — everyone else.

Below the threshold, no TDS. Above it, 1% on the full consideration.

**TDS is not a cost — it is prepaid tax.** It is creditable against your final liability and refundable if excess. Model it as a **cash-flow timing item, not an expense**, or you will double-count against the 30% s.115BBH tax. This distinction matters: the *real* crypto cost is the flat 30% with **no loss set-off and no carry-forward**, which the spec already flags as the reason crypto is excluded from proposals in v1.

> **Type: percentage of consideration, sell/transfer side only, above an annual threshold.**

### C.2 CoinSwitch trading fee — ⚠ conflicting and possibly in flux

| Source | Claim | Date |
|---|---|---|
| [Koinly India exchange review](https://koinly.io/blog/best-crypto-exchange-india/) | *"Maker/taker fees start from 0.4%"* | Updated 3 Sep 2026 |
| [Crypto Times](https://www.cryptotimes.io/2026/03/16/after-wazirx-coindcx-coinswitch-enters-indias-crypto-zero-fee-battle/) | Spot **0.04%–0.4%, tiered by volume**; futures 0.02% maker / 0.05% taker | 16 Mar 2026 |

⚠ **Both are third-party. I could not retrieve a current official CoinSwitch fee schedule** — their own fee page is a conceptual explainer with no rates, and the fee comparison page is behind bot protection.

⚠ **A change may be in progress.** On 16 March 2026 CoinSwitch posted messaging that *"strongly suggest[s] the exchange is preparing to drop trading fees"* following WazirX and CoinDCX, but as of that reporting *"no official pricing details, launch date, or product structure have been confirmed."* CoinSwitch has previously run limited-window zero-fee promotions on specific pairs.

**Model 0.4% and treat it as provisional.** For a retail-tier account with no volume history, the top of the tier is the right assumption.

**Add 18% GST on the trading fee** — standard for Indian exchanges, though I could not confirm CoinSwitch's specific treatment.

**Spread:** CoinSwitch operates as an aggregator routing across liquidity sources, so the executed price carries an implied spread on top of the explicit fee. **No published spread figure exists** — it is not disclosed and varies by pair and size. The only way to measure it is empirically: log the mid-market price at order time from an independent source (CoinGecko, which you already ingest) and compare to your fill. **Do this from day one** — it is the only unmeasured cost in this entire document, and on an aggregator it can exceed the explicit fee.

**Deposit/withdrawal:** INR deposits via UPI are generally free; crypto withdrawals carry network fees that vary by chain. Not published in a form I could verify.

---

## D. US equity — INDmoney

### D.1 Brokerage

**0.25% of trade value, capped at $25 per trade, plus GST** ([INDmoney](https://www.indmoney.com/learn/us-stocks/inr-to-usd-conversion-and-forex-markup)). Charged on both buy and sell. The cap binds above $10,000 per trade.

⚠ [Chittorgarh](https://www.chittorgarh.com/brokerage_charges/indmoney/182/) (last updated 31 Mar 2025) states *"0.25% or $25, whichever is lower"* — same thing, read as a cap.

> **Type: percentage of trade value, capped. Both legs.**

### D.2 FX conversion markup — the real cost

**0.5% to 1.2% over the interbank rate, charged by the partner bank, not by INDmoney.**

INDmoney's own wording: *"forex conversion charges are 0.5% to 1.2% and charged by the bank."* Their other page gives a slightly wider band: *"Currency exchange can range from 0.5% to 1.5% dependent on your bank."*

**This dwarfs the brokerage.** On a ₹30,000 remittance, 1% FX markup is ₹300 while brokerage on the resulting ~$340 trade is ~$0.85 (₹77). **Model FX as the dominant US-equity cost, and model it on the remittance, not on the trade** — you pay it once when INR becomes USD, not per trade.

The range is wide and bank-specific, so **calibrate it from your own first remittance**: record the interbank USD/INR mid at the moment of transfer (you already ingest FX) and compare to the rate you actually received. That single observation replaces the 0.5–1.2% guess with your real number.

This also connects to §12.4 of the spec: the FX markup is a **cost**, while the subsequent movement in USD/INR is a **return component**. They must not be conflated.

> **Type: percentage of the INR amount remitted, one-time at conversion.**

### D.3 Account and withdrawal charges

- Account opening: **$0**
- Annual maintenance: **$0**
- Platform fee: **$0**
- Withdrawal fee: **$0** — *"Zero Fees on US stocks deposits and Withdrawals"*
- Minimum investment: $1 / ₹100, fractional shares supported

⚠ Repatriating USD back to INR incurs the FX markup again, in the other direction. A round trip therefore pays the spread twice.

### D.4 TCS on the remittance

**20% on LRS remittances above ₹10 lakh per financial year; nil below.** Threshold raised from ₹7 lakh effective **1 April 2025**.

**TCS is not a cost.** Like crypto TDS, it is prepaid tax — fully creditable against your income tax liability and refundable if excess. Model it as a cash-flow item. At ₹30,000/month you will not approach the threshold unless US allocation rises sharply.

---

## E. Summary table for `services/costmodel`

| Charge | Asset | Rate | Type | Side | Effective |
|---|---|---|---|---|---|
| Brokerage | Groww equity | min(₹20, 0.1%), floor ₹5 ⚠ | % capped/floored | Both | min ₹5 from 21 Jun 2025 |
| STT | Indian equity delivery | 0.1% | % of turnover | Both | Unchanged in Budget 2026 |
| Exchange txn | NSE | 0.00307% | % of turnover | Both | ₹307/cr since 1 Oct 2024; split revised 1 Mar 2026 |
| Exchange txn | BSE | 0.00375% | % of turnover | Both | 1 Dec 2022 |
| SEBI fee | Indian equity | 0.0001% (₹10/cr) | % of turnover | Both | 3 Apr 2019 |
| Stamp duty | Indian equity delivery | 0.015% | % of turnover | **Buy only** | 1 Jul 2020 |
| GST | Indian equity | 18% of (brok + txn + SEBI + DP) | % of fee base | Both | — |
| DP charge | Groww equity sell | ₹23.60 (M) / ₹23.31 (F) incl. GST | **Flat, per ISIN per day** | **Sell only** | CDSL tariff 1 Oct 2024 |
| Demat AMC | Groww | ₹0 | — | — | — |
| Stamp duty | Mutual funds | 0.005% | % of purchase | **Buy only** | 1 Jul 2020 |
| Exit load | HDFC Flexi Cap Direct | 1.00% if < 1 yr | % of redemption, per lot | Redeem | Current |
| Exit load | HDFC Mid Cap Direct | 1.00% if < 1 yr | % of redemption, per lot | Redeem | Current |
| DP charge | MF in demat mode | ₹3.25 + Groww markup ⚠ | Flat, per ISIN | Redeem | Avoid by using SOA mode |
| TDS | Crypto | 1% | % of consideration | **Sell/transfer only** | s.194S, 1 Jul 2022. **Prepaid tax, not a cost** |
| Trading fee | CoinSwitch | ~0.4% ⚠ provisional | % of trade | Both | May be changing |
| Spread | CoinSwitch | Unpublished — **measure empirically** | implicit | Both | — |
| Brokerage | INDmoney US | 0.25%, cap $25, + GST | % capped | Both | — |
| FX markup | INDmoney US | 0.5–1.2% ⚠ **calibrate from first remittance** | % of INR remitted | On conversion | — |
| Account/withdrawal | INDmoney US | ₹0 | — | — | — |
| TCS | LRS remittance | 20% above ₹10 L/FY | % of remittance | Outbound | ₹10 L threshold from 1 Apr 2025 |

---

## F. What to verify against your own records

Five things I could not settle from public sources. Each is one contract note away.

1. **Groww brokerage: 0.1% or 0.05%?** Any trade between ₹20,000 and ₹40,000. Exactly ₹20 → 0.1%. Less → 0.05%.
2. **Is GST charged on the full ₹20 DP charge, or only Groww's ₹16.50?** Any sell contract note.
3. **Does Groww's ₹16.50 DP markup apply to mutual fund debits in demat mode?** Any MF redemption from demat.
4. **CoinSwitch's current fee tier and whether zero-fee has launched.** Your CoinSwitch trade history.
5. **Your actual FX markup on INDmoney.** Compare your received rate to the interbank mid at the time of your last remittance.

---

## G. What this changes in the spec

`investments-module-technical.md` §12.5 currently models Zerodha's charge sheet: ₹0 brokerage and a ₹15.34 DP charge. Both are wrong for Groww. The corrections:

- Brokerage `min(₹20, 0.1% × turnover)` floored at ₹5, **on both legs** — previously ₹0
- DP charge **₹23.60**, not ₹15.34
- NSE exchange charge confirmed at 0.00307%, with a note that the contract-note line-item split changed on 1 Mar 2026
- GST base extended to include DP charges
- Exit load added as a per-lot FIFO calculation reusing the tax lot matcher
- Crypto TDS and LRS TCS reclassified as **prepaid tax, not expense** — modelling them as costs would double-count against the 30% VDA rate
- FX markup modelled **on the remittance**, not per trade, and calibrated from observation rather than assumed
- A new `charge_schedules` row keyed to effective date, per §12.5's existing versioning requirement, so a rate change in six months does not retroactively rewrite the cost of past trades

**The break-even number is the one to carry forward: 0.66% on a ₹13,000 round trip, and 5.6% of a 12% gain.** Any proposal whose thesis targets less than roughly 2% is not worth transacting, and the decision engine should say so before it reaches a notification.
