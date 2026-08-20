# Tasks

Findings get recorded inline as work proceeds, with ⚠ wherever a premise turns out to be
wrong. A task that cannot be done as written is annotated, never quietly ticked.

## 0. Confirm the premises before building on them

- [ ] 0.1 Re-run the dedup measurement and confirm `AI-901` vs `AI-103` is still **0.098**
      and `AI-901` vs `AI-103 exam and received…` still **0.115** — both under the 0.12
      threshold. If the numbers moved, the whole of Decision 3 needs re-arguing
- [ ] 0.2 Confirm both `"The user has sisters."` and `"Narendra has sisters."` are still
      active — the same threshold failing in the opposite direction
- [ ] 0.3 Confirm no tool writes memory today (7 tools, none touching `profile_facts`)
- [ ] 0.4 Re-measure the recall band and confirm a 0.40 floor would still return **zero**
      facts for `"where do I work"`. This is the number that killed the floor-only design
- [ ] 0.5 Check whether `to_tsvector('english', fact)` is accepted as an immutable
      expression index on this Postgres build; if not, a generated column is needed and
      Decision 5 changes
- [ ] 0.6 Measure the added latency of the lexical query against the recall time budget
      (`memory_recall_timeout_s`, 4 s) — record the number, do not assume it is free

## 1. One writer

- [ ] 1.1 `services/memory.remember(db, user, fact, category, *, source, source_ref,
      replaces, confidence)` — validate, embed, dedup-judge, store or supersede. Returns
      what it did (`stored` / `superseded` / `flagged`), never a bare bool
- [ ] 1.2 `services/memory.correct(db, user, fact_id, new_text, ...)` — supersede, re-embed,
      record as `stated`
- [ ] 1.3 `services/memory.forget(db, user, fact_id)` — soft delete, reusing the existing
      `deleted_at` path so Restore keeps working
- [ ] 1.4 Move the dedup judgement out of `core/memory._store` into the service so there is
      exactly one implementation *(Decision 1)*
- [ ] 1.5 `core/memory.extract_and_store` calls `services.memory.remember` instead of
      writing directly. Behaviour on the background path must be unchanged except that a
      near-duplicate is now stored-and-flagged rather than dropped
- [ ] 1.6 Test: the extractor and the tool produce an identical row for identical input —
      the guarantee that there is one writer

## 2. Stop the silent discard

- [ ] 2.1 Add `possible_duplicate_of` (nullable FK) to `profile_facts` — migration 010
- [ ] 2.2 No-hint + distance under `NEAR` → store, flagged. **Never drop** *(Decision 3)*
- [ ] 2.3 `replaces` hint → supersede, history preserved
- [ ] 2.4 **Regression test, named for the bug:** two certifications differing only in their
      code (`AI-901` / `AI-103`) both end up stored and active. This test is the reason the
      change exists
- [ ] 2.5 Test: a genuine reword ("I work at TCS" after "Narendra works at TCS") still
      supersedes rather than duplicating
- [ ] 2.6 Surface the flag on the Knowledge page — a fact suspected of duplicating another
      is visible and mergeable, not silently identical

## 3. Deliberate writes

- [ ] 3.1 `remember_fact` tool — schema + handler calling `services.memory.remember`
- [ ] 3.2 `correct_fact` tool
- [ ] 3.3 `forget_fact` tool
- [ ] 3.4 Tool results are structured and honest: `{"ok": true, "action": "stored", "id":…}`
      or an explicit failure. **The model must never be able to report a write that did not
      happen** — that is defect B
- [ ] 3.5 `SOUL.md`: when the user asks to remember/correct/forget something, use the tool;
      do not claim to have stored anything otherwise
