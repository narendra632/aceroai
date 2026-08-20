# Design

Every number in this document was measured against the live embedding model and the real
`profile_facts` table before the design was chosen. Where a measurement contradicted an
earlier proposal, the proposal was changed and the contradiction is recorded — that is the
point of writing them down.

---

## Decision 1 — One writer, two callers

`services/memory.remember()` becomes the only function that creates, supersedes or forgets
a fact. Both the chat model's tools and the background extractor call it.

This is the pattern the project already uses everywhere else: `services/` is the single
source of truth for the REST API *and* the assistant's tools, so a task created by tapping
**Add** and one created by the assistant are validated identically. Memory is the one
subsystem that never got a front door, which is precisely why it grew a write path with no
validation anyone could point at.

**Rejected — a separate write path for the tool.** Two implementations of "store a fact"
would drift, and the dedup rule would end up implemented twice with different thresholds.

---

## Decision 2 — The extractor keeps returning JSON; only the chat model gets tools

The obvious symmetry — "if writing memory is a tool, let the extractor use the tool too" —
is wrong, for three reasons:

| | Chat model | Extractor |
|---|---|---|
| decides | **whether** to act at all | **what** is in this exchange |
| runs | every turn, acts on ~1% | every turn, always |
| cost of tools | one round trip, rarely | one extra round trip, **always** |

A tool exists so a model can *choose to act*. The extractor has no such choice — it is
handed a turn and asked "anything durable here?", and returns a list that is often empty.
Tool-calling would buy it nothing and cost a second provider request on every single
message.

JSON is also checkable against a schema; a tool-call transcript has to be interpreted.

**Rejected — extractor emits tool calls.** Doubles background request count for no decision
it needs to make.

---

## Decision 3 — Novelty is a judgement, and discarding requires evidence

Today the extractor proposes facts blindly and a distance threshold decides novelty
afterwards. That is the machinery that ate AI-901 at d=0.098.

The new rule inverts the default:

```
extractor proposes a fact, tagged either `new` or `replaces: <id>`
        │
        ├─ replaces set ................ supersede that fact (history preserved)
        ├─ no hint, distance ≥ NEAR ..... store as new
        └─ no hint, distance < NEAR ..... STORE ANYWAY, flagged as a possible duplicate
```

**Today: close ⇒ assume duplicate ⇒ delete. Proposed: close ⇒ assume new, unless something
says otherwise.** Dropping is the destructive move, so it is the one that needs evidence.

This mirrors a rule the project already holds elsewhere — *a zero is a lie that silently
understates; a gap is visible and gets fixed*. A discarded fact is a lie of omission. A
stored near-duplicate is visible on the Knowledge page and can be merged in one click.

Note honestly: `replaces` **already exists and already fails**. It missed the Infosys→TCS
conflict entirely. It is treated here as a hint, never an authority — which is why the
no-hint branch stores rather than trusting silence.

**Rejected — exact text match as the dedup key.** Catches `AI-901` vs `AI-103` but misses
every genuine rewording, which is the case dedup exists for.

**Rejected — a second model call to judge each near-pair.** Correct but pays a provider
request per candidate on the background path. Revisit if flagged duplicates become common.

---

## Decision 4 — Hybrid retrieval, fused by rank rather than score

### Why a relevance floor alone cannot work

An earlier version of this plan proposed a distance floor on recall. The measurement killed
it:

| query | best match | facts surviving a 0.40 floor |
|---|---|---|
| `where do I work` | 0.406 | **0** — would lose `Narendra works at TCS` |
| `which certifications do I have` | 0.385 | 1 |
| `hello` | 0.419 | 0 |
| `good night` | 0.480 | 0 |
| `explain TCP handshakes` | 0.519 | 0 |

Every fact about one person occupies a narrow 0.30–0.58 band. `"hello"` at 0.419 scores
*closer* than genuine matches for other queries. There is no line that keeps
`works at TCS` and drops `has sisters`.

Distance answers *"is this about the same person"*. It does not answer *"does this answer
the question"*.

### What the second ranker adds

Postgres full-text, measured on the same facts:

```
lexical "certifications"  →  exactly the 2 certification facts, nothing else
lexical "gym"             →  exactly the gym fact
lexical "hello"           →  0 matches
lexical "TCP handshake"   →  0 matches
lexical "work office"     →  0 matches   ← lexical's own blind spot
```

