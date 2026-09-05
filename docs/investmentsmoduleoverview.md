# The Investments Module — What It Is and How It Behaves

*A non-technical description of a proposed Investments capability for Acero.*
*Written 3 September 2026. Nothing described here is built yet.*

---

## 1. The one-paragraph version

The Investments module is a **research analyst and a bookkeeper that never sleeps and never trades**. It watches markets, filings, news and a small set of trusted commentators. It maintains a paper copy of the portfolio that mirrors what happens in the real world, and it keeps that copy honest by requiring the human to tell it what actually happened. When it thinks something should change, it writes a proposal — with a thesis, a size, a horizon, a score against the investment frameworks, the conditions under which it would admit it was wrong, and a confidence level — and sends it as a notification. Nothing moves until the human approves. Every proposal, every approval, every rejection and every input that produced them is written down permanently, so that months later it is possible to ask *"why did we do that, and was the reasoning right or were we just lucky?"* and get a truthful answer.

It is a machine for **producing an auditable track record**, not a machine for making money. The money question comes later, and only if the track record earns it.

---

## 2. The three rules the whole design hangs on

**Rule 1 — It proposes, it never acts.**
The system has no connection to any brokerage. It cannot see real holdings and cannot place an order. This is not a limitation to be engineered away later; it is the point. It is also what keeps the system outside the regulatory perimeter that applies to automated trading systems in India — a program that suggests and does not execute is not an execution algorithm.

**Rule 2 — The ledger is the human's word, the prices are the market's.**
What was bought, at what price, on what date, comes from the human — typed in plain language or read off a screenshot of a broker dashboard. The system never guesses a transaction into existence. Market prices, on the other hand, are fetched automatically. This split matters: it means the portfolio can never be silently wrong about *what is owned*, only about *what it is currently worth* — and the second kind of error is visible and self-correcting, while the first kind is poison.

**Rule 3 — Numbers come from records, judgement comes from the model.**
The AI is never asked to calculate. Every figure it uses in a thesis is looked up from a stored record with a traceable source, and the arithmetic is done by ordinary code. The AI's job is to read, connect, argue and score. The moment a system lets a language model produce a financial figure from memory, the figures become fiction that reads like fact — and that is the specific way these systems mislead people. This rule is enforced mechanically, not by asking politely.

---

## 3. The four jobs it does

### Job one — keep the book

