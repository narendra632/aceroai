# Make the Investments page legible to someone learning

## Why

The page is correct and hard to use. Every figure on it is honest, and a beginner opening it
cannot tell what matters, what needs him, or where to look. Measured on 27 Sep 2026 against
the live book, tab by tab:

1. **A tab you open shows nothing.** Framework opens to a heading, a version number and two
   links; the twelve company cards sit behind **Show**. Scorecard opens to four headings each
   saying **show**. A tab is already a deliberate choice — hiding its content a second time
   makes the reader click twice to see anything, and a collapsed heading says nothing about
   what is under it.
2. **Nothing says where the work is.** "1 company needs your agreement" lives in the third
   tab; "1 channel waiting for you" is a badge inside a collapsed panel at the bottom of the
   same tab. The tab bar gives no sign of either. The only way to find what needs you is to
   open every tab.
3. **A dead end.** BHARTIARTL was followed without first being read, so it has no place in the
   framework. The page says it "needs your agreement" and offers **Review them** — which opens
   a list it is not in. No control anywhere can place a company that has no mapping.
4. **Everything is the same weight.** A condition that disproved a thesis, a company waiting
   for agreement and a 40-row list of refusals are all small grey text in the same card
   style. Scores are "7 of 9 measurable" in 12px text; flags are "flag 6: yes"; the verdict
   that blocks a purchase is a lowercase phrase at the end of a line.
5. **Six different show/hide controls.** An underlined "show", a "Show" button with a chevron,
   a `<details>` summary, a "hide" link, a "Review them" button, and panels with no toggle
   at all. None remembers its state and none announces itself to a screen reader.
6. **Things in the wrong place.** "How it is doing" (whether the predictions come true) sits
   on Decisions, which is about acting today; sources — which the user now manages himself —
   are hidden under the framework; the filed-inbox result stays pinned above every tab.
7. **One destructive click.** **Reverse** on a transaction writes a reversing entry into an
   append-only ledger on a single click, with no confirmation.

## What Changes

- **One collapsible Section, used everywhere.** Header always shows its headline (a count, a
  figure, a state) so a closed section still says what is inside; open state remembered per
  viewer; `aria-expanded`/`aria-controls`; the whole header is the control. What a tab exists
  to show is open by default; history and reference material start closed.
- **Visual weight follows importance.** A small shared kit: `Meter` (x of y as a bar with an
  accessible value), `Chip` (tone + icon, never colour alone), `Callout` (alert / attention /
  info). Status tones become design tokens (`--good`, `--caution`, `--bad`, `--info`) with
  dark-mode steps, instead of hand-picked Tailwind colours per file.
- **The page says what needs you.** A new `GET /api/investments/attention` returns every item
  waiting on the user with its tab and severity. The tab bar shows a count on each tab that
  has something; a "Needs you" strip under the inbox lists them in words, each with a button
  that goes there. Nothing waiting → no strip.
- **Six tabs, each named for what is in it.** Holdings · Decisions · Companies (was
  Framework) · Sources (new — was a collapsed panel at the bottom of Framework) · Scorecard ·
  Records. Icons on each. A remembered "framework" tab opens Companies.
- **Holdings:** one summary card (value, gain, invested, realised, both returns, allocation
  bar, crypto line) instead of seven blocks; per-holding weight moves into the table as a
  column, removing a duplicated list; the chart is a Section.
- **Decisions:** fired conditions → suggestions → worth a look → themes, then refusals
  grouped by rule and by company (40 rows become "mostly: the price") and past decisions,
  both closed. Suggestion cards get a clear hierarchy; the dismiss reason opens under the row
  it belongs to.
- **Companies:** every company visible as a compact row — two score bars, the verdict as a
  coloured chip, the price against worth, the red-flag count — expanding to the full reading.
  Filters: all / held / watchlist / needs you. The needs-you callout acts in place.
- **A company with no place can be placed.** `POST .../framework/instruments/{id}/place`
  (you choose a bottleneck, or outside the framework) and `.../suggest` (the model proposes
  one from what sources said, through the billed path). Both write an **unapproved** mapping:
  the rule that nothing scores until you agree is unchanged.
- **Sources:** its own tab — what it reads (with switches), add a channel, what was heard,
  each source's record.
- **Scorecard:** open by default — the six criteria, the index comparison as two numbers side
  by side, and the prediction record (moved from Decisions) as progress towards the sample it
  needs. The books and past reviews stay closed (read on a schedule, not browsed).
- **Records:** transactions first, with a confirmation before a reversal; Schedule FA below.
- **Two structured fields** so the page stops parsing sentences: `Part.value` (the margin of
  safety as a number) and `Measure.needed` (the sample a measure waits for).
- **The handbook** is updated wherever the page changed; the assistant's description of the
  page names the new tabs.

## Out of scope

- No figure, rule, gate, threshold or score changes. This is presentation and one missing
  control.
- No new frontend dependency. Everything is built from what is already installed.

## Impact

- Backend: `api/investments.py` (attention, place, suggest, two output fields),
  `services/investments/frameworks.py` (placement), `scoring.Part.value`,
  `watching.Measure.needed`, `core/composer.py` (tab names). New tests.
- Frontend: a new `components/investments/` kit; every Investments panel rewritten on it;
  `ui/tabs.tsx` gains icon and count; `index.css` gains status tokens.
- Docs: `docs/INVESTMENTS-WALKTHROUGH.md`.
