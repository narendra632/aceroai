# Memory that can be written on purpose, and recall that is actually relevant

## Why

Narendra told the assistant, twice and explicitly, that he had completed the AI-901
certification. He asked it to store the fact. It replied *"Recorded that you completed the
AI-901 certification."* **Nothing was stored.** Asked later, it listed three
certifications and omitted the fourth.

Three separate defects produced that, and each is worth fixing on its own.

### A. The fact was thrown away by the duplicate check

Measured against the live embedding model:

| pair | cosine distance | outcome |
|---|---|---|
| `AI-901 certification` vs `AI-103 certification` | **0.098** | under the 0.12 threshold → **discarded** |
| `AI-901 certification` vs `AI-103 exam and received the certification` | **0.115** | under the threshold → **discarded** |
| `AI-901 certification` vs `GH-300 certification` | 0.208 | stored |

The embedding cannot distinguish `AI-901` from `AI-103`: four characters inside an
otherwise identical sentence is, semantically, the same sentence. GH-300 and GH-600
survived only because "GH" is far enough from "AI" — luck, not design.

The same single threshold fails in the opposite direction at the same time. Both of these
are stored right now as separate active facts:

```
"The user has sisters."
"Narendra has sisters."
```

So one number is simultaneously too strict for certifications and too loose for sisters.
**Cosine distance measures topic, not identity.** No single threshold can separate "same
fact, reworded" from "different fact, similar wording", and the current design treats
*discard* as the default outcome of that impossible judgement.

### B. There is no way to write a fact on purpose

The assistant has seven tools — create/list/update/complete/delete task, add/list journal.
**None writes memory.** Memory is extraction-only, in the background, after the turn.

So "store that fact about me" had no mechanism behind it, and the assistant said it had
done it anyway. That is worse than the missing fact: a memory that silently drops things is
a bug, but an assistant that reports success on a write it never performed teaches the user
to trust it exactly when they should not.

### C. Recall returns twelve facts whether or not any are relevant

`ORDER BY distance LIMIT 12` with no floor. Measured on the real memory:

- `"hello"` injects twelve facts including his sisters, his gym and his friend Supreeth
- `"which certifications do I have"` injects twelve, of which **eight are irrelevant** —
  and ranks *"The user has sisters"* above *"Narendra is preparing for the AI-103 exam"*
- `"write a python function to reverse a list"` injects twelve facts about Narendra

That is roughly 300 tokens of noise on every message, and it dilutes the facts that matter.

**A relevance floor alone cannot fix it**, which the measurement showed and this proposal
does not paper over: every fact about one person sits in a narrow 0.30–0.58 band. A 0.40
floor would make *"where do I work"* recall **nothing at all** — `Narendra works at TCS`
sits at 0.406, while `"hello"` scores 0.419 and would survive. There is no line to draw.

### D. The specs no longer describe what is built

21 of 49 requirements in `openspec/specs/` are **invisible to the tooling**: earlier
archives left `## ADDED` / `## MODIFIED` delta headers inside main specs, which truncate the
parsed `## Requirements` section. `ui-standards` and `documentation` are 100% invisible.
This does not affect the running app, but the next change that touches those capabilities
cannot see what it is modifying.

## What Changes

**One door for every memory write.** A single `services/memory.remember()` becomes the only
function that creates, supersedes or forgets a fact. The chat model reaches it through new
tools; the background extractor reaches it by returning JSON exactly as it does today. Same
validation, same rules, one implementation — the pattern `services/` already follows for
tasks and journal.

**Deliberate writes.** `remember_fact`, `correct_fact` and `forget_fact` join the tool set.
The chat model gets all three. The background extractor gets add and supersede but **never
delete** — superseding preserves history and there is no human watching that loop.

**Announced, not silent.** When the assistant corrects or forgets a fact mid-conversation it
says so. Had that existed, this bug would have surfaced the moment it happened.

**No more silent discards.** A near-duplicate is superseded (history kept) or stored and
flagged. Never dropped without a trace.

**Hybrid recall.** Postgres full-text rank fused with vector distance by Reciprocal Rank
Fusion. Facts both rankers agree on rank first; a small vector-only allowance keeps vague
questions from recalling nothing. Measured effect on the real memory:

| query | facts injected, before → after |
|---|---|
| `remind me about my exam` | 12 → **7**, all three exam facts ranked 1-2-3 |
| `which certifications do I have` | 12 → **6**, both certification facts at the top |
| `where do I work` | 12 → **8**, `works at TCS` promoted to first |
| `when do I go to the gym` | 12 → **5** |
| `hello` | 12 → **4** |
| `write a python function to reverse a list` | 12 → **0** |

**Tools become a package.** `core/tools.py` → `core/tools/`, one module per domain with each
schema beside its handler, so adding a domain is adding a file rather than editing a shared
list.

**Specs and docs brought back in line**, including the 21 invisible requirements and every
diagram that describes the memory pipeline.

## Non-goals

- **No re-embedding of stored facts.** The embedding model stays pinned.
- **No second model call per turn for relevance.** Hybrid retrieval is pure Postgres; a
  re-ranking model would add latency and cost to every message.
- **No automatic conflict sweep** over facts already stored. The Infosys/TCS class of
  problem stays on the roadmap as its own change; this one stops *new* conflicts being
  created silently.
- **No change to the embedding provider, dimensions, or the recall time budget.**

## Dependencies

None new. Postgres full-text search is built in, and the tool-calling machinery already
exists.

## Risks

- **A tool the model can call to delete memory.** Mitigated by soft delete (already built,
  restorable from the Knowledge page), by withholding delete from the background extractor,
  and by announcing every destructive action in the reply.
- **Hybrid recall could regress a query type not in the sample.** Mitigated by keeping the
  measurement script and asserting the measured behaviour in tests, so a regression is a
  failing test rather than a feeling.
- **Storing instead of discarding grows memory faster.** Accepted deliberately: a visible
  near-duplicate can be merged, a discarded fact cannot be recovered. The graph already
  warns before its node ceiling.
