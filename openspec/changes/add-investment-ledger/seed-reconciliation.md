# The seed, reconciled by hand — before any code

**Computed 2026-09-06, from Groww / CoinSwitch / INDmoney screenshots.** This file exists so
the tests have something to be *checked against* rather than something to be *fitted to*. If
an implementation disagrees with a number here, the implementation is wrong until proven
otherwise.

---

## 1. Indian equity (Groww) — every share count exact

| Instrument | Date | Qty | Price | Lot cost |
|---|---|---:|---:|---:|
| **HDFC Bank** | 2026-04-27 | 5 | 787.80 | 3,939.00 |
| | 2026-06-04 | 7 | 750.30 | 5,252.10 |
| | 2026-06-05 | 4 | 746.80 | 2,987.20 |
| | 2026-08-12 | 13 | 723.75 | 9,408.75 |
| | 2026-08-12 | 4 | 722.65 | 2,890.60 |
| **Kaynes Technology** | 2026-05-12 | 1 | 4,133.20 | 4,133.20 |
| | 2026-05-14 | 1 | 3,388.00 | 3,388.00 |
| | 2026-05-15 | 1 | 3,271.00 | 3,271.00 |
| | 2026-05-18 | 1 | 3,102.00 | 3,102.00 |
| | 2026-05-20 | 1 | 2,999.80 | 2,999.80 |
| **GE Vernova T&D India** | 2026-05-29 | 1 | 5,000.00 | 5,000.00 |
| | 2026-06-01 | 1 | 4,748.00 | 4,748.00 |
| | 2026-06-02 | 1 | 4,639.50 | 4,639.50 |
| **Sai Life Sciences** | 2026-04-30 | 2 | 1,066.35 | 2,132.70 |
| | 2026-06-04 | 4 | 1,159.00 | 4,636.00 |

### Expected positions

| Instrument | Qty | Cost basis | Groww | Diff | Weighted avg |
|---|---:|---:|---:|---:|---:|
| HDFC Bank | 33 | 24,477.65 | 24,477.75 | −0.10 | 741.7470 |
| Kaynes Technology | 5 | 16,894.00 | 16,894.00 | **0.00** | 3,378.8000 |
| GE Vernova T&D India | 3 | 14,387.50 | 14,387.49 | +0.01 | 4,795.8333 |
| Sai Life Sciences | 6 | 6,768.70 | 6,768.72 | −0.02 | 1,128.1167 |
| **Total** | | **62,527.85** | **62,527.96** | **−0.11** | |

**Every share count matches exactly.** Total differs by 11 paise across 15 transactions —
Groww rounds each lot's cost to 2dp before summing; we sum exact products. Not a defect.

### ⚠ The excluded order — the reconciliation check working before it was built

The Kaynes order list contains a **BUY of 1 share at ₹3,080.00 on 2026-05-18 12:20 PM**,
marked with a red dot where the others are green.

- **Including** it → 6 shares, ₹19,974.00
- **Excluding** it → **5 shares, ₹16,894.00** — exactly what Groww reports for both

The arithmetic settles it: the order never executed. This is §11 step 4 of the technical
spec — *"a screenshot that does not internally reconcile is rejected wholesale"* — working on
real data before a line of code existed. Keep it as the worked example.

---

## 2. Mutual funds (Groww) — units exact on both

| Fund | Date | Amount | Units | NAV |
|---|---|---:|---:|---:|
| **HDFC Flexi Cap Direct Growth** | 2026-02-11 | 4,999.75 | 2.172 | 2,301.470 |
| | 2026-03-06 | 4,999.75 | 2.292 | 2,181.727 |
| | 2026-04-30 | 4,999.75 | 2.340 | 2,137.000 |
| | | **14,999.25** | **6.804** ✅ | avg NAV 2,204.57 |
| **HDFC Mid Cap Direct Growth** | 2026-02-12 | 4,999.75 | 22.113 | 226.103 |
| | 2026-03-06 | 4,999.75 | 23.229 | 215.237 |
| | | **9,999.50** | **45.342** ✅ | avg NAV 220.54 |

Units sum **exactly** to Groww's redeemable units on both funds. Both folio 40754072, Demat.
Invested differs from Groww's rounded ₹15,000 / ₹10,000 by ₹0.75 / ₹0.50 — stamp duty
rounding on each purchase.

---

## 3. ⚠ XIRR — the convention, established against a third party's arithmetic

Groww publishes an XIRR for each fund. Reproducing it is a far stronger test than any
synthetic case, because it is arithmetic **somebody else did**. Solved for the convention:

| | Groww | Ours | |
|---|---:|---:|---|
| HDFC Mid Cap | **12.25%** | **12.25%** | **exact** |
| HDFC Flexi Cap | 6.48% | 6.49% | +0.01pp |

**The convention that reproduces it:**

