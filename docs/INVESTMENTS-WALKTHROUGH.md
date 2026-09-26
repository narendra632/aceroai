# The Investments module, walked through

*Written for Narendra, to be read once slowly and then kept for reference.*
*Covers everything shipped up to 27 September 2026 — the ledger, the prices, the framework,
the accounts, the scores, the suggestions, the watching, the reading layer that finds new
companies, the parallel books, the reviews, the go/no-go criteria, and the record of
predictions that grades the lot.*

This is the document that explains the whole thing: what each part does, what the arithmetic
actually computes, what you will see on the screen, and — most usefully — what happens in a
handful of specific situations, using your own holdings and real numbers.

There is no code in it. If a sentence here disagrees with the code, the code is wrong and it
should be fixed, not the sentence.

---

## Part 1 — The one idea

> **Every investing tool records what you did and throws away why. This one keeps the why,
> freezes it before the outcome is known, and grades it later.**

Groww knows you bought 5 Kaynes at ₹3,378.80 on 12 August. It has no idea why, and in eight
months neither will you — you will have a story, and the story will have quietly rearranged
itself to fit whatever happened.

That gap is the whole reason this module exists. Everything below is scaffolding around it.

---

## Part 2 — The eight layers

The module is built in layers, and which layer a thing lives in decides how much it can be
trusted. From the bottom:

| | Layer | What it holds | Who writes it |
|---|---|---|---|
| 1 | **The ledger** | Your transactions | **You.** Never a machine |
| 2 | **The market record** | Prices, NAVs, exchange rates, corporate actions | Fetched from five sources |
| 3 | **The fold** | Positions, lots, cost basis, returns | Computed fresh every time |
| 4 | **The framework** | Imperatives, bottlenecks, multiples | Your theory, versioned |
| 5 | **Judgement** | Scoring, thesis-writing | ← *the only place a model belongs* |
| 6 | **The gates** | Hard rules a suggestion must survive | Python, never a prompt |
| 7 | **The record of judgement** | Proposals, decisions, conditions, claims | Append-only |
| 8 | **The grading** | Did the claims come true? Was the confidence honest? | Computed |

**The model touches exactly one layer.** Everything below it is fact; everything above it is
deterministic code that can overrule it. That single constraint is the whole safety design —
the model can be wrong about judgement, which is recoverable, and cannot be wrong about
arithmetic, which is not.

Layer 5 now has four inhabitants, and what they have in common is more important than what
they do: **not one of them may produce a number or introduce a name.**

| What it does | What it is allowed to answer with |
|---|---|
| Answer the six reflexivity questions news can settle | one of four verdicts, with a quote that must really be in the evidence |
| Place a company on a bottleneck | an id from a closed list of 31, or nothing |
| Read a direction onto a company a matcher already found | bullish, bearish, or neither |
| Transliterate names out of Hindi commentary | plain text, which the exchange's 2,595-name register then accepts or rejects |

Every score, price, ratio and threshold is still assembled from filed figures by ordinary
code. A thesis built this way *cannot* contain a number that was never filed.

---

## Part 3 — Layer by layer, in plain terms

### Layer 1 — The ledger

Everything you own is in here because you typed it. Nothing infers a holding, ever.

It is **append-only**: there is no edit and no delete, and the database itself refuses both. A
mistake is corrected by recording a new entry that supersedes the old one — both stay visible,
and the history shows that you corrected it.

Why so strict? Because the question this whole module exists to answer is *"what did I own in
March, and what did I believe when I bought it?"* If a row can be changed afterwards, that
question has no stable answer and every review built on it is a story rather than a
measurement.

### Layer 2 — The market record

Prices are **observations**: a number, from a named source, at a stated moment. Five sources,
each for what it is best at:

| What | Daily close | Live price |
|---|---|---|
| Your four NSE stocks | **NSE's own bhavcopy** — official, no login | **Angel One** quote |
| Your two mutual funds | **AMFI**, history via mfapi.in | — (one NAV a day) |
| SpaceX + USD/INR | **Twelve Data** | Twelve Data |
| Your four coins | **CoinGecko** (one year) | CoinGecko |
| Crypto older than a year | **Binance** × that day's USD/INR | — |