Keyword matching is precise exactly where vectors are vague, and blind exactly where
vectors see (`where do I work` → `works at TCS` needs meaning, not words). They fail in
opposite directions, which is what makes fusing them worth more than either.

### It is not BM25, and the difference is measured

An earlier draft called this "BM25-style". That was loose, and checking it changed the
design. Postgres `ts_rank` is **not** BM25: it has no inverse-document-frequency term, no
term-frequency saturation, and no BM25 length normalisation.

What that means in practice, measured on the real facts:

```
query "certification"  -> 2 matches, 1 DISTINCT score   (both exactly 0.060793)
query "work"           -> 4 matches, 1 DISTINCT score   (all four exactly 0.060793)
query "exam certification voucher" -> 1 match, 0.268330
```

For a single-term query **every match scores identically**. `ts_rank` is behaving as a
*filter*, not a ranker — it only separates documents when they match a different number of
query terms.

This is fine, because the filter is where the value is. The lexical side answers "does this
fact contain what you asked about?", and RRF turns that binary answer into a rank position.
Real BM25 would rank *within* the matches, which matters at thousands of facts and is
nearly meaningless at twenty. Recorded so nobody later assumes a sophistication that is not
there.

**Rejected — a real BM25 extension (`pg_search` / ParadeDB).** A new dependency and a
different Postgres image, to improve ordering inside a set of two matches.

### Dropping terms that appear in almost every fact

Measured scaling, on synthetic memories with realistic vocabulary:

| facts | matches | lexical query | if the term is in EVERY fact |
|---|---|---|---|
| 500 | 48 | 2.3 ms | 9 ms |
| 5,000 | 426 | 8.0 ms | 65 ms |
| 20,000 | 1,670 | 16.4 ms | **219 ms** |

The realistic column is sub-linear — GIN does its job. The last column is the trap:
`ts_rank` must score **every** match before sorting, so a term present in all of them makes
cost linear in the size of memory.

And that case is not hypothetical. Every fact begins with `Narendra` or `The user` — by
design, since the extractor is instructed to phrase the subject consistently. A message
containing the user's own name would match the entire table.

Two mitigations, both cheap:

- **Drop terms with a document frequency above `LEXICAL_MAX_DF` (30%).** A word in most
  facts carries no information about which fact you want — this is the one thing IDF would
  have told us, applied by hand.
- **Cap the candidate set before ranking**, so ranking cost is bounded by a constant rather
  than by the size of memory.

A first measurement seeded every synthetic fact with the query term and produced 524 ms at
20k facts. That number described a corpus nobody has; it is recorded here because it was
nearly reported as a scaling problem.

### Reciprocal Rank Fusion, not a weighted score

```
score(fact) = Σ over rankers  1 / (K + rank_in_that_ranker)        K = 60
```

The two scores are **not on a comparable scale** — cosine distance runs 0.30–0.58, `ts_rank`
runs 0.00–0.10. Any weighted average silently lets one dominate and needs re-tuning every
time either distribution shifts. RRF discards magnitudes and fuses *positions*, so it needs
no normalisation and no per-corpus tuning. K=60 is the standard damping constant; it makes
the gap between rank 1 and rank 2 matter more than the gap between rank 11 and 12.

### The selection rule

The fused scores separate cleanly, because a fact found by **both** rankers scores roughly
double one found by a single ranker:

```
both rankers   ≈ 0.032
one ranker     ≈ 0.014 – 0.016
```

That cliff is the relevance signal that a raw distance could not provide. So:

> **Keep every fact both rankers found. Then top up with at most `VECTOR_ONLY_MAX` (4) of
> the best vector-only facts. Cap the total at `MEMORY_RECALL_K` (12).**

Agreement is the signal; the top-up stops a vague-but-personal question (`what should I do
today`) from recalling nothing. A vector-only floor of **0.52** removes queries that are not
about the user at all — the one place the data does separate cleanly.

Measured result, real memory:

| query | before | after | what moved |
|---|---|---|---|
| `remind me about my exam` | 12 | **7** | all three exam facts to ranks 1-2-3 |
| `which certifications do I have` | 12 | **6** | both certification facts to the top |
| `where do I work` | 12 | **8** | `works at TCS` to rank 1 |
| `when do I go to the gym` | 12 | **5** | gym fact to rank 1 |
| `what should I do today` | 12 | **4** | — |
| `hello` | 12 | **4** | — |
| `write a python function…` | 12 | **0** | nothing here is about the user |

