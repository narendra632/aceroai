# Tasks

Findings get recorded inline as work proceeds, with ⚠ wherever a premise turns out to be
wrong. A task that cannot be done as written is annotated, never quietly ticked.

## 0. Confirm the premises before building on them

- [x] 0.1 Re-run the dedup measurement and confirm `AI-901` vs `AI-103` is still **0.098**
      and `AI-901` vs `AI-103 exam and received…` still **0.115** — both under the 0.12
      threshold. If the numbers moved, the whole of Decision 3 needs re-arguing
      → **0.098 confirmed exactly.** ⚠ The second pair measured **0.129**, not 0.115 — now
      *above* the threshold. Decision 3 stands and is better supported: the primary pair is
      still inside the threshold and still deleted today, and a pair moving from 0.115 to
      0.129 on a re-measurement is itself evidence that a hardcoded cut-off through the
      middle of the distribution is fragile. Recorded rather than smoothed over
- [x] 0.2 Confirm both `"The user has sisters."` and `"Narendra has sisters."` are still
      active — the same threshold failing in the opposite direction
      → both active; the two phrasings measure **0.216**, comfortably outside the 0.12
      threshold that swallowed two *different* certifications at 0.098. Wrong in both
      directions at once, so it cannot be repaired by moving it
- [x] 0.3 Confirm no tool writes memory today (7 tools, none touching `profile_facts`)
      → confirmed: 7 tools, zero memory writers
- [x] 0.4 Re-measure the recall band and confirm a 0.40 floor would still return **zero**
      facts for `"where do I work"`. This is the number that killed the floor-only design
      → `where do I work` best match **0.406** (`Narendra works at TCS`), 0 survivors at
      0.40. `hello` 0.419, `TCP handshakes` 0.518, `python function` 0.553. The floor-only
      design is still dead
- [x] 0.5 Check whether `to_tsvector('english', fact)` is accepted as an immutable
      expression index on this Postgres build; if not, a generated column is needed and
      Decision 5 changes
      → accepted on PostgreSQL 17.10. No generated column needed; Decision 5 unchanged
- [x] 0.6 Measure the added latency of the lexical query against the recall time budget
      (`memory_recall_timeout_s`, 4 s) — record the number, do not assume it is free
      → **5.9 ms** of a 4,000 ms budget (0.15%) at 21 facts. Full scaling in 4.11

## 1. One writer

- [x] 1.1 `services/memory.remember(db, user, fact, category, *, source, source_ref,
      replaces, confidence)` — validate, embed, dedup-judge, store or supersede. Returns
      what it did (`stored` / `superseded` / `flagged`), never a bare bool
      → returns `WriteResult(action, fact, related)`; `related` carries the superseded or
      resembled row so the caller can name it
- [x] 1.2 `services/memory.correct(db, user, fact_id, new_text, ...)` — supersede, re-embed,
      record as `stated`
- [x] 1.3 `services/memory.forget(db, user, fact_id)` — soft delete, reusing the existing
      `deleted_at` path so Restore keeps working
      → the existing `forget_fact` already was exactly this; reused rather than duplicated
- [x] 1.4 Move the dedup judgement out of `core/memory._store` into the service so there is
      exactly one implementation *(Decision 1)*
- [x] 1.5 `core/memory.extract_and_store` calls `services.memory.remember` instead of
      writing directly. Behaviour on the background path must be unchanged except that a
      near-duplicate is now stored-and-flagged rather than dropped
      → `_store` now only resolves the model's `replaces` text to an id; every decision
      lives in the service
- [x] 1.6 Test: the extractor and the tool produce an identical row for identical input —
      the guarantee that there is one writer

## 2. Stop the silent discard

- [x] 2.1 Add `possible_duplicate_of` (nullable FK) to `profile_facts` — migration 010
- [x] 2.2 No-hint + distance under `NEAR` → store, flagged. **Never drop** *(Decision 3)*
- [x] 2.3 `replaces` hint → supersede, history preserved
- [x] 2.4 **Regression test, named for the bug:** two certifications differing only in their
      code (`AI-901` / `AI-103`) both end up stored and active. This test is the reason the
      change exists
      → `test_two_certifications_differing_only_by_code_both_survive`
- [x] 2.5 Test: a genuine reword ("I work at TCS" after "Narendra works at TCS") still
      supersedes rather than duplicating
- [x] 2.6 Surface the flag on the Knowledge page — a fact suspected of duplicating another
      is visible and mergeable, not silently identical
      → "may repeat another" chip in the list; the detail panel shows both facts with
      **Not a duplicate** / **Forget this one**. A warning with no way to answer it becomes
      permanent furniture, so `POST /api/memory/facts/{id}/not-duplicate` exists