Two properties matter:

**Nothing is ever overwritten.** Filling the same day twice writes nothing the second time. So
the jobs are safe to re-run, and the first run on any database *is* the backfill.

**A price has an age, and staleness depends on the market.** A closing price is *current*
until the next session opens — flagging Friday's close as stale on Saturday afternoon would
mark your whole book stale every weekend, which is how a warning stops being read.

### Layer 3 — The fold

Your positions are never stored. Every time anything needs them, the ledger is read from the
beginning and folded into holdings.

That sounds wasteful and is not: it is sub-millisecond on your book, and it means a position
can never silently drift from the transactions underneath it. Storing a running total is how
two numbers that must agree end up disagreeing with nobody noticing.

Lots are kept separately, first-in-first-out, because that is how Indian demat sales are
matched — and on a multi-lot holding, FIFO and weighted-average give **different** realised
gains on the same sale. The page shows the average because that is what every broker app
shows; the tax view uses FIFO, and each says which it is.

### Layer 4 — The framework

Your theory, stored as data: ten national imperatives, thirty-one bottlenecks, nineteen sector
multiples.

It is **versioned**. Change anything and a new version is written; every score already made
still points at the version that produced it. That is what lets you improve the framework
without corrupting the history of decisions made under the old one.

**A company's place in it scores zero until you agree.** Acero can propose that a company
clears a bottleneck; the claim is worth nothing until you click. Without that, a system reading
enough news will eventually talk itself into believing an unrelated small-cap is nationally
essential, and the score has no way to tell that apart from the real thing.

### Layer 5 — Judgement

A model reads news, filings and the channels you follow, and answers the six reflexivity
questions that cannot be computed. Four of the ten flags are arithmetic and are computed; two
of those four **override** whatever the model later says, because a measurable thing should
never be a matter of opinion.

Four gates stand between a model's answer and the record, and a verdict that fails any of them
becomes UNKNOWN rather than an answer:

1. **It must cite.** No quote, no verdict.
2. **The quote must be real.** The words are checked against the evidence it was given. A
   model answering from what it expects an article to say writes fluent quotes that are not
   there.
3. **A second reader must agree.** Two independent passes; disagreement is UNKNOWN.
4. **It must not calculate.** Any verdict that produces a figure is refused — arithmetic is
   layer 3's job and a model's arithmetic is not checkable by looking at it.

The same shape governs the reading layer. A model may *transliterate* a Hindi transcript into
Latin-script names, but the exchange's own list of 2,595 companies decides whether any of them
is a company — so a hallucinated name is rejected exactly as a misheard one is, and a language
model can never write a row into the table that measures where your ideas come from.

### Layer 6 — The gates

Nine hard rules, in ordinary Python, reading stored rows. No instruction anywhere asks a model
to respect them, **because an instruction is a request**.

A gate that a sufficiently persuasive argument can talk its way past is a preference. The whole
point of writing rules down in advance is that they bind on exactly the day you would rather
they did not.

### Layer 7 — The record of judgement

Every suggestion, with the price the system saw, the scores it rested on, which rules were
checked and what each decided — all **frozen**. A review that recomputes the inputs is
reconstructing a decision rather than examining one, and from the outside the two look the
same.

### Layer 8 — The grading

Four measures over the predictions layer 7 froze. More in Part 7.

**This layer was empty for a month, and the reason is worth keeping.** Predictions used to be
written only for suggestions that survived every gate — and in a market where nothing is
cheap, nothing survives. Fifty-seven suggestions were raised and fifty-seven were blocked, so
the system produced exactly zero falsifiable predictions while appearing to run perfectly.
The go/no-go asks for 150 resolved predictions inside a year; at zero a night it would have
been at zero in a year, and nobody would have found out until the year was over.