- [ ] 3.6 **Announce destructive actions** in the reply *(Decision 6, Narendra's choice)*
- [ ] 3.7 Test: "remember that I have the AI-901 certification" results in a stored,
      recallable fact — the exact exchange that failed
- [ ] 3.8 Test: a tool failure surfaces as a failure to the model, not as silence

## 4. Hybrid recall

- [ ] 4.1 Migration 010 (same migration as 2.1): GIN index on `to_tsvector('english', fact)`
- [ ] 4.2 `_tsquery()` — OR of individually sanitised terms, stop-words dropped, capped at 8.
      **Never interpolate user text into a tsquery** *(Decision 5)*
- [ ] 4.3 Lexical ranker: `ts_rank`, live + active only, same filters as the vector path
- [ ] 4.4 RRF fusion, `K=60`, pool 20 per ranker *(Decision 4)*
- [ ] 4.5 Selection: all consensus facts + at most `VECTOR_ONLY_MAX`(4) vector-only, capped
      at `MEMORY_RECALL_K`(12); vector-only floor `0.52`
- [ ] 4.6 Settings for every constant above, so none is a magic number in the query
- [ ] 4.7 **Test the measured behaviour, not the mechanism:** `"write a python function to
      reverse a list"` recalls **0** facts; `"remind me about my exam"` puts all three exam
      facts in the top 3; `"where do I work"` puts `works at TCS` first
- [ ] 4.8 Test: recall stays best-effort — a failure in either ranker degrades to the other
      rather than failing the turn
- [ ] 4.9 Test: superseded, rejected and forgotten facts are excluded from **both** rankers.
      A new retrieval path is a new place to leak a deleted record
- [ ] 4.10 Keep the measurement script in the repo so the numbers can be re-derived rather
      than trusted

## 5. Tools become a package

- [ ] 5.1 `core/tools/` package: `tasks.py`, `journal.py`, `memory.py`, `__init__.py`
      assembling `TOOLS` + dispatch *(Decision 8)*
- [ ] 5.2 Each module exports its schemas **and** its handlers together
- [ ] 5.3 `core/tools.py` deleted; imports updated. No behaviour change — the tool list sent
      to the provider must be byte-identical for the existing seven
- [ ] 5.4 Test: every schema in `TOOLS` has a handler and every handler has a schema

## 6. Repair the invisible requirements

- [ ] 6.1 Fold leaked `## ADDED` / `## MODIFIED` sections into the single `## Requirements`
      section for `assistant-tools`, `documentation`, `journal`, `tasks`, `ui-standards`,
      `web-chat`. **No requirement text is edited** *(Decision 9)*
- [ ] 6.2 `openspec validate --specs` passes for all 13 capabilities
- [ ] 6.3 Record the before/after count (21 invisible → 0) so the repair is checkable

## 7. Documentation and diagrams

- [ ] 7.1 `ARCHITECTURE.md` — the memory flow diagram (§4c) currently shows
      `extract → dedup → skip|embed→store`. Redraw for the one-writer path, the
      store-don't-drop rule, and hybrid recall. Add the tools package to the directory guide
      and `possible_duplicate_of` to the erDiagram
- [ ] 7.2 `REQUEST-ANATOMY.md` — recall is a two-ranker step now; update the pipeline and
      record the measured before/after fact counts and the added latency from 0.6
- [ ] 7.3 `backend/README.md` — the memory tools, the tools package layout, migration 010
- [ ] 7.4 `AGENTS.md` Layout — `core/tools/` package, `services/memory.py` as the one writer
- [ ] 7.5 `ROADMAP.md` — move this work to Done; state plainly what it does **not** do (no
      sweep of conflicts already stored)
- [ ] 7.6 `docs/INSIGHTS.md` — untouched by this change; confirm it stays true
- [ ] 7.7 A short note on how memory decides what to keep — written for the person using the
      app, not the person maintaining it

## 8. Verification

- [ ] 8.1 From `backend/`: `uv run ruff format .` and `uv run ruff check .` clean
- [ ] 8.2 From `backend/`: `uv run pytest` — all green
- [ ] 8.3 Frontend: `npm run build` clean (**not** `tsc --noEmit` — `tsconfig.json` has
      `files: []`, so it checks zero files and passes a broken build)
- [ ] 8.4 Migration 010 applies to an empty database **and** to a copy holding real rows
- [ ] 8.5 **Live:** say "remember that I have the AI-901 certification" and confirm it
      appears on the Knowledge page — the failure that started this change
- [ ] 8.6 **Live:** ask "which certifications do I have" and confirm all four come back
- [ ] 8.7 **Live:** correct a fact by chat and confirm the assistant *announces* it and the
      old version is superseded rather than deleted
- [ ] 8.8 **Live:** send a pure coding question and confirm no facts are recalled
- [ ] 8.9 Re-run the recall measurement and confirm the numbers match the design's table
- [ ] 8.10 **Confirm `.env` is NOT staged** before any commit