1. **Valuation date `2026-09-06`** — the day the figures were read
2. **Terminal value = units × current NAV**, *not* the rounded card figure. This is what
   makes Mid Cap land exactly: 45.342 × 234.584 = 10,636.51 gives 12.25%, while the card's
   rounded ₹10,637 gives 12.26%
3. **Day count actual/365**, discounting `(d − d₀).days / 365`
4. Newton–Raphson and bisection converge to the same value — so the fallback is verified, not
   merely present

**The residual 0.01pp on Flexi Cap is explained, not tolerated:** the NAV Groww displays
(2,271.324) is itself rounded to 3dp, and at 6.804 units that rounding is worth about ₹2 of
terminal value — more than enough to move the fourth significant figure of an annualised rate.
A test should assert **≤ 0.02pp**, and any drift beyond that is a real defect.

Sensitivity, for whoever debugs this later — the rate moves ≈ **0.04pp per day** of valuation
date on Flexi Cap and ≈ **0.07pp** on Mid Cap. A test that hardcodes a date will drift; the
valuation date must be an explicit input.

---

## 4. US equity (INDmoney) — exact

**SPCX** — SpaceX, Nasdaq, IPO 2026-06-12 at $135. An ordinary listed US equity.

| Date | Amount | Price | Units |
|---|---:|---:|---:|
| 2026-06-16 | 49.85 | 204.70 | 0.243527 |
| 2026-06-17 | 49.85 | 190.00 | 0.262368 |
| 2026-07-03 | 55.61 | 155.97 | 0.356543 |
| | **155.31** ✅ | avg 180.08 | **0.862438** ≈ 0.862429 ✅ |

Both totals match INDmoney exactly. `BUY EXPIRED` and `BUY CANCELED` orders correctly excluded
— the same reconciliation logic as the Kaynes case.

**⚠ Holding period is 24 months, not 12** → long-term from **2026-06-16 + 24m = 2028-06-16**.
**⚠ Schedule FA** is calendar-year and needs the *peak* value during 2026; the window opened
in June and is already partly historical.

---

## 5. Crypto (CoinSwitch)

| Coin | Qty | Invested | Buys | Entry |
|---|---:|---:|---|---|
| Zilliqa | 93.4675 | 297.03 | 2024-12-07 (1) | **exact** |
| JasmyCoin | 45.2488 | 200.00 | 2024-12-07 (1) | **exact** |
| Dogecoin | 23.8916 | 840.00 | 4 buys, Nov–Dec 2024 | **aggregate** |
| Bitcoin | 0.00001978 | 150.00 | 2024-11-17, 2026-05-01 | **aggregate** |

The two aggregates are entered as one row each at the average price, dated to the **first**
buy, `entry_source=IMPORT`, with a note saying so. Per-buy amounts are not recoverable from
CoinSwitch's history; a labelled aggregate is honest where an invented breakdown would not be.
₹990 across six buys moves no figure that matters.

**⚠ Losses here are tax-dead** and the ledger must show it rather than netting it:

| | |
|---|---:|
| DOGE | −625.89 |
| ZIL | −270.44 |
| JASMY | −180.38 |
| **Total unusable loss** | **−1,076.71** |
| BTC gain, still taxable at 30% | **+6.01** |

Under s.115BBH these losses offset nothing — not each other, not the ₹1,386 Indian equity
gain, not future years. **Assert this in a test**: crypto losses must not reduce equity gains
anywhere in the portfolio, and the ₹6.01 must remain visible as a gain.

---

## 6. Portfolio totals

| Class | Invested | Current | |
|---|---:|---:|---|
| Indian equity | 62,527.85 | 63,914.00 | +1,386 (+2.22%) |
| Mutual funds | 24,998.75 | 26,091.00 | +1,092 |
| Crypto | 1,487.03 | 416.30 | −1,070.73 (−72%) |
| US equity (SPCX) | $155.31 | $127.55 | −$27.76 (−17.87%) |

⚠ The US row is **deliberately left in USD here.** Converting it needs an FX rate, and the
rate at each transaction is a stored fact this document does not have. Filling it in is task
8.3, and doing it by guesswork now would put a fabricated number into the file the tests
trust.

---

## 7. Holding-period boundaries — nothing near a cliff

| Holding | Rule | Long-term from |
|---|---|---|
| HDFC Bank (first lot) | 12 months | 2027-04-27 |
| Sai Life Sciences (first lot) | 12 months | 2027-04-30 |
| Kaynes Technology (first lot) | 12 months | 2027-05-12 |
| GE Vernova (first lot) | 12 months | 2027-05-29 |
| HDFC MFs (first purchase) | 12 months | 2027-02-11 |
| **SPCX** | **24 months** | **2028-06-16** |
| Crypto | none | flat 30% forever |

Earliest boundary is **2027-02-11**, five months out. Nothing to watch yet — but the clock
starts with this change.