Predictions are now recorded **whether or not the gates open**, because calibration is a
property of the judge rather than of the purchases — a forecaster is not graded only on the
days someone carried an umbrella. Each carries the rule that refused the idea it came from,
so a reader always knows which population a number was computed over.

They are also deduplicated. The same company is reconsidered every night and its predictions
come out identical, so recording each night's would have reached "150 resolved" inside a week
with 150 copies of the same three sentences — a measure that reads as a large sample while
being a sample of one. A prediction is recorded only where no open one already says the same
thing about the same company.

---

## Part 4 — The arithmetic, explained

Three scores. **They are never added together.** The most valuable thing your frameworks can
tell you is *structurally essential, genuinely excellent, and still a bad purchase today* —
which is exactly the finding an average destroys.

### Score 1 — Structural (out of 10)

Pure arithmetic over a mapping you approved. No model involved and none permitted.

| Component | Max | How it is earned |
|---|---:|---|
| **Breadth** | 4 | How many of the ten imperatives this bottleneck blocks. ≥6 → 4; 3–5 → 3; 2 → 2; 1 → 1 |
| **Crisis** | 2 | A named shock pulled the spending forward |
| **Timing** | 2 | Inflecting now → 2; inside your holding period → 1; beyond → 0 |
| **Commitment** | 1 | A committed spend figure traceable to an ingested document |
| **Investability** | 1 | Green → 1, amber → 0.5, red → 0 |

**Worked example — GE Vernova:**

```
breadth        4/4   transmission blocks 6 of the ten imperatives
crisis         0/2   your notes call it implied, not one of your three named shocks
timing         2/2   inflecting now, peaking FY26–30
commitment     0/1   no ingested source yet carries the ₹200 trillion figure
investability  1/1   green
               ─────
               7/10
```

> **The commitment point is withheld on purpose.** The rule requires a spend figure traceable
> to an ingested document, and your framework document is not one. Awarding it from the
> framework's own prose would be the system citing itself — precisely what the sourcing rule
> exists to forbid. It will be earned once the reading layer ingests a budget document.

**Your whole universe, computed:**

| | Score | |
|---|---:|---|
| Genus Power | **8/10** | ⚠ your highest, and you don't own it |
| Kaynes · GE Vernova · Apar | 7/10 | |
| Solar Industries | 6/10 | breadth floored at 1, carried by the crisis flag |
| Sai Life · Neuland | 5/10 | |
| Syrma | 4.5/10 | after correcting B2.2 to three crossings |
| Premier Energies | 4.5/10 | |
| HDFC Bank | 4/10 | correct — see below |
| SpaceX · Rolex Rings | — | outside the framework |

**On HDFC Bank's 4/10.** This is the framework working, not failing. It is telling you that
HDFC Bank is *not a structural play*. You do not own it because it unblocks a national
imperative — you own it because it is a quality bank below 18× with an inverted narrative.
That belongs in score 2 and score 3. Widening its bottleneck to flatter your largest holding
would be rewriting your framework to agree with your portfolio.

**On "at least N".** Twenty-three of the thirty-one bottlenecks carry a *floor* rather than an
established count, because your notes spell the crossings out for only eight. The screen says
"blocks at least 1" and offers a control to set the real figure. A gap in a write-up scored as
a fact about India would mark ammunition structurally narrow because that section is short.

### Score 2 — Business and price (out of what could be measured)

Every figure from the company's own filing with the exchange.

| Component | Max | The test |
|---|---:|---|
| Return on equity | 2 | ≥15% in ≥3 of the last 5 years |
| Return on capital | 2 | 5-year average ≥15% → 2; ≥12% → 1 |
| Profit into cash | 2 | 3-year mean cash flow ÷ profit ≥0.8 → 2; ≥0.6 → 1 |
| Debt | 1 | Net debt < 2× earnings before interest and depreciation |
| Retained earnings | 1 | Did each rupee retained create a rupee of value over 5 years |
| Margin of safety | 2 | ≥25% below a defensible worth → 2; 0–25% → 1; above it → 0 |

