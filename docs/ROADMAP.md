# ROADMAP.md — where aceroai is going

> Living document. The *why* behind the architecture is in
> [`ARCHITECTURE.md`](ARCHITECTURE.md); this file is the *sequence of work*.
> Ordering is intentional but not contractual — we build one OpenSpec change at a
> time, and Narendra approves each proposal before it's implemented.

## Done

- **Phase 0** — scaffold: schema, config, security, `/health`, CI, OpenSpec workflow.
- **Feature 1 — Web chat** — the "one brain" (`handle_message`), auth, SSE
  streaming, multi-session history, polished responsive Claude-inspired UI.
- **Feature 2 — Telegram channel** — thin adapter reusing the one brain;
  `/start` trust-on-first-use linking; chat-id allowlist.
- **Cross-session memory + adaptive reasoning** — per-request reasoning effort
  (fast by default; "think harder" toggle on web, `/think` on Telegram, task
  routing for jobs); durable facts extracted from chats, **embedded (pgvector +
  HNSW)**, and **semantically recalled** into every new session.
- **Hosting + CI/CD** — backend live on a Google Cloud always-free `e2-micro`
  (Docker: Caddy + api + Postgres/pgvector, auto-HTTPS via DuckDNS), frontend on
  Vercel. **Stage 2 CD:** a push to `main` that passes tests builds the image on
  GitHub → GHCR → SSH-deploys to the VM automatically. Auth is a Bearer token
  (localStorage) because the cross-site cookie was blocked by browser privacy
  protections — see [`ARCHITECTURE.md`](ARCHITECTURE.md) / the memory note.
- **Tasks & journal + assistant tool-use** — a shared `services/` layer backs both
  the REST API and the assistant's function-calling tools, so the same logic serves
  web, Telegram, and the model. Task-aware context (open tasks injected each turn).
- **Multi-provider LLM + Settings** — `core/providers/` behind one interface, each
  on its **native** SDK (google-genai on Agent Platform via ADC; the openai SDK).
  Per-user provider/model choice in a Settings view. Embeddings pinned separately.
  Per-turn telemetry (`aceroai.timing`) — which caught a 12 s embedding stall and
  took a turn from ~14 s to ~1.9 s in production.
- **Documentation truth-up + diagrams** — every `.md` brought back in line with the
  code, **Mermaid** adopted for architecture diagrams (in git, diff-reviewable), and
  a standing "docs and diagrams reflect what was built" item added to every future
  `tasks.md` so the drift cannot silently return.
- **UI/UX to product standard** — all 38 findings in [`UI-AUDIT.md`](UI-AUDIT.md)
  closed. Six shared primitives on Radix (no new dependencies); deleting is now
  **reversible** via an Undo toast backed by soft delete (migration 004), with the
  exclusion filter in `services/` so the assistant can never see a deleted record;
  `notes` and `snoozed_until` finally have a UI; conversations can be renamed and
  searched; every list has loading, empty and **error** states.
- **Knowledge visualization** — the memory has a page and an API of its own. Facts
  are drawn as a kNN force graph built from the *same* pgvector embeddings recall
  uses, so the picture cannot drift from what Acero actually knows; a list view is
  the default on narrow screens. Facts can be edited, confirmed, forgotten and
  restored, and editing supersedes rather than overwrites, so history survives.
- **Observability** — every provider call is now traced: cost, tokens, latency,
  and a per-stage waterfall. This closed three real accounting defects — a
  tool-using turn recorded only its **last** round; embeddings and fact extraction
  were **billed and never counted** (they are ~4 % of spend and a third of all
  calls); and thinking tokens were dropped on one provider while being billed at
  the output rate. Traces are pruned on a schedule with a permanent daily rollup
  behind them, so the tables cannot outgrow the 10 GB disk.

  A **monthly spend limit** closes the loop: observability could report cost but not
  stop it, so a runaway loop was visible afterwards rather than prevented. Set a
  ceiling in Settings and replies pause once the month's estimated spend passes it,
  with a warning at 80% and a one-click way to raise it. Off by default.

  **What observability does *not* do:** no alerting, no external exporter, no
  sampling. Cost is an **estimate** frozen at
  write time from a hand-maintained price list — both providers bill through
  accounts this app never sees, so it will not match an invoice to the cent.
  Latency percentiles and error kinds exist only within the trace-retention
  window; past it, spend and volume survive and speed does not.

