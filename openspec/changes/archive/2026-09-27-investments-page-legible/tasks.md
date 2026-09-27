# Tasks

## 1. Backend — what the page needs

- [x] 1.1 `scoring.Part.value`: the margin of safety as a fraction; `PartOut.value`
- [x] 1.2 `watching.Measure.needed`: the sample a measure waits for; `MeasureOut.needed`
- [x] 1.3 `frameworks.place` / `frameworks.suggest_place`: an unapproved mapping for a
      followed company that has none, by hand or proposed by the model from what sources said
- [x] 1.4 `POST /framework/instruments/{id}/place` and `/suggest`; refuse a company that is
      already mapped
- [x] 1.5 `GET /attention`: every waiting item with tab, severity, symbol and words
- [x] 1.6 Tests for all of the above, including that a suggestion goes through the billed path
- [x] 1.7 The assistant's description of the page names the six tabs

## 2. Frontend — a shared kit

- [x] 2.1 Status tokens `--good` `--caution` `--bad` `--info` in light and dark
- [x] 2.2 `Section` (remembered, accessible, headline while closed), `Meter`, `Chip`,
      `Callout`
- [x] 2.3 `TabsTrigger` with icon and count; remembered "framework" opens Companies

## 3. Frontend — each tab

- [x] 3.1 Page: needs-you strip and tab counts from `/attention`, refreshed after any action;
      compact inbox result with a way to the item
- [x] 3.2 Holdings: one summary card; weight column; chart as a Section
- [x] 3.3 Decisions: fired → suggestions → worth a look → themes → refusals grouped → decided
- [x] 3.4 Companies: compact rows with bars and chips, filters, expand for the full reading;
      needs-you callout that places, suggests, and opens
- [x] 3.5 Sources: its own tab
- [x] 3.6 Scorecard: criteria, index comparison, prediction record with progress; books and
      reviews closed
- [x] 3.7 Records: transactions first, confirmed reversal; Schedule FA
- [x] 3.8 Checked in a real browser at desktop and phone width, dark and light

## 4. Close

- [x] 4.1 Handbook updated wherever the page changed
- [x] 4.2 `ruff format`, full `pytest`, `npm run build`, `npm run lint`
- [x] 4.3 Archive