**The number is always reported as "earned out of available."** Six on its own means nothing:
six of ten is mediocre and six of six is excellent, and the difference is entirely how many of
the filings have been read.

**Worked example — Apar Industries:**

```
return on capital   2/2   29.2% average over the 2 years read
profit into cash    2/2   ₹1.28 of cash per rupee of profit
debt                1/1   net debt 0.1× earnings
return on equity    1/2   ≥15% in 2 of 2 years read
retained earnings    —    needs 5 years of market value; the price record does not reach back
margin of safety     —    no market price yet (watchlist backfill in progress)
                    ─────
                    6 of 7 measurable  =  86%
```

> **A missing input is "—", never 0.** A company marked poor because its filings had not been
> read is *indistinguishable*, from the outside, from a company that is genuinely poor. Only
> one of those is a judgement.

**Margin of safety, in detail**, because it is where most refusals come from:

```
owner earnings  = profit + depreciation − maintenance capex
                  (maintenance capex is disclosed nowhere, so depreciation
                   stands in for it — the two then cancel, which is why this
                   lands close to profit and is flagged as a proxy)

worth           = owner earnings, averaged over 3 years  ×  the sector multiple
margin          = (worth − market value) ÷ worth
```

**⚠ Trailing reported earnings, never a forecast.** No filing contains next year's profit, so a
forecast can be checked against nothing — and an unverifiable number is exactly what this
design forbids. **The consequence is real and you will meet it:** Acero will call your growth
holdings expensive where your own forward estimate calls them fair. That is Buffett's
discipline doing its job, not a bug.

**Worked example — GE Vernova, and it is the important one:**

```
sector multiple                          28×   (your own "fair PE 25–30x", midpoint)
worth       = owner earnings × 28
market cap  ≈ 4.35 × worth
margin      = (worth − market cap) ÷ worth  =  −335%
```

**335% above a defensible worth.** The system independently arrived at your framework's own
central finding: *structurally essential, genuinely excellent, and still a bad purchase today.*

**Banks are measured differently.** For HDFC Bank, return on capital, profit-into-cash and the
debt test all report "—". Borrowings are a bank's **raw material**, not its leverage; its cash
flows follow deposits, not trading. Scoring those as though they described an industrial would
class a sound bank as a failing business — and that classification would block you from ever
adding to your largest holding.

### Score 3 — Reflexivity (four of ten questions, so far)

Ten red-flag questions. **YES is bad**, on all ten. Four are arithmetic and live now:

| # | Question | How it is answered |
|---|---|---|
| 2 | Returns declining or below 15%? | From the filings |
| 6 | Multiple expanded far faster than earnings? | Price × shares ÷ profit, year on year |
| 8 | Margins deteriorating *as* revenue grows? | Both must be true |
| 10 | Market's tone shifted sharply? | 52-week range > 60% of its low |

Six need a model reading news and filings. **Flags 6 and 10 will override whatever that model
eventually says**, because a measurable thing should never be a matter of opinion — and those
two are exactly the ones a persuasive narrative would talk you out of.

**A flag with no evidence is UNKNOWN, never NO.** A checklist that answers "no" by default
reports a clean bill of health it never checked.

### The four boxes

```
                 story running          quiet
quality good     Q1 supercharged        Q3 ignored compounder
quality poor     Q2 story w/o business  Q4 cheap for a reason
```

**Q2 and Q4 forbid a purchase outright, with no override.**

And a fifth answer that matters more than it looks: **BORDERLINE — too little read to judge.**
Assigned whenever the margin of safety is unknown, fewer than 6 points were measurable, or more
than two components are missing.

> A company blocked because its accounts have not been read yet is indistinguishable from one
> blocked because it deserves it. I found Kaynes landing in "structural value trap" on *one
> year* of data — which would have permanently blocked a holding you own, for a pipeline
> reason. It now says "too little read to judge."

---

## Part 5 — What happens in a day, and in a week