- **Memory the assistant can write, and recall that actually discriminates** — Acero could
  read its memory but never deliberately write to it, so *"remember that I have the AI-901
  certification"* did nothing while the assistant said it had worked. Three tools
  (`remember_fact`, `correct_fact`, `forget_fact`) now go through **one writer** shared with
  the background extractor, so a fact you ask for and a fact learned in the background obey
  the same rules — and a failed write is reported as a failure instead of being narrated as
  a success.

  The same bug had a second cause: the extractor **deleted** any proposed fact sitting
  within 0.12 of an existing one. Measured, `AI-901` and `AI-103` are **0.098** apart while
  two phrasings of the same family fact are **0.216** apart — the threshold is wrong in both
  directions at once. Near-duplicates are now stored and flagged on the Knowledge page as a
  question, never resolved by deletion.

  **Recall became two searches instead of one.** Distance alone could not work: every fact
  about one person sits in a 0.30-0.58 band, so `hello` scored closer than genuine matches
  for other queries, and recall returned a fixed 12 facts on every message including
  *"write a python function to reverse a list"*. A keyword search now runs alongside the
  vector search and their **positions** are fused, with agreement as the signal. Measured on
  the real memory: 12 → 7 for the exam question, 12 → 8 for *"where do I work"* (with the
  job first), 12 → **0** for the coding question. Added cost is ~4 ms at 1,000 facts against
  a 300-500 ms embedding call.

  Every reply now carries a third control showing **exactly which facts were used**, and the
  same list appears on the Insights waterfall for any past turn — because this whole change
  exists as a result of a fact being silently absent with no way to notice.

  **What it does *not* do:** it does not sweep conflicts or duplicates already stored. The
  new rules apply from here forward; the backlog is the "Review conflicts" item below. It
  also does not re-rank *within* keyword matches — `ts_rank` is not BM25 and has no IDF,
  which is worth revisiting in the thousands of facts, not now.

- **A Learn section, and diagrams that cannot quietly rot** — everything learned building
  this lived in `docs/`, written for whoever maintains the code and unreachable from the
  product. The app now explains itself: two diagrams you click into (how a message is
  answered; what it costs and how we know) and concept cards for the ideas underneath —
  embeddings, rank fusion, streaming, soft delete, one brain.

  It is built to stay accurate rather than to be accurate once. **Every number is fetched**
  from a read-only endpoint that reads the live configuration, so a tuned setting changes
  the lesson instead of making it wrong. **Every reference is checked** — a panel pointing
  at a file that no longer exists fails the build. That mechanism earned itself
  immediately: the endpoint revealed that the running app was recalling **12** facts, not
  the 16 the code defaults to, because `.env.example` still pinned the old value and every
  copied `.env` inherited it silently.

  Two other things fell out of it. An audit of all eleven Mermaid diagrams found **four
  defects**, the worst being a node id declared twice — Mermaid keeps one label and drops
  the other, so the diagram rendered *wrong* rather than failing. All eleven are now checked
  structurally on every CI run. And the **frontend had no CI job at all**, which meant
  `npm run build` — the only thing that typechecks this project — had never run outside a
  laptop. It does now.

  **What it does *not* do:** it does not generate itself from the code. The prose is written
  by hand and must be maintained by hand; the tests catch broken references, not missing
  ones. A change to the system updates the Learn content in the same commit, or not at all.

## Now

*(Nothing in flight — the next change on the list below starts when Narendra says so.)*

## Next (planned, in order)

1. **Scheduled jobs** — `app/jobs/` exists but is empty; APScheduler is in the stack
   and unused. A day-end summary and proactive nudges (overdue tasks, journal
   prompts) would make Acero the first to speak instead of purely reactive.

2. **PWA + web push** — installable app, native notifications. This is the feature
   that lets the **Telegram channel be retired**; it has been deferred twice and
   should not slip again.

3. **Investments page** — Narendra has **local Markdown research files** describing
   exactly how he wants this to work. **⚠ ASK HIM for those `.md` files when we
   reach this feature** — do not design it before reading them.

4. **MCP-powered real-world capabilities** — expose the tools Narendra actually
   uses through MCP so Acero can act in the real world, not just chat.

5. **Beyond** — additional features as they come up; this list grows over time.

## Deliberately deferred

- **Database backup.** Everything Acero knows lives on a single 10 GB disk with no
  off-box copy. This is a **priced, deliberate choice** rather than an oversight:
  the data is currently recoverable by re-stating it, and the cost of losing it is
  accepted until the Investments page ships, at which point the calculus changes.
  Likely shape when it is scheduled: a nightly `pg_dump` in the compose stack,
  copied off the VM, plus a **rehearsed restore** — a backup nobody has restored
  from is a hope, not a backup.

## Triggered work — scheduled by a measurement, not a date

These are not "someday" items. Each has a **numeric trigger**, and the knowledge graph
tells you in the interface when one fires.

- **Real BM25 for the keyword ranker.** Postgres `ts_rank` has no inverse document
  frequency, so within a set of matches it does not discriminate at all — measured, every
  match of a single-term query scores an identical `0.060793`. That is fine at tens of
  facts, where the filter is the whole value, and stops being fine when a common word
  matches a hundred of them. **Trigger: ~1,000 stored facts**, where IDF becomes real
  signal rather than noise. The option is `pg_search`/ParadeDB, which costs a new
  dependency and a different Postgres image — priced deliberately, not deferred vaguely.

