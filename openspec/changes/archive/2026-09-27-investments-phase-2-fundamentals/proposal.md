# Investments Phase 2, stage 2 — filed numbers, and what they say

## Why

The framework can say which companies deserve attention. It cannot say whether any of them is
a good business, or whether today is a sensible day to buy one, because nothing in the system
had ever read a company's accounts.

The research pass found the source: every NSE-listed company files its results in XBRL and NSE
publishes those files at open URLs needing no key. This is the only source in the module where
the figure the system uses and the figure the company filed are **the same characters** — which
is what makes the rule that a model never produces a number enforceable rather than hopeful.

## What Changes

- **An adapter over NSE's results feeds**, carrying four traps found by calling it live rather
  than by reading documentation. Each would have produced confident wrong numbers: the symbol
  must be URL-encoded (`GVT&D` unescaped ends the query parameter); governance filings share
  the feed and parse perfectly while carrying no financial line; contexts must be resolved by
  their period dates (Kaynes' March file reports revenue for the quarter **and** the year under
  one tag — wrong by four, silently); and dimensional contexts must be dropped or a single
  segment's revenue is read as the company's.

- **Consolidated preferred, standalone fallback.** GE Vernova files only standalone because it
  has no subsidiaries. Requiring consolidated left the portfolio's widest-bottleneck holding
  with no financials at all, and the failure read as "this company does not report".

- **`source_items` and `fundamentals`**, both append-only. The literal filed lines are stored
  because an echo check needs the words; the document is not, because filings are 200 KB
  against a 250 MB module budget.

- **Two vocabularies, chosen by content.** A bank files `InterestEarned` where an industrial
  files revenue, and its equity as `Capital` + `ReservesAndSurplus`. The filename declares the
  taxonomy only from the Integrated Filing framework onward, so matching on the filename read
  every earlier bank filing with an industrial's map and found nothing at all.

- **The quality score**, entirely arithmetic. Return on equity and capital, cash conversion,
  balance sheet, margin of safety — every figure from a filing, every component carrying the
  filings it rested on.

- **Four of the ten reflexivity flags**, computed rather than judged: falling returns, margins
  slipping while revenue scales, a multiple outrunning earnings, and the 52-week range. Two of
  them override any later model verdict, because a measurable thing should not be a matter of
  opinion. The remaining six need a model reading news and arrive with source ingestion.

## Three refusals this stage is really about

**A missing input is `None`, never zero.** A company marked poor because its filings had not
been read is indistinguishable, from the outside, from a company that is poor. So `earned` and
`available` are reported together and the interface renders an absent input as "—".

**One year does not answer a five-year question.** The rule is "at or above 15% in three of the
last five years"; with one year read it cannot be satisfied, so scoring it zero is
arithmetically right and epistemically wrong.

**A thin reading never convicts.** Two of the four quadrants hard-block a purchase. Blocking a
company because its accounts have not been read yet would be a pipeline failure wearing the
clothes of a judgement.

## Impact

- `investments` — fundamentals, the quality score, the measured flags
- `market-data` — the NSE XBRL adapter
- `scheduled-jobs` — `fundamentals_sync`
- `ui-standards` — the score on the framework panel

No model is invoked anywhere in this stage.