| Time | What runs | Cost |
|---|---|---|
| 06:30 Sunday | `universe_sync` — the exchange's full equity list, 2,595 names | free |
| 07:30 | `prices_daily` — fills any missing close for funds, US, crypto | free |
| 08:00 | `benchmarks_sync` — the index funds you are measured against | free |
| **08:10, 12:10, 16:10, 20:10, 23:10** | **`sources_poll`** — the exchange's five feeds and your channels, including the spoken words of every new video | free |
| 16:45 weekdays | **`position_watch`** — checks every invalidation condition, settles due predictions | free |
| 19:00 weekdays | `prices_india_close` — NSE's bhavcopy | free |
| 20:00 weekdays | `corporate_actions_watch` — records splits, applies them on the ex-date | free |
| 20:30 daily | `candidate_analysis` — takes up to four queued companies through the same four steps a holding goes through | a few model calls |
| **21:00 daily** | **`evening_synthesis`** — the one run that decides | free today |
| Sunday 08:00 | `fundamentals_sync` — reads every company's filings | free |
| Saturday 09:00 | `investments_weekly_review` — the week in aggregate | free |
| 1st of month | `investments_monthly_review`; quarterly on 1 Jan/Apr/Jul/Oct | free |
| Monday 09:00 | `investments_disk_watch` — the module against its 250 MB budget | free |

The 23:10 poll exists because NSE's announcement feed empties overnight: a day's filings are
gone by morning, and a reader that only looked in daylight would miss them permanently.

Two of these will interrupt you and the rest never will:

- **A fired invalidation condition** — always, immediately. A thesis you hold money against has
  been contradicted by the facts, and being told is the entire reason the condition was written
  down in advance.
- **A suggestion** — at most one notification an evening.

Everything else is silent. `evening_synthesis` records a row whether or not it suggests
anything, because a system that only leaves a trace on the days it acted can never be measured
against the days it should have acted and did not.

---

## Part 6 — Six scenarios, worked through

### Scenario 1 — An ordinary evening (what will actually happen tonight)

21:00. Acero reads eleven tracked companies, scores each one, applies nine rules to each, and
proposes **nothing**. No notification. One `agent_runs` row saying eleven considered, zero
proposed.

Open the page and the Suggestions panel says:

> *Nothing is suggested right now. That is the usual and usually correct answer. Every evening
> is recorded either way, so the quiet ones can be counted later.*

**That is the system working.** A research analyst who finds something worth doing every single
day is not an analyst.

### Scenario 2 — Why nothing was suggested tonight, in detail

Expand "refused by the rules" and you will see exactly this:

| | Blocked by | Because |
|---|---|---|
| **GE Vernova** | the price | *335% above a defensible worth of 28×* |
| Apar, Solar, Neuland, Syrma, Genus, Premier, Kaynes, Sai Life, HDFC Bank | business and price together | *too little of its accounts has been read to say which box it is in* |
| **Rolex Rings** | its place in the framework | *off-framework holdings are already 19.3% of the book, at the 5% ceiling* |

Three different kinds of refusal, and it is worth knowing which is which:

- **GE Vernova is a real verdict.** Enough was read; the answer is "too expensive". If the price
  fell 70% or earnings quadrupled, this would change.
- **The nine are a data gap**, and they resolve as the watchlist price backfill finishes over
  the next few evening runs.
- **Rolex is a rule about portfolio shape**, not about Rolex. SpaceX already occupies the whole
  off-framework allowance.

> **On that 5% ceiling.** It governs what may be *added*, never what is already held. Applying
> it backwards would block a position you took before the framework existed — not a decision
> the rule was ever written to make.

### Scenario 3 — A suggestion arrives

Say Apar's price backfill completes, its accounts read at 86%, and the price has fallen to
where the margin of safety is 30%. All nine rules pass. At 21:00 you get:

> **APARINDS: start a position, and 1 other**
> *Nothing moves until you decide. Each one carries what it rests on and what would prove it
> wrong.*

The card shows:

```
APARINDS: start a position        ₹9,375 · 12 shares
                                  74% confident · 270 days · Q3

Apar Industries clears B1.1, which blocks 6 of the ten imperatives.
Structural score 7 of 10.
What is good: roce — 29.2% average over 2 years read; cash_conversion —
1.28 of profit arrived as cash; balance_sheet — net debt is 0.1× earnings.
Not measured: retained_earnings — so this rests on 6 of 7 available
points, not on ten.

Suggested at ₹782.40, and that price is frozen onto this record.

WHAT WOULD PROVE THIS WRONG
 • Return on capital falls below 12% in the next annual filing.      (by 17 Jun 2027)
 • Less than 60 paise of each rupee of profit arrives as cash.       (by 17 Jun 2027)
 • The price falls below ₹586.80, a quarter below where this was
   suggested, without the accounts explaining it.                    (by 17 Jun 2027)

WHAT IT IS CLAIMING
 • Return on capital stays at or above 15%.
 • Profit keeps arriving as cash, at or above 0.8.

[ Why — in your own words. Required. ]
[ Approve ]  [ Reject ]
```

**The reason field is required and both buttons stay disabled until you fill it.** That is not
politeness. It is the data that eventually reveals what kinds of suggestion you keep turning
down — the only route by which the system learns anything about its own judgement.

**Where 74% comes from.** Confidence is *derived*, not chosen: 35% weight on how much could be
measured, 40% on how strongly it scored, 25% on the structural score, minus 8 points per red
flag standing. A figure a model picked because the argument felt strong would measure the
model's mood; this measures what was known. It matters because confidence is the number
calibration is scored against.

### Scenario 4 — You approve it, then buy something different

Approve → the decision is recorded with your reason, the three conditions arm, and the
**system's paper book** records the position.

Your real book is untouched. If you then buy 8 shares instead of 12, or wait a week, or don't
buy at all — you enter that yourself, as you enter everything.

> The two books are deliberately separate. The gap between "what the system suggested" and
> "what you did" is one of the most interesting numbers this module will ever produce, and
> merging them would destroy it.

### Scenario 5 — A condition fires

Four months later, Apar's annual filing lands and return on capital comes in at 10.4%.

16:45 the next weekday, `position_watch` reads it, compares against the 12% written down in
June, and fires. Immediately:

> **APARINDS: something that would disprove the thesis has happened**
> *Return on capital falls below 12% in the next annual filing. It now stands at 10.4. This was
> written down before the position was taken.*

The panel shows it above everything else, in red, with the evidence: *"roce now 10.4, against
the 12 written down when the position was taken."*

**It fires whether or not the story still looks good.** That is the point. A system that writes
invalidation conditions and then reasons past them has quietly stopped being a system — and
that failure is measured, by trigger discipline, which is the one criterion that is not
statistical. A *single* ignored firing is a finding.

### Scenario 6 — A bonus issue is announced

NSE announces a 1:1 bonus on Kaynes, ex-date in three weeks.

**20:00 that evening** — `corporate_actions_watch` reads it, records it, and tells you. From
that moment the holdings row is flagged and its profit-and-loss is marked unreliable. Nothing
can be proposed about Kaynes (rule G7).

**On the ex-date** — the price halves. Acero applies the bonus: your 5 shares become 10, your
total cost basis is *unchanged*, and each lot's per-share cost halves — ₹960 and ₹722 become
₹480 and ₹361, **not ₹420 twice**. Flattening them would conserve the total and report the
wrong realised gain on every FIFO sale afterwards.

Without this, your page would show Kaynes down 50% overnight. That is the single most likely
way this system could have done you real damage, and the whole apparatus exists for it.

> **If the announcement's wording is ambiguous, nothing is applied.** `BONUS 1:1` is
> unambiguous; a bare `SPLIT 1:10` does not say which side is the old face value, and the two
> readings differ by a factor of a hundred. Anything unreadable is flagged for you instead. The
> confident wrong answer is a larger fiction than the one being fixed.

---

## Part 7 — How you will know whether any of this works

### The honest problem