- **Barnes-Hut quadtree for the graph layout.** The force simulation compares every fact
  with every other one — O(n²). Measured per frame (desktop, physics only, drawing not
  included): 0.22 ms @200 · 1.0 ms @400 · 3.5 ms @800 · 9.4 ms @1500, against a 16.7 ms
  frame budget. A quadtree treats a distant cluster as one blob and turns this into
  roughly n·log n. **Trigger: the Knowledge page says so** — it warns at 80% of the 800
  ceiling, before anything is hidden. Scope is one function; the rest of the page is
  untouched.

- **Conflict review for the memory.** Acero can hold two contradicting beliefs at once and
  use either. Found live: *"Narendra works at TCS"* (stated) and *"The user works at
  Infosys"* (inferred), both active. The contradiction handling built into extraction only
  fires when the model volunteers a `replaces` hint at the moment a fact is written — it
  does nothing about conflicts already stored, or ones created by confirming/editing in the
  interface.

  **Partly mitigated already:** the extractor is now required to phrase every fact with the
  same subject, because that alone was hiding the conflict — the identical claim measured
  0.328 apart with drifting wording and **0.131** with consistent wording. Since the memory
  change above, near-duplicates are also *flagged* rather than deleted, so new conflicts
  arrive visible instead of arriving as a silent gap. Neither touches the pairs already
  sitting in the table, which is what this item is for.

  The remaining piece is a **"Review conflicts" action** on the Knowledge page, shaped as:
  distance narrows the candidates (each fact's single nearest neighbour, in a band close
  enough to be about the same thing but too far to be a repeat) → **one batched model call**
  judges which candidates genuinely conflict, because distance provably cannot (*"has
  sisters"* and *"celebrates Rakshabandhan"* sit at 0.189 and are complementary, not
  contradictory) → **the user picks which is true**, and the loser is superseded, never
  deleted. **Trigger: seeing a wrong belief in conversation, or two rival facts in the
  graph.** Cheap filter, sparing use of the expensive judge, human as the authority.

- **Precompute graph edges on write.** The edge query asks each fact for its nearest
  neighbours, so it is N×N in Postgres. Migration 006's partial HNSW index made that
  survivable (5619 ms → 170 ms at 800 facts), but there is a **planner-crossover hump**
  between roughly 300 and 700 facts where Postgres still prefers a sequential scan:
  measured 277 ms @200 → **1111 ms @400** → 243 ms @800. It self-corrects, so this is not
  urgent. The durable fix is computing a fact's neighbours once when it is stored and
  keeping them in an `fact_edges` table, making reads a plain select.
  **Trigger: the Knowledge page taking more than ~2 s to load.**

## Future considerations (not scheduled)

- **Further latency work on memory recall.** After moving embeddings off the `global`
  endpoint a turn is ~2.9 s, of which the embedding is still the largest single piece
  (~1.8 s from Oregon, ~0.5 s from Mumbai). Ideas, roughly in order of value-for-effort
  (see [`REQUEST-ANATOMY.md`](REQUEST-ANATOMY.md) for the measurements):
  1. **Skip recall for trivial messages** ("ok", "thanks", one-word replies) — saves the
     whole embedding on those turns for no loss of usefulness.
  2. **Cache embeddings** of repeated/near-identical queries.
  3. **Benchmark smaller/faster embedding models** against the current one for both
     latency *and* recall quality — ⚠ changing the model invalidates every stored
     vector, so it requires a deliberate re-embed migration of `profile_facts`.
  4. **Trim the fixed token floor** (persona + tool schemas are re-sent every turn).

- **Semantic journal search.** Search is currently `ILIKE`, a plain substring match —
  cheap and honest, but it finds "errands" when you search "ran", and misses "I ran 5k"
  when you search "running". Postgres full-text (`tsvector`) would fix both, but the
  better end-state is **semantic search over the embeddings this app already produces**,
  which would find "times I felt burnt out" in an entry that never uses those words.
  Spending a migration on `tsvector` first would be paying for a stepping stone we
  intend to step over.

- **Public / multi-user app** — Narendra may later open this up to other users.
  If so, the auth and user model (currently deliberately single-user: one seeded
  user, one Telegram allowlist) will need rework: real signup, per-user isolation,
  onboarding. Keep this in mind so we don't over-couple to single-user assumptions
  where it's cheap to avoid.

## How we work (reminder)

Plan-then-act, OpenSpec-first for any multi-file change:
`/opsx:propose` → Narendra reviews → `/opsx:apply` → `/opsx:archive`.
After edits, from `backend/`: `uv run ruff format .` and `uv run pytest`.
Never touch `.env`.
