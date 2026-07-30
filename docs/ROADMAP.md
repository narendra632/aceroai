# ROADMAP.md — where aceroai is going

> Living document. The *why* behind the architecture is in
> [`ARCHITECTURE.md`](ARCHITECTURE.md); this file is the *sequence of work*.
> Ordering is intentional but not contractual — we build one OpenSpec change at a
> time, and Narendra approves each proposal before it's implemented.

## Done

- **Phase 0** — scaffold: schema, config, security, `/health`, CI, OpenSpec workflow.
- **Feature 1 — Web chat** — the "one brain" (`handle_message`), auth (JWT cookie),
  SSE streaming, multi-session history, polished responsive Claude-inspired UI.
- **Feature 2 — Telegram channel** — thin adapter reusing the one brain;
  `/start` trust-on-first-use linking; chat-id allowlist.

## Now

- **Cross-session memory + adaptive reasoning** *(current OpenSpec change)*
  - **Adaptive reasoning:** the model's "thinking" budget is chosen *per request*
    — chat is fast (low) by default; **explicit user control** ("think harder"
    toggle on web, `/think` on Telegram) and **task routing** (any caller can pass
    an effort; future jobs like reviews use `high`) dial it up. Fixes the 5–7s
    first-token latency. *(A fully-automatic router model that classifies each
    message is deferred until billing — it costs an extra call per message.)*
  - **Cross-session memory (with pgvector):** start using the `profile_facts`
    table — extract durable facts about Narendra from conversations, **embed them
    (pgvector + HNSW)**, and **semantically recall** the most relevant ones into
    every new session, so Acero remembers him across chats instead of starting
    blank. *(This is the first real "cognition" layer, and where pgvector starts
    doing real work; today the assistant only sees the current session's last 20
    messages.)*

## Next (planned, in order)

1. **Hosting + CI/CD** — deploy the backend (always-on VM; leaning Google Cloud
   always-free `e2-micro` running backend + Postgres/pgvector in Docker) and the
   frontend (Vercel), and wire continuous deploy. This is the phase where the
   scheduled/proactive features become possible (a job only fires if the server
   is running).

2. **UI feature set** — the app grows a real product surface. Motivation: the
   frontend will be wrapped as a **PWA / Capacitor app with push notifications**,
   which is intended to eventually **make the Telegram channel obsolete** (native
   notifications instead of a bot).
   - **Journal / Tasks page** — UI over the existing `journal_entries` and `tasks`
     tables (today they exist in the schema but have no interface).
   - **Investments page** — Narendra has **local Markdown research files** describing
     exactly how he wants this to work. **⚠ ASK HIM for those `.md` files when we
     reach this feature** — do not design it before reading them.
   - **Knowledge visualization page** — visualize the memory/`profile_facts` and
     their **pgvector embeddings** (stored from the memory feature onward) that
     Acero has learned about Narendra, using a visualization library, so he can
     *see his knowledge graph grow* over time.

3. **MCP-powered real-world capabilities** — expose the tools Narendra actually
   uses through MCP so Acero can act in the real world, not just chat.

4. **Beyond** — additional features as they come up; this list grows over time.

## Future considerations (not scheduled)

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