At ₹30,000 a month you will make thirty to forty-five decisions a year. **That is not enough to
conclude anything about skill.** The statistical floor is about thirty observations and that is
a *floor*, not a standard; serious work wants hundreds across different market conditions.
Anyone who tells you otherwise — including this system, if it ever starts to — is selling
something.

### The way around it

Each thesis makes several specific, checkable assertions. Each position carries at least two
invalidation conditions. Each suggestion carries a confidence level.

**That is a few hundred testable predictions a year instead of thirty outcomes** — the
difference between knowing in months and knowing in decades. It is the entire reason claims are
written down at all.

### The four measures

| Measure | What it asks | Reports from |
|---|---|---|
| **Claim accuracy** | Of the specific things it said would happen, how many did? | 20 resolved claims |
| **Calibration** | When it says 80%, is it right 80% of the time? | 20 settled theses |
| **Trigger discipline** | When something disproved a thesis, did anything happen? | **the first firing** |
| **Decision record** | How often did you agree? | the first decision |

All four show **"—"** today, and will for months.

> **That blankness is the feature.** A precision computed over six outcomes reads *exactly*
> like one computed over six hundred, and nothing in an interface can tell you which you are
> looking at. So the figure is withheld rather than shown with a caveat — a caveat next to a
> number is read as a number.

### But blank for the right reason, not the wrong one

There is a failure that looks identical to healthy blankness and is not: a measure that can
**never** fill. Both show "—" and neither complains.

Two have been found and fixed, and they were the same mistake in different clothes — a
threshold written as an absolute where it should have been relative to what could actually
exist:

| Looked like | Actually was |
|---|---|
| "Kaynes and Sai Life score unknown" | a five-year rule asked of a company listed eighteen months ago |
| "no predictions yet" | predictions written only for suggestions the gates let through, and the gates let none through |

So the criteria now say when their own target is out of reach. Most predictions settle on the
next annual filing, which means a book of a dozen companies produces roughly thirty a year —
and 150 of them needs about seven years at that size. The screen says so, in those words,
because a permanently unmet criterion that looks pending is worse than one that is simply
unmet. **Widening the watchlist is what shortens that, not waiting.**

**Calibration** is scored with Brier: the mean squared gap between confidence stated and what
happened. **Lower is better.** 0.25 is what a coin achieves by saying 50% to everything.
Overconfidence is the most common and most correctable failure of a system like this, and it
shows up here before anywhere else.

**Trigger discipline is deliberately not statistical.** It reports from the first firing,
because one ignored condition is a finding rather than a data point.

**Decision record is described, not scored.** A high agreement rate could equally mean the
system is good *or* that it has learned to suggest only what will be accepted. Whether your
vetoes add or subtract is answered by the shadow book over years, not by counting.

### The three shadow books

Alongside the real book, three ledgers track what did **not** happen:

- **What you turned down** — measures the cost of your vetoes
- **What the budget could not fund** — measures the cost of the constraint
- **What the rules blocked** — ⚠ the most valuable of the three, because it is the only way to
  find out whether the safety rails are protecting or merely obstructing

> **A warning about reading them.** Rejected ideas that went *up* are far more memorable than
> rejected ideas that went down. Read in aggregate, on a schedule — never dipped into after a
> name that got away. A shadow book read casually trains worse judgement, not better.

---

## Part 8 — What it will never do

- Connect to a brokerage, place an order, or read your real holdings. **Not a limitation to
  engineer away later** — it is what keeps this outside the regulatory category that governs
  automated trading in India.
- Hold an opinion about the next few hours.
- Compute your tax. It flags consequences; it does not file anything.
- Propose crypto or mutual funds. Tracked and reported, never suggested — crypto because a flat
  30% with no loss set-off changes the arithmetic of every position.
- Be published or shared. The moment its output reaches a third party it becomes regulated
  investment advice.
- Be backtested. The model already knows what happened to these companies before its training
  cutoff, so a backtest would produce a confident, wrong, deeply persuasive answer.
- **Produce a number it cannot point to a source for.** If it does not have the figure, it says
  it does not have the figure.

---

## Part 9 — The same module, in a conversation

