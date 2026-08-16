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

## Now

- **Documentation truth-up + diagrams** *(current OpenSpec change)* — bring every
  `.md` in the repo back in line with the code as it actually is, then adopt
  **Mermaid** as the diagram format so architecture pictures live in git, diff
  reviewably, and are updated in the same change as the code that moved.
  Every future OpenSpec `tasks.md` carries a "diagrams match the code" checklist
  item, the same way tests do.

## Next (planned, in order)

1. **UI/UX polish pass** — bring the interface to product standard rather than
   functional standard. The gap is concrete: native `<select>` elements and a native
   `datetime-local` input (an OS-styled white popup inside a dark UI, with an icon
   that is invisible on dark), no session rename, and similar rough edges throughout.
   Radix is already a dependency, so proper custom controls cost no new packages.
   Principle: **no shortcuts on UI/UX** — the bar is ChatGPT / Claude, not "it works".

2. **Scheduled jobs** — `app/jobs/` exists but is empty; APScheduler is in the stack
   and unused. A day-end summary and proactive nudges (overdue tasks, journal
   prompts) would make Acero the first to speak instead of purely reactive.

3. **PWA + web push** — installable app, native notifications. This is the feature
   that lets the **Telegram channel be retired**; it has been deferred twice and
   should not slip again.

4. **Investments page** — Narendra has **local Markdown research files** describing
   exactly how he wants this to work. **⚠ ASK HIM for those `.md` files when we
   reach this feature** — do not design it before reading them.

5. **Knowledge visualization page** — visualize the memory/`profile_facts` and
   their **pgvector embeddings** that Acero has learned about Narendra, so he can
   *see his knowledge graph grow* over time.

6. **MCP-powered real-world capabilities** — expose the tools Narendra actually
   uses through MCP so Acero can act in the real world, not just chat.

7. **Beyond** — additional features as they come up; this list grows over time.

## Standing risk — not yet scheduled

- 🔴 **No database backup.** Everything Acero knows — memory/`profile_facts`,
  journal entries, tasks, chat history — lives on a single 10 GB disk on one
  `e2-micro`. There is no dump, no snapshot, no off-box copy. If that disk is lost
  or a migration goes wrong, it is all gone with no way back. Unlike every other
  item on this list, delay here has **permanent** cost rather than deferred value.
  Likely shape: a nightly `pg_dump` in the compose stack, retained N days, copied
  off the VM (Cloud Storage bucket or similar), plus a **rehearsed restore** —
  a backup nobody has restored from is a hope, not a backup.

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
