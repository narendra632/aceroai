# Tasks

## 1. The record

- [x] 1.1 Migration 020: proposals, decisions, invalidation_triggers, claims, shadow_entries,
      agent_runs. Four append-only at the database
- [x] 1.2 ⚠ `proposals.status` holds only what the SYSTEM decided; the effective state is
      derived from `decisions`, so the two cannot disagree
- [x] 1.3 `decisions.reason_text` NOT NULL with a non-empty CHECK — the reason is the data
      that reveals what keeps being turned down
- [x] 1.4 `price_snapshot`, `gate_results` and `input_refs` frozen onto every proposal
- [x] 1.5 Verified upgrade → downgrade → upgrade

## 2. The gates

- [x] 2.1 G1 framework, G2 quadrant, G3 margin of safety, G4 invalidation conditions,
      G6 cooling-off, G7 corporate action, G8 price age, G9 volume, G11 confidence
- [x] 2.2 ⚠ Every rule answers, not just the first refusal — a near miss and a company that
      should never have been considered are different findings
- [x] 2.3 ⚠ `not_applicable` distinct from `passed`: counting them together overstates how
      much was checked
- [x] 2.4 G2 has no override. A gate that yields to a strong enough thesis yields exactly when
      the thesis is most persuasive
- [x] 2.5 ⚠ The off-framework ceiling counts EQUITIES only. Found live: counting crypto and
      the funds put it at 39.8%, eight times its ceiling
- [x] 2.6 The ceiling governs what may be ADDED, never retro-blocking what is held

## 3. The loop

- [x] 3.1 `draft_for` — thesis, triggers and claims assembled from filed figures alone
- [x] 3.2 ⚠ Confidence derived from coverage, not chosen. It is the number calibration is
      measured against, and a figure a model picked measures the model's mood
- [x] 3.3 Sizing clamps to one share; `ACCUMULATE_POOL` where a share costs more than the
      ceiling, because India has no fractional equity
- [x] 3.4 ⚠ Every judgement formed BEFORE anything is written — the append-only trigger refused
      an `agent_runs` row opened at the start and closed at the end, which is the guard working
- [x] 3.5 A blocked proposal is written with its blocker and shadowed
- [x] 3.6 Approving arms the conditions; rejecting writes the veto book

## 4. Deciding

- [x] 4.1 `effective_status` derived — PENDING · APPROVED · REJECTED · MODIFIED · EXPIRED ·
      BLOCKED
- [x] 4.2 A decision needs a reason, enforced by the database
- [x] 4.3 A lapsed suggestion cannot be acted on: it was made at a price now history
- [x] 4.4 One decision per proposal, enforced by a unique constraint

## 5. The run

- [x] 5.1 `evening_synthesis`, 21:00 daily, idempotent through `occurrence_key`
- [x] 5.2 ⚠ Silent when it suggests nothing, but the run is recorded either way
- [x] 5.3 One notification at most, naming the first suggestion

## 6. Over the wire, and on the page

- [x] 6.1 `GET /api/investments/proposals`, `POST .../decide`
- [x] 6.2 `ProposalsPanel` — the argument, what would prove it wrong, what it claims, and the
      refusals on request
- [x] 6.3 The reason field is required before either button enables

## 7. Proof

- [x] 7.1 `test_investments_proposals.py` — 24 tests, every gate against a case it must refuse
- [x] 7.2 The append-only guarantee checked at the database, not assumed
- [x] 7.3 Teardown purges the decision layer in foreign-key order
- [x] 7.4 Full suite: 1001 passed, 5 skipped. Was 975.
- [x] 7.5 Run against the REAL book: 11 considered, 0 proposed, every refusal specific

## 8. The watching half

- [x] 8.1 `watching.check_triggers` — every armed condition against today's price and today's
      filed figures
- [x] 8.2 ⚠ A condition nothing can evaluate is UNEVALUATED, not satisfied. Counting it as
      passed reports a clean bill of health nothing ever checked
- [x] 8.3 A condition past its window expires rather than lingering — left armed it would fire
      years later on an unrelated movement and read as the original thesis failing
- [x] 8.4 `watching.resolve_claims` — settles every claim whose deadline has passed
- [x] 8.5 ⚠ A claim that cannot be checked is UNVERIFIABLE, never false. Otherwise claim
      accuracy measures data coverage rather than judgement, and the two become inseparable
- [x] 8.6 Four measures: claim accuracy, calibration (Brier), trigger discipline, decision
      record — each reporting its sample size
- [x] 8.7 ⚠ No figure below `MIN_OBSERVATIONS`. A precision over six outcomes reads exactly
      like one over six hundred, and no caveat fixes that
- [x] 8.8 ⚠ Trigger discipline reports from the FIRST firing. A single ignored condition is a
      finding, not a data point
- [x] 8.9 `position_watch` job, weekdays after the close, and a firing always notifies
- [x] 8.10 Migration 021: the claims guard narrowed rather than dropped — the PREDICTION is
      frozen, the outcome may be recorded, and DELETE is refused outright
- [x] 8.11 Fired conditions and the measures on the page, above the suggestions
- [x] 8.12 `test_investments_watching.py` — 21 tests. Full suite 1022.

## 9. Deployment

- [ ] 9.1 Pushed; migrations 020 and 021 run on the server
- [ ] 9.2 Verified in production

## 10. Owed at the end of Phase 2

- [x] 10.1 **The walkthrough** — `docs/INVESTMENTS-WALKTHROUGH.md`. The eight layers, the
      arithmetic with worked examples from the real book, six simulated scenarios, how the
      system will be judged, and what is not built. Written to be read once and kept
- [x] 10.2 Schedule FA coverage counts days HELD, not days in the period. "Priced on 97 of
      263 days" for a share bought in June read as a hole in the record when the truth was
      that it was not owned yet — a figure that cannot tell "not owned" from "not recorded"
      reports a fault that does not exist
- [ ] 10.3 The six model-judged flags, with source ingestion
- [x] 10.4 Trigger evaluation on a schedule — done in section 8
- [x] 10.5 Claim resolution and the measures that rest on it — done in section 8