Everything above has a screen. It also has a chat interface, and the two read the same code —
so a figure is never computed twice and the page and the assistant can never quote different
numbers for the same portfolio.

Ask in plain words: *what is my book worth*, *why is Kaynes scored like that*, *did it suggest
anything*, *why is nothing being suggested*, *what did my channels say*, *what has it
predicted*, *am I beating the index*, *is this working*. It answers from the tools, not from
memory.

**It can record a transaction and decide on a suggestion — both in two steps.** It tells you
what it understood and waits for your confirmation before anything is written. That is not
politeness: the ledger is your word, and a decision is the row the system is eventually graded
on. A model that could write either in a single call could invent a holding, or quietly write
its own report card.

It cannot approve a framework mapping, approve a source, or promote a company out of the
research queue. Those are structural claims about your theory, and they stay on the page where
you can see what you are agreeing to.

---

## Part 10 — What is not built yet, stated plainly

| | Why it matters |
|---|---|
| **Annual accounts before FY25** | The exchange tags earlier years' profit as a fourth quarter. Two years is what exists in machine-readable form; more means summing quarterly filings. Every rule now scales to what a company *could* have, so this thins a reading rather than blocking one |
| **Retained-earnings test** | Needs five years of market value; the price record does not reach back that far. Fills itself with time |
| **Asset quality for a bank** | Gross NPAs and the deposit mix are disclosed in the results but not under tags this reader collects. Provisioning and funding spread stand in, and say that they are standing in |
| **Bank bands rest on one peer** | Cost-to-income and credit-cost bars are anchored on HDFC's own filing plus the shape of the peer set, not a measured distribution. Revisit when a second lender enters the book |
| **The government-commitment point** | Withheld until a budget document is ingested |
| **Your original framework documents** | Everything reads your framework through your cowork agent's summary of it. With the originals, most of the 23 provisional crossing counts could be established properly |
| **Channels that discuss Indian companies** | Measured 24 Sep 2026: of the three registered, two publish in Hindi and one teaches valuation with American examples. The machinery reads all three correctly; the sources are the wrong sources, and you change them from the page |

Parked deliberately, not forgotten: US companies, screenshot ingestion, a regime model,
framework self-tuning, the hyperactive parallel book, and reading PDFs.

---

## Part 11 — The honest summary

This is a machine for producing an **auditable track record**, not a machine for making money.

At ₹30,000 a month, a better decision process is worth a few thousand rupees a year against
simply buying an index fund. As a money-making machine at this size, it does not pay for
itself, and I would be lying if I said otherwise.

What it pays for is two things:

1. **You learn how software is really made** — and this module is the hardest, most real thing
   in Acero.
2. **A few hundred written, timestamped, unchangeable predictions and the reasoning behind
   each.** That cannot be bought, backfilled, or hurried, and in a decade of investing it is
   the thing that separates people who improve from people who accumulate stories.

The most valuable thing it produces in its first year is almost certainly not returns. It is
the record — and the record is what makes the second year worth running.

It is designed so that the answer "no, this does not work" is easy to see. **That is the only
design that makes the answer "yes" worth believing.**

---

*Where the code is: `backend/app/services/investments/` — `portfolio` (the fold), `pricing`,
`returns`, `taxrules`, `costmodel`, `entry`, `history`, `corpactions`, `schedulefa`,
`frameworks`, `framework_data`, `fundamentals`, `scoring`, `gates`, `proposals`, `watching`,
`overview`, and the research half: `reading`, `candidates`, `deduce`, `judgement`, `themes`,
`spoken`, `benchmarks`, `reviews`, `books`, `verdict`. Market adapters in
`backend/app/services/marketdata/` — `feed`, `feeds`, `universe`, `webpage`, `transcript`,
`nse_xbrl`. Jobs in `backend/app/jobs/`. The screen in
`frontend/src/components/InvestmentsView.tsx` and its panels, in five tabs. The same figures
reach a conversation through `backend/app/core/tools/investments.py` (the ledger) and
`research.py` (everything above it).*
