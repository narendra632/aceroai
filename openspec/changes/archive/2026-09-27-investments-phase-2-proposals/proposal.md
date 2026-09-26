# Investments Phase 2, stage 4 — proposals, and the rules that refuse them

## Why

Everything before this describes. Nothing recommends. Acero could say a company clears a
national bottleneck, that its return on capital is 29%, and that it is trading at four times a
defensible worth — and then stop, leaving the reader to join those up.

This stage closes the loop the whole module exists for: **write down a judgement before anyone
knows how it turns out, with the specific things that would prove it wrong, and keep the
refusals as carefully as the suggestions.**

## What Changes

- **Six tables** (migration 020). `proposals` is what was suggested; `decisions` is what the
  human did; `claims` and `invalidation_triggers` are the falsifiable halves; `shadow_entries`
  holds what did not happen; `agent_runs` records every evening, **including the ones that
  suggested nothing**.

- **The gates, in Python and never in a prompt.** A gate a sufficiently persuasive argument can
  talk its way past is a preference. The whole point of writing rules down in advance is that
  they bind on exactly the day you would rather they did not, so no instruction anywhere asks a
  model to respect them.

- **A refusal is written down too**, with the rule that blocked it, and entered in the shadow
  book. A rule whose cost is invisible is a rule nobody can evaluate.

- **`evening_synthesis`** — the one scheduled run that thinks. Notifies at most once, and only
  when there is something to decide.

- **A proposals panel** showing the argument, what would prove it wrong, what it claims, and —
  on request — what the rules refused.

## Two contradictions the database caught, not me

**`agent_runs` opened at the start and closed at the end.** The append-only trigger refused the
update, which is the guard working. Fixed by forming every judgement *before* writing anything,
which also means a run that fails halfway writes nothing rather than half a batch plus a record
claiming the evening completed.

**`proposals.status` was editable on an append-only table.** The effective state is now derived
from `decisions`, so the two cannot disagree — and the stored column holds only what the
*system* decided as it wrote the row.

## The bug found by running it against the real book

The off-framework ceiling counted crypto and the mutual funds, which have no framework mapping
because the framework was never about them. The share came out at **39.8%** — eight times its
ceiling — and every equity outside the framework was blocked by a rule measuring something
else entirely. It now counts equities only: 19.3%, which is SpaceX, which is correct.

## What it actually says today

Run against the real book, the system proposes **nothing**, and every refusal is specific:

- **GE Vernova** — blocked by the price. *"335% above a defensible worth of 28×."* That is the
  framework's own central finding — structurally essential, genuinely excellent, and still a
  bad purchase — reached independently from filed accounts.
- **Nine others** — blocked because too little of their accounts has been read to say which box
  they are in. Honest, and it resolves as the price backfill completes.
- **Rolex** — blocked because the off-framework ceiling is already used by SpaceX.

That is the correct output, not a gap.

## Impact

- `investments` — proposals, gates, decisions, triggers, claims, shadow books
- `scheduled-jobs` — `evening_synthesis`
- `notifications` — a new kind carrying a decision
- `ui-standards` — the proposals panel

No model is invoked in this stage either. The thesis is assembled from filed figures, which
means it cannot contain a number that was never filed — the one failure that would make the
whole record worthless.
