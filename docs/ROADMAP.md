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

- **What Acero said, what it runs on, and a strip of wasted space** — notifications and
  briefings became removable, the notification panel stopped claiming you had none while it
  was still loading, the daily push ceiling was removed, and the Insights page gained live
  server vital signs plus a `disk_watch` job.

  Three of the four things asked for turned out to be **defects rather than missing
  features**, two of them breaking `ui-standards` requirements that had been archived for
  releases. The notification bell was hand-written instead of going through
  `useOptimisticList`, and so re-implemented none of the invariants that hook enforces.

  Getting the existing suite green first surfaced three more, none of them planned:

  - **The job advisory lock had never worked.** `pg_try_advisory_lock` is scoped to a
    Postgres *connection*, and a SQLAlchemy `Session` is not pinned to one — `commit()`
    returns it to the pool. `run_job` commits several times, so the unlock ran on a
    different connection than the one holding the lock. The lock leaked onto pooled
    connections, and could both block work that should run and fail to block work that
    should not. `UNIQUE (job_name, occurrence_key)` had been carrying the guarantee alone.
  - **The test suite depended on the developer's `.env`** — eight tests asserted the
    unconfigured-push behaviour and passed only because CI has no VAPID keys.
  - **Six tests asserted on rows they did not create**, counting a real browser
    subscription registered during local testing.

  The connecting thread: a suite that is green in CI and red on one machine is not reporting
  a fault in the code, and would just as happily hide one.

- **Acero speaks first, and Telegram is retired** — the assistant had never once started a
  conversation. Everything it knew about your day sat in Postgres waiting for you to think to
  ask. `app/jobs/` had been an empty package since Phase 0 and `apscheduler` an unused
  dependency for just as long.

  Six jobs now run on a schedule: a **morning brief**, a **day-end summary**, an **overdue-task
  nudge** (coalesced, and silent when nothing has changed), a **spend warning** at 80% of the
  monthly limit, an optional **journal prompt**, and the **retention sweep** — which used to
  ride on the back of a delivered reply, so a quiet week pruned nothing at all.

  **The scheduler is only a ticker.** A `job_runs` table decides what has run, keyed on the
  job plus the exact scheduled instant, unique in the database. That is not bookkeeping for
  its own sake: an in-memory scheduler loses the 21:00 summary to a 20:58 deploy and reports
  *nothing*, because nothing failed. Here the run happens at 21:05 instead.

  **Two defects were found by measurement rather than by reasoning.** APScheduler counts
  weekdays from Monday while every crontab reference counts from Sunday, so `* * * * 0` — which
  reads unmistakably as Sunday — fires on **Monday**, silently, forever. And a daily job with a
  24-hour catch-up window can never be missed, because its occurrences are 24 hours apart; the
  window read like a staleness policy while actually meaning "deliver however late". Both are
  now startup failures rather than comments.

  **On the AI:** most jobs use no model at all — *"which tasks are overdue"* is a query. The
  two digests gather every fact in SQL and hand the model **only that**, with no tools and no
  database access, so it cannot report a task you did not finish. A job that could *act* on a
  timer was considered and rejected: unsupervised action is a different risk class from
  unsupervised writing.

  **Notifications are stored, then delivered.** The row is written before any push is
  attempted, so it survives a refused permission, a closed laptop, a dead subscription and a
  swipe on a lockscreen. A failed push is recorded against the *device* — a phone in a drawer
  must not make working software look broken. Everything lands in a bell in the header, and the
  longer briefings get their own tab in Journal beside your own entries.

  **Web push replaced Telegram**, which had been the weakest part of the system since it
  shipped: a long-poll loop that only ran while the backend was up, and a bot token that
  **leaked into production logs** before it was caught. Writing the test for that redaction
  found a second hole — the pattern's comment claimed to cover `?key=` while the regex required
  `api` before `key`, which is exactly the shape the Gemini Developer API uses.

  Telegram conversations are **preserved unchanged**: `chat_sessions.channel` still permits
  `'telegram'`, because rewriting those rows would make the record misstate where they happened.

  The app is also **installable** now — a manifest, a hand-written service worker, an offline
  shell, and its own icon. On iPhone that installation is the precondition for notifications at
  all; on Android it is optional.

  **What it does *not* do:** no offline message queue, no weekly review, no email fallback, and
  no job that can take an action. Each is named in the list below rather than implied.