`MEMORY_RECALL_K` stops being a quota and becomes a ceiling.

**Rejected — a cross-encoder / LLM re-ranker.** The most accurate option and the wrong
trade: a provider call on the critical path of every message, against a recall step already
budgeted at 4 seconds.

**Rejected — tuning the distance floor per query type.** Requires classifying the query,
which is the problem it was meant to avoid.

---

## Decision 5 — Lexical queries are OR, not AND

`plainto_tsquery('english', 'work office')` produces `work & offic` — every term must be
present — and matched **zero** facts while `Narendra works at TCS` sat right there.

The query is built as an OR of individually sanitised terms
(`plainto_tsquery(:w0) || plainto_tsquery(:w1) || …`), stop-words dropped, capped at 8
terms. Each term goes through `plainto_tsquery` so nothing user-typed is ever interpolated
into a tsquery — `to_tsquery` on raw input is a syntax-error and injection surface.

A GIN index on `to_tsvector('english', fact)` supports it. The expression is immutable
because the config is named explicitly, so an expression index is sufficient and no
generated column is needed.

---

## Decision 6 — Destructive memory actions are announced

Chosen by Narendra. When the assistant supersedes or forgets a fact mid-conversation, it
says so in the reply.

The argument is this bug: the assistant claimed a write it never made, and nothing
contradicted it for three exchanges. An announcement is a claim the user can check
immediately against the Knowledge page. Silence is what let a false success stand.

---

## Decision 7 — Delete is withheld from the background extractor

| | add | supersede | forget |
|---|---|---|---|
| chat model (user present, explicit instruction) | ✅ | ✅ | ✅ |
| background extractor (cheap model, nobody watching) | ✅ | ✅ | ❌ |

Superseding preserves history and is reversible by reading it; deletion in an unattended
loop is neither observed nor prompted. Forgetting stays soft (`deleted_at`, restorable), so
even the chat model's delete is recoverable — which is what makes granting it safe.

---

## Decision 8 — Tools become a package

```
core/tools/
  __init__.py    assembles TOOLS + the dispatch map — the only import the handler needs
  tasks.py       schemas and handlers, together
  journal.py
  memory.py
```

Two properties that matter as this grows past 10 tools: adding a domain is **adding one
file**, never editing a shared list; and a schema sits **beside its handler**, so one cannot
be added without the other. MCP later exposes the same registry rather than a second copy.

**Rejected — a decorator registry.** Neat, but import-order-sensitive and harder to read
than an explicit assembly in `__init__`.

---

## Decision 9 — The invisible requirements are repaired, not rewritten

21 of 49 requirements sit below leaked `## ADDED` / `## MODIFIED` headers in main specs and
are invisible to `validate`, `list` and `archive`. The repair is mechanical: fold the delta
sections into the single `## Requirements` section and delete the headers. **No requirement
text is edited** — this restores visibility, it does not restate intent.

`openspec validate --specs` passing for all 13 capabilities is the acceptance check.

---

## Decision 10 — Recall is shown to the user, not just used

**Narendra's request.** Every reply gets a third control beside copy and regenerate that
reveals the facts recall actually injected for that message.

The facts are already fetched and already sent to the model, so this costs nothing to
compute. What it buys is that memory stops being a black box: this whole change exists
because a fact was silently missing and there was no way to see it. With this, the AI-901
bug is visible in one glance — the fact simply is not in the list.

It is the same principle as Decision 6. An announcement you can check beats a claim you
cannot.

Shape:

- A new `recall` SSE event carries the facts used, emitted after the recall stage. The
  browser attaches them to that message.
- **Click, not hover.** Hover does not exist on a phone, and this must work at 375 px. The
  existing Popover primitive already handles focus and dismissal.
- The control is **absent, not empty**, when nothing was recalled — and after this change
  that is a real state (a coding question recalls nothing), so an always-present button
  showing "none" would be noise on exactly the turns that need no explanation.
- The **recalled fact ids are also written into the `memory_recall` span's `meta`**, which
  already records the count. Ids are identifiers, not content, so this stays inside the
  existing rule that traces record shape and never message text. It makes the same
  information available on the Insights waterfall for any past turn, not only for the
  session still open in the browser.

**Rejected — storing the recalled facts on the `messages` row.** Duplicates fact text into a
second table, where it would go stale as facts are edited or forgotten.

**Rejected — showing it only in Insights.** The moment the question "why did it say that?"
occurs is in the conversation, not on a dashboard visited weekly.
