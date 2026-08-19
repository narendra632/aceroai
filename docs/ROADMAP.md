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
  0.328 apart with drifting wording and **0.131** with consistent wording.

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