## Now

*(Nothing in flight — the next change on the list below starts when Narendra says so.)*

## Next (planned, in order)

1. **Investments page** — Narendra has **local Markdown research files** describing
   exactly how he wants this to work. **⚠ ASK HIM for those `.md` files when we
   reach this feature** — do not design it before reading them.

2. **MCP-powered real-world capabilities** — expose the tools Narendra actually
   uses through MCP so Acero can act in the real world, not just chat. The tool
   registry (`core/tools/`) was shaped with this in mind.

3. **Beyond** — additional features as they come up; this list grows over time.

### Small things the jobs change made cheap

Each is roughly one file now that the registry exists — which was the point of building it
that way.

- **A weekly review.** `generated_reviews.kind='weekly'` already permits it.
- **Memory hygiene.** A weekly job surfacing flagged duplicates and conflicts — the delivery
  mechanism the "Review conflicts" item below has been missing.
- **Disk watch.** 10 GB, no backup. A push at 80% full is about twenty lines and is the
  cheapest insurance this project can buy.
- **A nightly `pg_dump`.** The deliberately-deferred backup finally has somewhere to live.
- **A stale in-progress nudge.** A task that has been `in_progress` for a fortnight.

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

- **⚠ A warning raised inside quiet hours can go a full day without ever buzzing.** Quiet
  hours suppress the *push* and keep the *record*, which is correct and deliberate. But a job
  that also suppresses repeats then never gets a second chance: `disk_watch` runs at 00:00,
  06:00, 12:00 and 18:00, and the first two fall inside the 22:00–07:00 window. A crossing
  detected at midnight is recorded and not delivered; at 06:00 and again at 12:00
  `already_said` finds it inside its 24-hour window and stays quiet. The row sits in the
  panel and the phone never rings.

  Found by walking the behaviour of `reliable-urgent-notifications` rather than its code, and
  deliberately left out of that change: the general fix is **"deliver what quiet hours held,
  once quiet hours end"** — a pending-delivery concept that belongs in its own change, not
  bolted onto a nudge rewrite. A narrower fix (pace repeats from the last *delivery*, as
  `task_nudge` now does) would work for a job that repeats, and `disk_watch` deliberately
  does not.

  **Trigger: production disk crossing 80%. It is at 77%.** This is the one item here whose
  trigger is already close, and the warning it would swallow is the one about the disk that
  stops Postgres accepting writes on a machine with no backup.

- **A forced job re-run spends money but leaves no record.** `run_job(..., force=True)`
  bypasses the already-ran check and executes — including the model call — but its
  `_record` then hits `UNIQUE (job_name, occurrence_key)`, and that `IntegrityError` is
  deliberately swallowed. So the run is invisible in `job_runs` while its cost is fully
  visible on Insights. Found by reconciling four `job` turns against three run rows.
  Harmless in normal operation, since nothing forces a run on its own. **Trigger: the next
  time a job is re-run by hand.** The fix is a distinct occurrence key for forced runs, so
  they record as themselves rather than colliding with the scheduled occurrence.

- **One unverified check on the interface: the keyboard pass.** The 375 px pass is
  **done** — the app was installed from Chrome on a Pixel on 2026-08-24 and used there, which
  exercised the Learn section, the notification bell and the Journal tabs at phone width.

  What has still never been exercised is **keyboard-only navigation**. Everything is built
  for it — every control is a real button, the tablists have roving `tabIndex` and arrow
  keys, the switches are Radix, and the notification row's dismiss button carries its own
  label — but built-for and verified are different things, and nobody has tabbed through
  any of it. **Trigger: the next keyboard pass over any screen.** A ten-minute check, listed
  only so it is not silently assumed done.

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
  user) will need rework: real signup, per-user isolation,
  onboarding. Keep this in mind so we don't over-couple to single-user assumptions
  where it's cheap to avoid.

## How we work (reminder)

Plan-then-act, OpenSpec-first for any multi-file change:
`/opsx:propose` → Narendra reviews → `/opsx:apply` → `/opsx:archive`.
After edits, from `backend/`: `uv run ruff format .` and `uv run pytest`.
Never touch `.env`.