## 3. Deliberate writes

- [x] 3.1 `remember_fact` tool — schema + handler calling `services.memory.remember`
- [x] 3.2 `correct_fact` tool
- [x] 3.3 `forget_fact` tool
- [x] 3.4 Tool results are structured and honest: `{"ok": true, "action": "stored", "id":…}`
      or an explicit failure. **The model must never be able to report a write that did not
      happen** — that is defect B
      → shape is `{"ok": true, "result": {"action": …, "id": …}}`: the `ok`/`result`
      envelope is the existing convention for all ten tools, and breaking it for three of
      them would be worse than the nesting. Content is exactly as specified
- [x] 3.5 `SOUL.md`: when the user asks to remember/correct/forget something, use the tool;
      do not claim to have stored anything otherwise
- [x] 3.6 **Announce destructive actions** in the reply *(Decision 6, Narendra's choice)*
- [x] 3.7 Test: "remember that I have the AI-901 certification" results in a stored,
      recallable fact — the exact exchange that failed
- [x] 3.8 Test: a tool failure surfaces as a failure to the model, not as silence

⚠ **Recorded limitation.** `correct_fact` and `forget_fact` take an id, and ids reach the
model only through the recalled-facts block — the same way task ids already do. So a fact
recall did not surface cannot be corrected by id in that turn. No lookup tool was added:
hybrid recall makes the realistic case ("forget that I like tea") reliable, because the
message now matches the fact by word as well as by meaning. Worth revisiting if it bites.

## 4. Hybrid recall

- [x] 4.1 Migration 010 (same migration as 2.1): GIN index on `to_tsvector('english', fact)`
      → partial, on the same `deleted_at IS NULL AND status='active'` predicate as the HNSW
      index, or the planner cannot use it for the queries the app actually runs
- [x] 4.2 `_tsquery()` — OR of individually sanitised terms, stop-words dropped, capped at 8.
      **Never interpolate user text into a tsquery** *(Decision 5)*
- [x] 4.2a Choose those 8 terms **rarest-first by document frequency**, not first-8-in-order.
      A three-paragraph message has fifty content words and the opening ones are rarely the
      informative ones; the rarest term is the one that identifies a fact. Falls out of the
      DF lookup 4.10 already needs, so it costs nothing extra
      → measured on a 5,000-fact corpus, a 60-word message kept
      `dental · cycling · pottery · goa · helios · week · terraform · evenings` — the
      identifying words, none of the filler
- [x] 4.3 Lexical ranker: `ts_rank`, live + active only, same filters as the vector path
- [x] 4.4 RRF fusion, `K=60`, pool 20 per ranker *(Decision 4)*
- [x] 4.5 Selection: all consensus facts + at most `VECTOR_ONLY_MAX`(4) vector-only + at
      most `LEXICAL_ONLY_MAX`(3) lexical-only, capped at `MEMORY_RECALL_K`(**16**, raised
      from 12); vector-only floor `0.52`
- [x] 4.5a A lexical-only fact is admitted **only if it matched a term with document
      frequency ≤ `LEXICAL_RARE_DF`(10%)** — the lexical equivalent of the vector-only
      floor. Computed as a boolean in the same query as the rank, over the already-capped
      candidate set, so it is not a second round trip
- [x] 4.5b Test the case that motivated it: a multi-topic message whose rare term
      (`dentist`) sits outside the vector pool still recalls that fact — and a message
      whose only lexical hits are on common words recalls **none** of them
- [x] 4.5c ⚠ **Defect found by 4.5b, not by reasoning: consensus needed a distance bound.**
      The vector ranker does not *find* facts, it *ranks* them — `ORDER BY distance
      LIMIT 20` returns twenty rows whether or not any relate to the message. On a 25-fact
      memory that pool is 80% of everything, so a single keyword hit put a fact at distance
      **1.0** into the "both rankers agreed" lane, and the recall popover would have told
      the user exactly that. Added `CONSENSUS_MAX_DISTANCE`(0.60): past it a fact is
      *demoted* to the lexical lane and must clear its gate, rather than being waved
      through as agreement that never happened
- [x] 4.6 Settings for every constant above, so none is a magic number in the query
- [x] 4.7 **Test the measured behaviour, not the mechanism:** `"write a python function to
      reverse a list"` recalls **0** facts; `"remind me about my exam"` puts all three exam
      facts in the top 3; `"where do I work"` puts `works at TCS` first
      → all three hold against the real memory. ⚠ The python case needed an honest
      correction in the *unit* test: English stemming maps `write` onto "Narendra **writes**
      his own summaries", so a stray keyword can still land one fact. The test now asserts
      what is actually true — the *meaning* ranker contributes nothing, and any keyword
      residue is bounded by `LEXICAL_ONLY_MAX` and never labelled agreement
- [x] 4.8 Test: recall stays best-effort — a failure in either ranker degrades to the other
      rather than failing the turn
      → and a ranker that *raised* is distinguished from one that *found nothing*: finding
      nothing is a real answer the selection rule depends on
- [x] 4.9 Test: superseded, rejected and forgotten facts are excluded from **both** rankers.
      A new retrieval path is a new place to leak a deleted record
- [x] 4.10 Drop query terms whose document frequency exceeds `LEXICAL_MAX_DF` (30%) and cap
      the candidate set before ranking. **Measured:** a term present in every fact costs
      219 ms at 20k facts because `ts_rank` scores every match before sorting — and every
      fact starts with the user's name, so this is a real query, not a hypothetical
      → verified: `"what do you know about Narendra"` drops `narendra` entirely
- [x] 4.11 Keep the measurement scripts in the repo so the numbers can be re-derived rather
      than trusted
      → `app/scripts/measure_recall.py` and `app/scripts/measure_recall_scale.py`, listed
      in `backend/README.md`. Scaling result: **~3-5 ms added** for a short message at 200 /
      1,000 / 5,000 facts, **~33-50 ms** for a three-paragraph message. Against a 300-500 ms
      embedding call inside a 4,000 ms budget

## 4b. Show what was recalled *(Decision 10)*

- [x] 4b.1 New `recall` SSE event carrying the facts used for this turn
- [x] 4b.2 Third control beside copy and regenerate, opening a Popover with the list.
      **Click, not hover** — hover does not exist on a phone
      → new `components/ui/popover.tsx` on the `radix-ui` package already in the stack; no
      new dependency
- [x] 4b.3 The control is **absent** when nothing was recalled, not present-and-empty
- [x] 4b.4 Write the recalled fact ids into the `memory_recall` span's `meta` alongside the
      count it already stores. Ids are identifiers, not content, so this stays inside the
      rule that traces never hold message text
- [x] 4b.5 Surface the same list on the Insights waterfall, so any past turn can be
      explained and not just the session still open
      → resolved live from the ids, so a corrected fact shows its current text and a
      forgotten one drops out — a forgotten fact must be unreachable from every path
- [x] 4b.6 375 px pass on the popover
      → `w-[min(22rem,calc(100vw-1.5rem))]` plus `collisionPadding`, so the panel can never
      push the page sideways
- [x] 4b.7 Test: the facts shown are exactly the facts sent to the model — a display that
      can drift from what was used is worse than no display
      → the test captures the real prompt and asserts every fact **and its id** appear in it

## 5. Tools become a package

- [x] 5.1 `core/tools/` package: `tasks.py`, `journal.py`, `memory.py`, `__init__.py`
      assembling `TOOLS` + dispatch *(Decision 8)*
      → plus `common.py` for the shared argument parsers. Putting them in `__init__` would
      have made every domain module import its own package
- [x] 5.2 Each module exports its schemas **and** its handlers together
- [x] 5.3 `core/tools.py` deleted; imports updated. No behaviour change — the tool list sent
      to the provider must be byte-identical for the existing seven
      → ⚠ one deliberate signature change: `execute` is now **async**. `remember_fact` must
      embed before storing, and a fact stored without a vector is invisible to recall. Sync
      handlers still run in a threadpool, inside `execute`, so no handler knows which it is
- [x] 5.4 Test: every schema in `TOOLS` has a handler and every handler has a schema
      → also enforced at import: the package raises on a mismatch rather than waiting for
      the model to call a tool that does not exist

## 6. Repair the invisible requirements

- [x] 6.1 Fold leaked `## ADDED` / `## MODIFIED` sections into the single `## Requirements`
      section for `assistant-tools`, `documentation`, `journal`, `tasks`, `ui-standards`,
      `web-chat`. **No requirement text is edited** *(Decision 9)*
      → diff is 13 insertions / 16 deletions across six files, all headers
- [x] 6.2 `openspec validate --specs` passes for all 13 capabilities
      → was 7 passed / 6 failed; now **13 passed / 0 failed**
- [x] 6.3 Record the before/after count (21 invisible → 0) so the repair is checkable
      → visible requirements **70 → 91**, against 91 on disk. Exactly the 21 claimed

## 7. Documentation and diagrams

- [x] 7.1 `ARCHITECTURE.md` — the memory flow diagram (§4c) currently shows
      `extract → dedup → skip|embed→store`. Redraw for the one-writer path, the
      store-don't-drop rule, and hybrid recall. Add the tools package to the directory guide
      and `possible_duplicate_of` to the erDiagram
      → §(c) redrawn as one writer with two callers; new §(e) for the two rankers with its
      own diagram, the measured tables, and the three honest limits
- [x] 7.2 `REQUEST-ANATOMY.md` — recall is a two-ranker step now; update the pipeline and
      record the measured before/after fact counts and the added latency from 0.6
      → new §5b. Prompt size went **down**: ~100-200 tokens saved on a typical turn, which
      more than pays for the ~12 tokens per fact now spent carrying its id
- [x] 7.3 `backend/README.md` — the memory tools, the tools package layout, migration 010
      → plus a "Re-deriving the numbers" section pointing at the two measurement scripts
- [x] 7.4 `AGENTS.md` Layout — `core/tools/` package, `services/memory.py` as the one writer
- [x] 7.5 `ROADMAP.md` — move this work to Done; state plainly what it does **not** do (no
      sweep of conflicts already stored)
      → and a new triggered item: real BM25 at ~1,000 facts, where IDF becomes signal
- [x] 7.6 `docs/INSIGHTS.md` — untouched by this change; confirm it stays true
      → ⚠ it was no longer complete: the waterfall now also shows which facts a turn used.
      Added, with the note that "no facts" is an answer rather than a gap
- [x] 7.7 A short note on how memory decides what to keep — written for the person using the
      app, not the person maintaining it
      → `docs/MEMORY.md`, linked from `README.md` and `AGENTS.md`

## 8. Verification

- [x] 8.1 From `backend/`: `uv run ruff format .` and `uv run ruff check .` clean
- [x] 8.2 From `backend/`: `uv run pytest` — all green → **288 passed** (was 262)
- [x] 8.3 Frontend: `npm run build` clean (**not** `tsc --noEmit` — `tsconfig.json` has
      `files: []`, so it checks zero files and passes a broken build)
- [x] 8.4 Migration 010 applies to an empty database **and** to a copy holding real rows
      → empty: created a throwaway database, `upgrade head` → `downgrade -1` →
      `upgrade head`, all clean, column and index present. Real rows: applied to the dev
      database, which holds 21 live facts
- [x] 8.5 **Live:** say "remember that I have the AI-901 certification" and confirm it
      appears on the Knowledge page — the failure that started this change
      → `remember_fact` fired, reply was "Stored.", row present with `source=stated` and an
      embedding. The exchange that produced a false success now produces a real write
- [x] 8.6 **Live:** ask "which certifications do I have" and confirm all four come back
      → AI-901 recalled at rank 1 (found by **both** rankers), alongside the Claude
      certifications and the AI-103 voucher. The reply listed them without inventing any
- [x] 8.7 **Live:** correct a fact by chat and confirm the assistant *announces* it and the
      old version is superseded rather than deleted
      → reply: *"Updated — I had you at AI-901, now AI-902."* Old rows `status=superseded`
      with `superseded_by` set; nothing deleted. (The invented AI-902 was removed and the
      real AI-901 fact restored afterwards — the test must not leave a false fact behind)
- [x] 8.8 **Live:** send a pure coding question and confirm no facts are recalled
      → "write a python function that reverses a list": **no `recall` frame at all**, so no
      third control appears on that reply. This is the 12-facts-every-message bug, gone

- [x] 8.11 ⚠ **Defect found by the live run, not by the tests: every explicit "remember X"
      wrote the fact twice.** The tool stored it, then the background extractor read the
      same turn, proposed the same sentence, and stored it again — and recall returned both
      copies. The store-don't-drop rule was working exactly as designed; the design had not
      accounted for two writers seeing one turn.

      Fixed with the one principled exception to that rule: **identical text is a provable
      repeat, not a judgement call.** The argument for keeping near-duplicates is that
      distance cannot separate a restatement from a change (AI-901 vs AI-103 at 0.098);
      byte-identical text carries no such ambiguity, and nothing is lost by not writing it.
      `remember` now returns `UNCHANGED` and writes nothing. Belt and braces, facts a tool
      just wrote are also handed to the extractor as already known.

      Re-verified live: the same instruction a second time produced one row, not two.
      (In that re-run the model declined to call the tool at all, having seen the fact in
      its recalled context — also correct, and the reason the guard itself is covered by
      `test_the_exact_same_sentence_is_not_stored_twice` rather than by the live run.)
- [x] 8.9 Re-run the recall measurement and confirm the numbers match the design's table
      → exact match after the 4.5c fix: 7 / 6 / 8 / 5 / 4 / 4 / **0**
- [x] 8.10 **Confirm `.env` is NOT staged** before any commit
      → checked before the commit and re-checked after: `.env` is gitignored, absent from
      commit `378479f`, and not tracked anywhere in the repository
