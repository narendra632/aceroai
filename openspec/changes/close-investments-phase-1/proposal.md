# Close Investments Phase 1

## Why

Phase 1 of the build spec — "the honest ledger" — shipped and is live, but three of its items
were left undone, and re-reading the spec against the code made the gaps precise.

1. **Corporate actions were announced and never recorded.** The feed was read every evening
   and a notification sent; nothing was stored, nothing could be applied, and nothing could
   flag the holding. That leaves the module's **highest-damage failure mode** wide open: a 1:1
   bonus halves the quoted price overnight, so until the ledger knows, the page reports −50% on
   a holding that lost nothing. Phase 2's gate **G7** is built on a stored action and cannot be
   written without one.

2. **Schedule FA was never captured.** We hold SPCX. Every resident holding a foreign security
   declares it with **no minimum threshold**, and the return wants the **peak value during the
   calendar year** — which can only be known by something that recorded the value on every day.
   The spec assumed this had to be captured at transaction time; since the price feeds landed
   it can be read from the record instead, which is strictly better. Every week it stayed
   unbuilt was a week of 2026 that would have been harder to reconstruct.

3. **The 250 MB storage budget was unmeasured.** A budget nobody measures is a wish, on a disk
   already three-quarters full.

A fourth thing was found while building the first: `_rescale_unit_costs` gave every lot the
book's average cost after a split or bonus. It conserved the total and destroyed what lots are
for — two HDFC Bank lots at ₹960 and ₹722 would become ₹420 twice instead of ₹480 and ₹361, so
every FIFO disposal afterwards would report the wrong realised gain. Invisible until now
because nothing had ever applied one.

## What Changes

- **`corporate_actions`, a stored row rather than a message.** One table (migration 017), not
  append-only — an action is a thing being *tracked* and moves PENDING → APPLIED / IGNORED /
  NEEDS_REVIEW. What it *did* to the book stays an append-only transaction, which
  `applied_txn_id` points at.

- **A parser that refuses.** `BONUS 1:1` and `FACE VALUE SPLIT FROM RS.10/- TO RE.1/-` are
  read. A bare `SPLIT 1:10` is **not**: it does not say which side is the old face value, and
  the two readings differ by a factor of a hundred. Unreadable announcements become
  `NEEDS_REVIEW`, which flags the holding and waits for a person. ⚠ The confident wrong answer
  is a larger fiction than the one being fixed.

- **Applied on the ex-date**, as an ordinary ledger entry with `entry_source='CORP_ACTION'`,
  conserving total cost basis and each lot's own per-unit cost. Offered as a button too, and
  undone by the existing correction path — the ledger is the user's word, so an entry made on
  their behalf must be visible and reversible.

- **Gate G7 on the page.** While an action is outstanding the holding is flagged and its P&L
  is stated as not yet reliable. This is why it is a row: a notification can be dismissed while
  the number it was about stays on screen.

- **Schedule FA as a reading, not a store.** `schedulefa.report` walks stored observations for
  one calendar year per foreign security: acquisition date, initial value, peak (with its day),
  closing value, income, proceeds — with **coverage reported beside them**. ⚠ Converted at the
  rate recorded, not SBI's TT buying rate; every figure names its day so the right rate can be
  looked up.

- **`investments_disk_watch`**, weekly, reporting the module's tables against the spec's
  250 MB budget with a warning at 200 MB.

## Impact

- `investments` — corporate actions, foreign-holding disclosure, the lot-cost correction
- `scheduled-jobs` — `corporate_actions_watch` rewritten; `investments_disk_watch` added
- `ui-standards` — two new cards on the Investments page

Not touched: the returns, the fold's other paths, any price source, any assistant tool.