It knows every holding across Indian stocks, US stocks, crypto and Indian mutual funds. For each: what was paid, when, how much is held now, what it is worth today, what has been made or lost, and how the whole thing breaks down by asset class, sector, geography and framework theme. It computes both the *rate of return on the money* (which measures the investor's timing) and the *rate of return on the strategy* (which measures the ideas, independent of when cash happened to arrive). It nets out the real cost of trading — the transaction taxes, exchange fees, stamp duty and depository charges that quietly eat a few tenths of a percent off every round trip — because a paper portfolio that ignores costs flatters itself.

### Job two — watch the world

On a schedule, it pulls in:

- **Prices**, delayed by fifteen or twenty minutes, which is entirely adequate for someone holding things for months.
- **Exchange announcements and filings** — the official firehose of board meetings, results, corporate actions, shareholding changes and insider trades for Indian companies, and the equivalent regulatory filings for US ones.
- **Financial press and macro events** — central bank decisions, inflation and growth prints, currency moves, sector news.
- **A small set of trusted video channels** — a handful of India-focused and global market commentators, whose new uploads are read for the stocks discussed, the argument made, and the verdict reached.
- **Anything the human throws at it** — a link, a video, a PDF, a screenshot, dropped into a single inbox with no ceremony, which the system reads, files against the relevant holdings, and treats as a research lead.

The commentators are treated as *leads, never instructions*. A stock mentioned on a channel enters the research queue; it does not enter the portfolio. Crucially, the system logs **every** stock every channel mentions — not only the ones it acted on — because otherwise it becomes impossible to ever answer the question "is this channel actually any good?"

### Job three — think, and propose

The system holds two investment frameworks as its constitution.

The first asks a structural question: *what must India build to become what it wants to be, what specific bottlenecks stand in the way, and who solves those bottlenecks?* A company that solves a bottleneck standing in the way of six national imperatives has more durable demand than one that solves a bottleneck standing in the way of one. This framework tells you **what deserves attention**.

The second asks two questions about the company itself. The Buffett half: *is this a genuinely good business at a sensible price* — does it earn well on the capital it uses, does its accounting profit turn into actual cash, is management honest, and is there a gap between what it is worth and what it costs? The Soros half: *is the market's story about this company feeding back into the company's reality* — is a high price letting it raise cheap capital and hire well, or is a falling price starving it? And is that loop building, running, peaking or breaking?

Neither framework is treated as scripture. They are the starting point, and the system is designed so that they can be revised — the scoring rules live in one place, changes to them are versioned, and every past decision remembers which version of the rules produced it. That last detail is what makes it possible to improve the frameworks without corrupting the history.

Every proposal states which framework score justified it, and every proposal must survive a set of hard rules that the AI cannot argue its way past. It cannot recommend buying a company the frameworks classify as a story without a business, or as a cheap company that is cheap for good reason. It cannot recommend anything without writing down, in advance and in checkable terms, what would prove it wrong.

### Job four — mark itself

Every position carries the invalidation conditions written at entry. The system watches for them. If a company's working capital was supposed to normalise below a threshold by a certain quarter and it does not, that is a trigger, and the trigger fires whether or not the story is still popular. If a governance event recurs at a company where governance was already the stated risk, that is a trigger.

And on a schedule, the system grades itself: which decisions worked, which did not, whether the reasoning was wrong or the outcome was just noise, which sources actually produced anything, and what should change as a result.

---

## 4. A day in its life

**Before the Indian market opens (around 8:00 in the morning).**
The system has already collected overnight: what US markets did, what happened to crude and the rupee, which of the tracked companies filed something with the exchange after yesterday's close, and what the central bank or the statistics office published. It reads all of it against the current holdings and the watchlist. If nothing material happened — and on most days nothing material happened — it writes one line into the morning brief that already goes out and does nothing else. If something material did happen to something owned, it says so, plainly, in that brief.

**Midday (around 12:30).**
A price refresh, and one narrow question: has anything owned moved sharply enough, or has an exchange filing landed important enough, that it should not wait until evening? Most days the answer is no and the system spends almost nothing. This run exists to catch the rare event — a results announcement, a rating action, a governance disclosure — not to have an opinion about the day's wiggle.

**After the Indian close (around 16:30).**
The closing prices are recorded permanently. The portfolio is marked. Every open position's invalidation conditions are checked against today's facts. Anything that fired is queued.

**Evening (around 21:00) — the one run that actually thinks.**
This is the day's real work. It gathers everything collected since yesterday evening: filings, news, any new videos from the tracked channels, anything the human dropped in the inbox, the day's price and volume action, and the state of every open position. It re-reads the theses. It scores candidates against both frameworks. It decides whether anything is worth proposing.

Then it either sends a batch of proposals as a phone notification, or it sends nothing — and the "sent nothing" is itself recorded, because a system that only logs the days it acted can never be measured against the days it should have.

**Overnight.**
While India sleeps, the US market is open. A single run after the US close (around 2:00 in the morning India time) records US closing prices and checks US positions for triggers. It can raise a proposal but usually will not; anything it finds waits politely in the queue for the evening batch unless it is genuinely urgent.

**What the day costs.** Five scheduled touches in total — one of which does the thinking and four of which are near-free bookkeeping — plus two quick checks for new videos. In round terms a normal day costs less than a cup of coffee, and almost all of that is the evening run.

---

## 5. A week in its life

Monday through Friday is the day above, five times.

**Saturday morning is the weekly review.** No market is open, nothing is urgent, and the system does the thing it cannot do on a weekday: it looks backwards. Which proposals were approved, rejected or modified this week, and why? Where are the open positions relative to their theses? Did any invalidation trigger get close without firing? How much of the month's budget is left? What is sitting in the research queue that has been sitting there too long? And it compares the portfolio's week against the benchmarks.

It writes this up and sends it. This is the artefact that is actually worth reading — the daily notifications are operational, the weekly review is where the thinking accumulates.

**Sunday it does nothing**, deliberately. There is a real risk in a system like this that it fills every available slot with output, and output is not the same as insight.

---

## 6. A month in its life

At the start of each month the deployable budget resets — ₹30,000 by default, editable — and the system re-plans. It does not spread the budget evenly across the month, because that is a savings habit rather than an investment decision. It holds capital until something crosses a price it has decided in advance is worth paying, and if nothing crosses, it says so and carries the cash forward. Unspent budget is a legitimate outcome and the system is explicitly designed not to feel bad about it.

At the end of each month it produces the monthly review, which is the weekly review plus three things a week is too short to answer:

- **Attribution.** Which decisions drove the month's return, and which sources triggered them.
- **Calibration.** When the system said it was 80% confident, was it right about 80% of the time? This is measurable, and it is the single most honest thing you can measure about a forecaster.
- **What it wants to change.** Concrete proposals to adjust its own scoring weights, thresholds, prompts or source list — which are themselves proposals, requiring approval, and which are versioned so that the effect of each change can be traced afterwards.

**Quarterly**, it does the deeper version: full framework re-scoring of every holding against fresh results, a review of whether the framework's own claims are holding up, and an honest read on whether the system is beating its benchmarks or merely tracking them.

---

## 7. The life of one decision, start to finish

This is the part worth reading twice, because everything else is scaffolding around it.

**Step 1 — Something arrives.**
At 9:40 on a Tuesday evening, an exchange filing lands. A company on the watchlist has reported quarterly results. Separately, one of the tracked channels published a video that afternoon discussing the same company.

**Step 2 — It is turned into facts, not impressions.**
The filing is read and the numbers extracted, each tagged with the document it came from. The video is read for what it claims and what it concludes, tagged as commentary — a lead with a named source, not evidence. The two are kept strictly apart. A number from a filing and a number from a commentator are different species and the system never lets them mix.

**Step 3 — It is scored.**
Three separate scores, deliberately never blended into one:

- *Structural*: which national imperative does this serve, which bottleneck does it solve, how many imperatives does that bottleneck cross, is it crisis-accelerated, and is its inflection inside the intended holding period? This score comes from a stored mapping that a human approved once — the AI can propose that a company solves a bottleneck, but that claim only becomes usable after a human agrees. This is the guard against a machine talking itself into believing a random small-cap is nationally strategic.
- *Business quality and price*: return on capital, cash conversion, whether retained profits have created value, debt, and the gap between a defensible estimate of worth and the current price. Every component is computed from filed numbers. If a number is missing, that component scores *unknown* — never zero, because a missing number silently treated as a bad number is how a good company gets rejected for no reason.
- *Narrative and reflexivity*: what story is the market telling, is the price feeding back into the business, and is that loop forming, running, peaking or breaking? This is the score the AI genuinely judges, and it is required to cite evidence for each judgement. A judgement without evidence is recorded as "unknown", not as an opinion.

They stay separate because blending them hides the thing you most need to see: that a company can be structurally essential, genuinely excellent, and still a bad purchase at today's price. That is not a contradiction to be averaged away. It is the actual finding.

**Step 4 — It must clear the gates.**
Hard rules, applied by the system, not by the model:

- If the combination of quality and sentiment places the company in the "story without a business" or "cheap for a reason" quadrants, no buy proposal is possible. Full stop.
- If there is no margin of safety, a buy is only possible in the more aggressive mode, at half the normal size, and only if the thesis says out loud that it is paying for growth rather than pretending there is a discount.
- At least two invalidation conditions must exist, each of which is a specific number, a comparison and a deadline — not a sentiment like "if the story changes".
- Every figure in the thesis must trace to a source. Unsourced figures are stripped, and if stripping them guts the argument, the proposal is demoted to a research note rather than sent.
- If a proposal on this same company was rejected recently, it cannot be re-raised unless something genuinely new has happened. The system is not allowed to nag.

**Step 5 — It becomes a proposal.**
What arrives on the phone the next evening is short and complete: the action, the amount, the expected holding period, a few sentences of thesis, the three scores, the invalidation conditions, a confidence level, and the specific things that triggered it. Behind it, permanently frozen, is everything that produced it — the prices at that moment, the documents, the scoring rules in force, and the model that wrote it. Frozen, because a record that can be edited later is worthless for judging yourself.

**Step 6 — The human decides.**
Approve, reject, or modify. Modification means changing the amount or the conditions and approving the changed version. Every outcome captures a reason in the human's own words, and that reason is data — it is how the system eventually learns what kinds of proposal keep getting turned down.

**Step 7 — Reality diverges, and that is fine.**
Approving a proposal updates the paper portfolio. If the human then does something different in the real world — buys a different amount, or on a different day, or not at all — they say so, and the two books drift apart on purpose. The gap between them is one of the most interesting numbers the system produces.

**Step 8 — It is watched.**
From that moment the position's invalidation conditions are checked whenever new facts arrive. Nothing material happens on most days and the system stays quiet. When something material does happen, it raises a fresh proposal rather than waiting for the calendar.

**Step 9 — It is graded.**
At the horizon written at entry — and again when the position closes — the system asks the question that matters: not *did it go up*, but *did the specific claims in the thesis turn out to be true?* Those are separable, and keeping them separate is the difference between learning and superstition. A thesis that was right about the business and wrong about the price teaches something. A thesis that was wrong about the business and made money teaches nothing, and pretending otherwise is how people acquire expensive habits.

---

## 8. Modes and budget

**Budget.** A monthly deployable amount, ₹30,000 by default, editable at any time. It is a ceiling, not a target. Unspent budget rolls forward and the system reports what it chose not to spend and why.

**Balanced mode** is the default and the one that should run for the whole paper period.

- Positions are sized at roughly a fifth to a third of the monthly budget each, so two to four new or added positions a month.
- No single holding grows past about a fifth of the portfolio, and no single theme past about a third.
- Only companies that clear the quality bar with a real margin of safety.
- Indian and US listed equity only for new proposals. Crypto and mutual funds are tracked and reported, but the system does not propose them — crypto because India's tax treatment of it is punitive enough to change the arithmetic of every position, and mutual funds because a monthly systematic plan is a decision made once, not a decision made repeatedly.
- Roughly a tenth to a sixth of the portfolio deliberately held as cash, to have something to deploy when a market drop makes the expensive names briefly sensible.
- A minimum conviction level, and a minimum gap between proposals on the same name.

**Hyperactive mode** exists to be *measured*, not to be lived in. It changes specific, named things:

- Larger positions, up to about half the monthly budget in one name.
- More positions open at once, and a lower conviction threshold.
- Buying without a margin of safety becomes possible — at half size, and only with the thesis stating explicitly that it is buying growth.
- Concentration limits loosen.
- Reaction time shortens: a material event can produce a proposal within the hour rather than waiting for the evening.
- Smaller, less liquid and more speculative names become eligible, within a cap on how much of the portfolio they can collectively occupy.

The honest reason to have two modes is not flexibility. It is that running both books in parallel — the same signals, two sets of rules — measures whether the extra risk buys anything. The strong prior is that it does not, and the system is designed to make that finding visible rather than arguable.

---

## 9. The what-if book

Alongside the real paper portfolio, a second ledger records decisions that did not happen, and tracks them with identical arithmetic.

Three things go into it:

- **Proposals rejected by the human.** This measures the cost of the vetoes.
- **Proposals the budget could not fund.** This measures the cost of the constraint.
- **Proposals blocked by the system's own gates** — the ones the rules refused to let through. This measures the cost of the rules, and it is the most valuable of the three, because it is the only way to find out whether the safety rails are protecting or merely obstructing.

Each entry carries the same thesis, the same invalidation conditions and the same horizon, and is marked at the same prices as the real book.

Read carefully, this ledger will eventually answer three questions with numbers instead of feelings: *does the human's judgement add to or subtract from the machine's?*, *what has the budget cap cost?*, and *are the guardrails paying for themselves?*

A warning that belongs here rather than in the risks section: this ledger will be seductive. Rejected ideas that went up are far more memorable than rejected ideas that went down, and a shadow book read casually will train worse judgement, not better. It should be read as a whole, in aggregate, on a schedule — never dipped into after a name that got away.

---

## 10. How performance is measured — and how we tell skill from luck

### The four benchmarks

One benchmark is not enough, because a single comparison can be beaten for uninteresting reasons.

1. **The market**, measured properly — the index *including dividends*, not the headline index. The headline number understates the real alternative by more than a percent a year, and comparing against it is a way of winning by accounting.
2. **Buy everything it ever proposed, and never sell.** Take every buy the system suggested, weight them equally, hold forever. If the actual portfolio cannot beat this, the system has ideas but no timing — a genuinely useful thing to find out.
3. **The real-world portfolio.** The whole point.
4. **The what-if book.** Described above.

### The honest problem with measuring returns

At roughly ₹30,000 a month and two to four decisions in it, the system will produce something like thirty to forty-five decisions in a year.

That is not enough. Not close. The conventional statistical floor for saying anything at all about a strategy is about thirty observations, and that is a floor rather than a standard; serious practice wants two hundred to five hundred, spread across different market conditions. Thirty-five decisions in a single year, in a single market regime, is a sample from which no honest conclusion about skill can be drawn. Worse, the imprecision in a return-quality measure like the Sharpe ratio is so large over one year of monthly data that a genuinely good strategy and a mediocre one are statistically indistinguishable.

Anyone who tells you otherwise — including this system, if it ever starts to — is selling something.

### So measure the process instead

There is a much larger sample hiding in plain sight. Each thesis makes three to five specific, falsifiable claims. Each position carries two or more invalidation conditions. Each proposal carries a confidence level. Over a year that is a few hundred checkable predictions rather than thirty-five outcomes — enough to say something real, within months rather than decades.

Four measures, all of which reach usable sample sizes quickly:

- **Claim accuracy.** Of the specific things the theses asserted would happen, what fraction happened? This is the closest thing to a direct measure of whether the reasoning works.
- **Calibration.** When it says 80%, is it right 80% of the time? Overconfidence is the most common and most correctable failure of a system like this, and it shows up here first.
- **Trigger discipline.** When an invalidation condition fired, did the system act — and was acting right? A system that writes invalidation conditions and then rationalises past them has quietly stopped being a system.
- **Source precision.** Of the ideas each source produced, what fraction cleared the frameworks, and what fraction of those worked? Measured against *everything* that source said, not just what was acted on.

### The criterion for real money

Not "it beat the index". A specific, pre-committed rule, written now so it cannot be softened later:

- **At least twelve months** of continuous operation, and **at least two distinguishable market conditions** within them. A year that is entirely one long rise proves nothing.
- **At least forty completed decisions**, understanding that even this is a small sample and the conclusion is provisional.
- **Calibration within tolerance** — confidence levels that broadly match outcomes, not systematically overconfident.
- **Claim accuracy meaningfully better than a coin flip** on the falsifiable claims, over at least a hundred and fifty claims.
- **Trigger discipline near-perfect.** This one is not statistical. If the system ignored its own invalidation conditions even a few times, it does not get real money regardless of returns.
- **Return above the dividend-inclusive index**, net of modelled costs and taxes — a necessary condition, but deliberately the *last* one on the list, and the least informative.

And even when all six are met, the sane move is a small fraction of capital, run alongside, for another year.

---

## 11. What the system will and will not do

**It will:**
keep the book across four asset classes; fetch prices on a schedule; read exchange filings and financial press; read the tracked channels and anything dropped into the inbox; score against both frameworks; propose specific actions with sizes, horizons, theses, scores, invalidation conditions and confidence; batch those into notifications; watch open positions continuously and raise unscheduled proposals when something genuinely material happens; track the shadow book; keep an immutable record of everything; and grade itself weekly, monthly and quarterly.

**It will not:**
connect to any brokerage, place any order, or see any real holdings. Trade intraday, or hold an opinion about the next few hours. Propose crypto or mutual fund positions in the first version. Compute tax liability or file anything — it flags tax consequences, it does not do tax. Manage a second portfolio or a second person. Provide advice to anyone but its single user. Be published, shared, or turned into anything anyone else can read — India's regulator has been active on unregistered investment advice and automated advisory tools, and a private research tool becomes a regulated activity the moment its output reaches a third party.

**It will not, most importantly:** produce a number it cannot point to a source for. If it does not have the figure, it says it does not have the figure.

---

## 12. Risks and limitations, stated plainly

**It can be confidently wrong, and it will sound the same either way.** A language model writes a well-argued thesis with fabricated figures in exactly the register it uses to write a well-argued thesis with real ones. The published benchmarks on this are bleak — leading models answering questions about real company filings with a document-retrieval setup have been measured failing four times out of five, and even with the full document in front of them failing around a fifth of the time. That is the reason for the rule that the model never produces a figure. The rule is load-bearing, and if it is ever relaxed for convenience the whole thing becomes untrustworthy in a way that is very hard to detect from the outside.

**Its historical judgement is contaminated.** A model trained on text up to a certain date already knows what happened to most companies before then. Ask it to evaluate a stock as of a past date and part of what looks like reasoning is recall. This has been measured, and the memorisation component is a substantial fraction of the apparent skill. The practical consequence: any backward-looking test of this system is worth much less than it appears, and only genuinely forward-looking paper performance counts. That is precisely why the plan is months of live paper trading rather than a backtest.

**It will chase narratives, because narratives are what it reads.** It ingests news and commentary, which are made of stories. Recent and loud will be over-weighted relative to slow and quiet. The structural framework is the counterweight — it is deliberately slow-moving and human-approved — but the pull is real and permanent.

**It will want to trade more than it should.** A system that runs every day and produces proposals will find reasons to produce proposals. Every real cost of activity — transaction taxes, fees, the short-term tax rate being nearly double the long-term one, and the well-documented tendency of active retail trading to underperform — argues for doing much less. The cooling-off periods, the minimum conviction thresholds and the explicit permission to spend nothing all exist to fight the system's own bias toward motion.

**Reviewing the past is where self-deception lives.** Once an outcome is known, the reasons it was obvious appear in hindsight. The only defence is that the reasoning was frozen before the outcome existed, and that the record cannot be edited. This is why the permanence of the record is not a technical nicety.

**The data will be wrong sometimes, and quietly.** A price feed returns a stale number; a company splits its shares and the price halves overnight with no corresponding fall in value. If a corporate action is missed, the portfolio will show a fifty percent loss that did not happen, an invalidation condition may fire on that phantom loss, and the system may propose selling a position for no reason whatsoever. This is the single most likely path to the system doing real damage, and it is guarded specifically: corporate actions are ingested from the exchange, and profit-and-loss on an affected holding is suspended until the action has been applied.

**Sources will be judged on too little evidence.** With a handful of channels and a few dozen ideas a year, source scoring will be noisy for a long time. It should be read as a diary, not a verdict, until the counts are genuinely large.

**Currency will flatter or punish it undeservedly.** A US holding gains from a falling rupee even if the stock does nothing. Returns are decomposed into asset movement and currency movement so the system cannot take credit for the exchange rate.

**Tax is not symmetric and not neutral.** In India, selling a listed share held for under twelve months is taxed at a materially higher rate than one held past it. Crypto is taxed at a flat rate with losses that cannot be set off against anything. Holdings in US shares carry a separate holding-period rule and an annual disclosure obligation with severe penalties for omission. A system that proposes trades without surfacing these will systematically propose bad ones.

**The machine it runs on is small.** The server is modest and its disk is already three-quarters full. This is not a footnote — it forces real discipline about what is stored. Minute-by-minute price history, full documents and full video transcripts are all excluded by design, not by oversight, and the module carries a hard storage budget.

**There is no database backup today.** Everything above is worthless if the record can vanish. Backups ship before this does.

---

## 13. What is deliberately not in the first version

Cutting is the hardest and most valuable part of a plan, so here it is explicitly.

- **Seven daily runs, reduced to four.** For a months-to-quarters horizon, a run thirty minutes after the open exists to satisfy anxiety, not to inform decisions. Every additional run costs money, adds an interruption, and increases the chance of reacting to noise.
- **Market and sector regime assessment.** Breadth, valuations, institutional flows, sentiment indices — a lot of plumbing for a signal that would be used qualitatively at best. Second version.
- **Crypto and mutual fund proposals.** Tracked from day one, proposed on later or never.
- **Screenshot ingestion of broker dashboards.** Typing "bought 3 Apar at 13,400 today" is faster, more reliable and less prone to silent misreading than photographing a screen. Screenshots arrive once the plain-language path is solid, and even then every parsed transaction is shown for confirmation before it is written.
- **Statistical source attribution.** The logging starts immediately, because the data cannot be reconstructed later. The scoring waits until the counts justify it.
- **AI-written narrative reviews.** The first version computes the numbers and shows them. The essay about what they mean comes once there is enough history for the essay to be about something.
- **Automatic self-tuning.** The system proposes changes to its own weights and thresholds; it never applies them. A system that silently rewrites its own scoring rules destroys the comparability of its own track record.

---

## 14. The honest summary

This is a system for finding out something specific: **whether a disciplined, framework-driven, fully documented research process — executed by a machine that reads far more than a human can — produces better decisions than the human would have made alone.**

It answers that question slowly, on paper, with an audit trail, and with the arithmetic honest about costs and taxes. It is designed to make the answer "no" easy to see, which is the only design that makes the answer "yes" worth believing.

The most valuable thing it produces in its first year is almost certainly not returns. It is the record — a few hundred written, timestamped, unchangeable predictions and the reasoning behind each. That record is what makes the second year worth running, and it is the thing that cannot be bought, backfilled, or hurried.
