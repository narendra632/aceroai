# Tasks

Findings get recorded inline as work proceeds, with ⚠ wherever a premise turns out to be
wrong. A task that cannot be done as written is annotated, never quietly ticked.

## 0. Verify the assumptions before any production code

The riskiest premises in the design, checked first.

- [x] 0.1 ⚠ **`openspec/config.yaml` does not parse.** Found while creating this change:
      `Implicit keys need to be on a single line at line 26` — a plain YAML scalar containing
      `": "`. OpenSpec has been silently ignoring the project context **and every rule** in
      that file, for every change since the rules were added.
      → Fixed by making it a `>-` folded block. `openspec list` is now warning-free and
      `openspec instructions` shows the project context and both rule sets. The rule
      "State new dependencies explicitly and flag that Narendra must approve them" had never
      once been applied
- [x] 0.2 ⚠ **`CronTrigger.from_crontab` does NOT use crontab's day-of-week numbering.**
      All six schedules parse correctly in `Asia/Kolkata` — but measured, `0 18 * * 0` fires
      on **Monday**, not Sunday. APScheduler numbers days 0=Monday; standard crontab uses
      0=Sunday. A "Sunday weekly review" written the obvious way would silently run a day
      early, and nothing would report an error.
      → Guarded: the registry **rejects a numeric day-of-week field at import**, requiring
      `sun`/`mon`/… instead. Verified: `0 18 * * sun` → Sunday, `0 18 * * 6` → Sunday,
      `0 18 * * sat` → Saturday. A silent off-by-one is now a startup failure
- [x] 0.3 Forward-stepping `most_recent_occurrence` verified against 8 cases: daily,
      hourly-with-range, weekly-by-name, exact-boundary (`now == fire time`, which
      `get_next_fire_time` treats as **inclusive**), across local midnight, and outside the
      window returning `None`. All correct.
      → Cost measured: **3.3 ms** for the worst realistic case (7-day window on an hourly
      job, 91 iterations). Daily jobs are far cheaper. Not worth optimising
- [x] 0.4 `pg_try_advisory_lock` verified on the dev database across two connections:
      first acquires, second is refused while held, second acquires after release
- [x] 0.5 `uv add pywebpush` → resolves, `cryptography` unchanged.
      ⚠ It pulled **11 packages including `aiohttp`** — heavier than expected on a 1 GB VM.
      → Avoided: `WebPusher.encode()` produces the encrypted body **without sending**, and
      `py_vapid` signs the headers, so the actual HTTP request goes through **`httpx`**,
      which the app already uses and which is async-native. `aiohttp` is never imported at
      runtime. One HTTP client in the app, not two
- [x] 0.6 Full offline proof: a synthetic Chrome subscription, aes128gcm encryption
      (**191 bytes** for a realistic payload, against the 4096 limit) and a VAPID
      `Authorization` header — all with **no network**.
      → The push sender is therefore genuinely testable in CI, which was the open risk
- [x] 0.7 `turns.kind='job'` accepted by the migration-007 CHECK constraint (flush, then
      rollback — nothing written)
- [x] 0.8 `generated_reviews` accepts `morning`/`daily`/`weekly` with an empty `delivered_to`.
      Confirmed the table holds **0 rows** today: built in migration 001, never used since
- [x] 0.9 **Premises that were wrong: two.** The OpenSpec config had been silently dead
      (0.1), and the cron day-of-week numbering is not what any crontab reference says
      (0.2). Both are now guarded rather than noted. Everything else held

## 1. Schema — migration 011

- [x] 1.1 `job_runs` with `UNIQUE (job_name, occurrence_key)` and a six-value status CHECK
- [x] 1.2 `notifications` + a recency index and a **partial** index on unread (read on every
      page load; the unread set is the small tail of a table that only grows)
- [x] 1.3 `push_subscriptions`, `endpoint` UNIQUE so re-subscribing updates rather than
      accumulating a row that can never be delivered to
- [x] 1.4 `user_job_prefs`, sparse — verified: adding a job needs no migration and no backfill
- [x] 1.5 `users` +`quiet_hours_start`/`quiet_hours_end`/`daily_push_cap`, −`telegram_chat_id`
- [x] 1.6 `chat_sessions.channel` CHECK left **unchanged**, with the reason in `models.py` so a
      later reader does not "tidy" it away
- [x] 1.7 Models written with docstrings in the established style
- [x] 1.8 Verified **up → down → up** against the real database. `telegram_chat_id` is restored
      nullable + unique by the downgrade, exactly as migration 001 created it

## 2. The job registry and runner

- [x] 2.1 `registry.py` — `Job`, and the `@job(...)` decorator
- [x] 2.2 `JobResult` with `notify` / `review` / `detail` / `silent`
- [x] 2.3 Import-time validation, **raising** not asserting
- [x] 2.3a ⚠ **A second validation was needed and was not in the plan.** `catch_up` must be
      shorter than the gap between occurrences or it can never expire — see 2.4a. The registry
      now computes the real gap (`Job.min_period`, sampled from the trigger) and refuses a
      window that cannot bite
- [x] 2.4 `most_recent_occurrence(job, now, lookback)` — forward walk, measured 3.3 ms worst case
- [x] 2.4a ⚠ **Design defect, found by a failing test I had written to pass.** A daily job with
      the planned 24-hour default can **never** be recorded missed — its occurrences are 24
      hours apart, so one is always inside the window. The window read like a staleness policy
      while meaning "deliver however late": a 07:30 brief would still go out at 07:29 the next
      morning, which is precisely what the design said it must not do.
      → Default lowered to 4 h, every shipped job given an explicit considered value, and
      "however late" now has to be spelled `catch_up=None` (used by `retention_sweep` alone).
      Enforced at import, and asserted for the real registry by a test
- [x] 2.5 `run_job` — advisory lock, budget check, timeouts, recording, everything caught
- [x] 2.6 `tick(db, user, now)` — a pure function of `now` and the database
- [x] 2.6a ⚠ **A first-ever evaluation must not be recorded as `missed`.** Found on the first
      live tick: deploying the feature at 01:52 wrote six `missed` rows, because every job's
      last scheduled moment was behind us. Nothing was missed — the jobs did not exist yet, and
      six failures on a healthy first boot is a bad first impression and worse evidence.
      → `has_ever_run` gates it. "Missed" now means "it used to happen and this time it did not"
- [x] 2.7 `scheduler.py` — APScheduler holds **exactly one** job, and the lifespan starts/stops
      it. Verified through a `TestClient` round-trip: starts, ticks, shuts down clean
- [x] 2.8 Timeouts moved out of `services/retention.py` and into the runner
- [x] 2.9 `python -m app.jobs.run` — `--list`, a bare tick, one job, `--force`
- [x] 2.10 `services/job_prefs.py` — sparse resolution, plus `human_schedule` so the phrasing
      has one implementation rather than a second one in TypeScript

## 3. First job: retention, moved off the reply path

- [x] 3.1 `retention_sweep` at 03:15, `catch_up=None`
- [x] 3.2 `prune_notifications` added — the third unbounded table, bounded in the same change
      that introduces it
- [x] 3.2a ⚠ **`rowcount` can be −1**, and `or 0` does not catch it because −1 is truthy. The
      rollup's `INSERT..SELECT..ON CONFLICT` returns exactly that: the first live sweep recorded
      `{'rolled_up': -1}` and counted it as having done something, so a sweep with nothing to do
      reported `ok` instead of `silent`. Pre-existing since the observability change; invisible
      until these counts started being recorded. Fixed with a `_rows()` helper
- [x] 3.3 `maybe_sweep`, `_lock`, `_last_run` and the `TODO(scheduled-jobs)` paragraph deleted.
      `sweep`/`rollup`/`prune_*` untouched — only the trigger was ever wrong
- [x] 3.4 `telemetry._housekeeping` and its call deleted; the `record` docstring now explains
      where retention went and why
- [x] 3.5 The three `maybe_sweep` tests replaced with job-level equivalents, including one that
      asserts the old functions are **gone** rather than merely unused

## 4. Notifications: the store, then the channel

- [x] 4.1 `services/notifications.py` — the row is written first, unconditionally
- [x] 4.2 Policy central: per-job enablement, quiet hours, daily cap
- [x] 4.2a ⚠ **Quiet hours could not be turned off.** NULL already means "use the server
      default", so there was no way to express "never quiet" — and the test suite was therefore
      **time-dependent**: every push test passed by day and failed at night. Found at 01:52,
      failing. → Equal start and end means no window; a test documents it, and the push tests
      set it explicitly so the suite no longer depends on the wall clock
- [x] 4.3 `core/push.py` — lazy, and importable with no keys. Verified: CI has none
- [x] 4.4 404/410 deletes the subscription; anything else records `last_error_at` and keeps it
- [x] 4.5 TTL per kind — 24 h digests, 4 h nudges, asserted
- [x] 4.6 Payload is `{title, body, url, tag}`, bounded and asserted. Measured: 191 bytes
- [x] 4.7 A failed push leaves the job `ok`, asserted
- [x] 4.8 `api/notifications.py` — list, unread, mark read, mark all, subscribe, unsubscribe, test
- [x] 4.9 `api/jobs.py` — list and toggle. **No trigger route**, asserted by a test
- [x] 4.10 `generate_vapid.py` — prints, writes nothing, and says the rotation warning out loud
- [x] 4.10a ⚠ **The generated key could not be loaded back.** §0.6 verified signing but never
      round-tripped the key: the script emitted DER/PKCS8 while `Vapid01.from_raw` wants the raw
      32-byte scalar, so every real send would have died with `ValueError: Invalid EC key`.
      Caught by the first push test. → The script emits the raw scalar (what every other VAPID
      tool produces), and `push.py` loads with `from_string`, which accepts either — because a
      key pasted from a different tool is likely to be the other form
- [x] 4.11 Config added, all of it numeric or a key
- [x] 4.11a ⚠ **The docs told him to set an env var nothing reads.** Five places said to put
      `VITE_VAPID_PUBLIC_KEY` in `frontend/.env` — a leftover from the plan. The frontend
      actually fetches the public key from `GET /api/notifications/push`, which is the better
      design (one source of truth, and rotating the pair needs no frontend rebuild). All five
      corrected; nothing references it now
- [x] 4.11b ⚠ **`generate_vapid` crashed on Windows.** Found by running it: the `⚠` character
      cannot be encoded by a cp1252 console, so it died with `UnicodeEncodeError` **after**
      printing the keys. This is the first command in the setup instructions, on the platform
      this project is developed on. Output is now ASCII-only

## 5. The user-facing jobs

- [x] 5.1 `_gather` — the brief, built entirely in SQL
- [x] 5.2 `_compose` — one non-streaming call, traced `turns.kind="job"`. **First thing ever to
      write that enum value**, permitted since migration 007
- [x] 5.2a ⚠ **The persona was missing, and the first live brief proved it.** The design said
      "SOUL.md + the brief"; I shipped the brief alone with an instruction saying "in your own
      voice", which is meaningless without the file that defines the voice. The 07:30 brief
      came back as: *"Today is August 24, 2026, and you have zero tasks due today and zero
      overdue tasks. You still have one open task in total."* — accurate, and a recitation of
      the fact list.
      → `composer._read_persona()` reused (not a second SOUL.md loader, so a job and a chat
      reply speak as the same assistant and the prod `SOUL_PATH` override keeps working), the
      date dropped from the facts because the model kept parroting it, and the instruction now
      forbids mechanical restatement. Re-run live, same data:
      *"You have no tasks due or overdue today, with just one open item remaining on your
      list. You also haven't logged a journal entry yet. Take a moment to capture your
      thoughts whenever you're ready, or let me know how you'd like to handle that open
      task."* A test now asserts the persona is present rather than the wording
- [x] 5.3 `morning_brief` 07:30, `kind='morning'`
- [x] 5.4 `day_end_summary` 21:00, `kind='daily'` — `generated_reviews` finally holds rows,
      having been empty since migration 001
- [x] 5.5 Asserted: a generated review never reaches the memory extractor
- [x] 5.6 `task_nudge` — coalesced; the tag is a hash of *which* tasks, so an unchanged set is
      silent and completing one makes the next nudge genuinely new
- [x] 5.7 `budget_watch` — once at 80%, once at 100%, scoped per month
- [x] 5.8 `journal_nudge` — **off by default**, with the reasoning in its own docstring
- [x] 5.9 Every job returns `silent` rather than padding. An empty day does not even cost a
      model call

## 6. Frontend — service worker, PWA, and the surfaces

- [x] 6.1 `public/sw.js` hand-written — network-first navigation, cache-first hashed assets,
      API never touched, versioned cache
- [x] 6.2 `push` and `notificationclick`; an open window is focused rather than duplicated
- [x] 6.3 `pushsubscriptionchange` re-subscribes and re-posts
- [x] 6.4 `manifest.webmanifest` with real theme tokens and three shortcuts
- [x] 6.5 `vercel.json` created — the repo had none. `sw.js` and the manifest are `no-cache`,
      without which a new deploy could never replace the worker
- [x] 6.6 `lib/push.ts` — permission states, subscribe/unsubscribe, and `pushBlockedReason`
- [x] 6.7 `useInstallPrompt` — Chrome's event, or the iOS steps Safari never offers
- [x] 6.8 `useOnlineStatus`
- [x] 6.9 Notification bell — Popover when wide, Sheet when narrow, chosen by **measured width**
      via `useMediaQuery`. A CSS class would not have worked: Radix portals to `document.body`,
      which is the double-panel bug this project shipped once already
- [x] 6.10 Journal gains two tabs, with the same ARIA tablist treatment as `LearnView`
- [x] 6.11 Settings → Notifications: honest permission states, per-job toggles, quiet hours,
      and **Send a test**
- [x] 6.12 Settings → Install, or the iOS instructions
- [x] 6.13 `lib/api.ts` extended

## 7. Retire Telegram

- [x] 7.1 `app/channels/` and `tests/test_telegram.py` deleted
- [x] 7.2 The poller is gone from the lifespan; the scheduler holds that slot
- [x] 7.3 The bot-token regex dropped; the generic pattern, the formatter and `httpx → WARNING`
      kept, with the comments rewritten to the reason that still applies
- [x] 7.3a ⚠ **A real hole in the redaction, found by writing the test.** The pattern read
      `(?:api[_-]?key|token|access_token)=` while its comment claimed to cover `?key=` — which
      it did **not**, because `api` was required. `?key=<SECRET>` is exactly the form the Gemini
      Developer API uses, so the provider URL most likely to carry a raw key in a log was the
      one shape never being redacted. → `key` added as its own alternative; the lookbehind still
      protects `cache_key=` and `first_token=2584ms`. A test now asserts each spelling
      individually, and a second asserts real telemetry survives redaction
- [x] 7.4 `telegram_bot_token` removed from `config.py` and `.env.example`
- [x] 7.5 Comments in `services/journal.py` and `core/handler.py` corrected
- [x] 7.6 `test_prod_config.py` — Telegram assertions replaced; a new test asserts
      `app.channels` no longer imports and the lifespan starts no poller
- [x] 7.7 Existing `channel='telegram'` sessions still load — the CHECK still permits the value

## 8. Logo and icons

- [x] 8.1 ⚠ Deleted `public/favicon.svg` (still the **purple Vite/Vercel template mark**) and
      `public/icons.svg` (a template sprite containing a **Bluesky** icon). Neither was
      referenced anywhere. The app had no logo of its own at all
- [x] 8.2 `icon-192`, `icon-512`, `icon-512-maskable`, `apple-touch-icon`, `favicon` wired into
      the manifest and `index.html`
- [x] 8.3 `badge-mono.png` — a flat white silhouette on transparent, because Android renders a
      colour badge as a grey blob
- [x] 8.4 ⚠ **Not done: the wordmark is not in `LoginScreen` or the sidebar.** The generated
      wordmark does not exist yet, and putting a placeholder lockup on the login screen would
      look worse than the current type. Carried to the handover note — it is a five-minute
      change once Narendra supplies `wordmark.png`
- [x] 8.5 Placeholders written by a small rasteriser (pure stdlib, no image dependency) using
      the real palette, at the **final filenames**, so dropping generated artwork in needs no
      code change

## 9. Learn section

- [x] 9.1 `PROACTIVE_FLOW` — "How Acero speaks first", ten steps from the ticker to the bell
- [x] 9.2 Every node has a panel (the checker fails the build otherwise)
- [x] 9.3 Seven concept cards: idempotence, cron (and its weekday trap), job-owns-facts,
      store-then-deliver, web push, service workers, installing a website
- [x] 9.4 Ten new constants, **all numeric**. No cron strings — the int/float invariant is a
      security boundary, so schedules come from `/api/jobs` instead
- [x] 9.5 Telegram references updated; the concept card replaced by push
- [x] 9.6 `PLANNED` updated — jobs and push are no longer "not built yet"; a weekly review and
      "jobs that can act" take their place, the latter as a deliberate refusal
- [x] 9.7 A fifth tab in `LearnView`
- [x] 9.8 ⚠ Not done. `openspec/specs/learnings/spec.md` still says `Purpose: TBD - created by
      archiving...`, and so do several other archived capabilities — the Purpose written in a
      delta does not survive `openspec archive`. That is a **tooling** behaviour, not a content
      mistake, and fixing one file by hand would hide it. Carried to `ROADMAP.md`
- [x] 9.9 Content checker: **67 explanations, 34 live constants**. It earned itself again —
      it caught `docs/JOBS.md` and `docs/NOTIFICATIONS.md` being referenced before they existed

## 10. Tests

- [x] 10.1 Registry invariants — duplicate name, bad cron, no description, numeric weekday
- [x] 10.2 `most_recent_occurrence` across 7 cases, with the lookback passed **explicitly** so
      the algorithm is tested independently of the policy that normally supplies it
- [x] 10.3 Idempotence — same occurrence twice → one run, one notification
- [x] 10.4 Catch-up inside the window runs; outside it records `missed`
- [x] 10.5 A long outage produces **one** run, never a backlog
- [x] 10.6 Failure isolation — recorded, later jobs still run, `tick` does not raise
- [x] 10.7 Budget — AI job `skipped_budget`, non-AI unaffected
- [x] 10.8 Disabled → `skipped_disabled`, no row, no push
- [x] 10.9 Quiet hours and the daily cap — written, not pushed
- [x] 10.10 Push against a fake **transport**: real encryption, real VAPID signing, only the
      POST replaced. Payload shape, size bound, TTL, 410 deletes, 500 keeps
- [x] 10.11 A failed push leaves the job `ok`
- [x] 10.12 Notification API — list, unread, mark read, ownership on every route
- [x] 10.13 Both digests against a fake model; asserts the prompt contains **only** the brief
      and that no tools are passed
- [x] 10.14 A generated review never reaches the extractor
- [x] 10.15 `task_nudge` — coalescing, no repeat, snoozed/completed/dropped/deleted excluded
- [x] 10.16 `app.channels` is gone and no poller starts
- [x] 10.17 `/api/learn/constants` still int/float only, with the ten new keys
- [x] 10.18 `test_docs_diagrams.py` — **57 checks** (was 49) across the new and redrawn diagrams
- [x] 10.19 **Testing the tests.** Four defects in this change were found by a test failing
      that I expected to pass — 2.4a, 2.6a, 4.2a and 4.10a — and one (7.3a) by writing an
      assertion per spelling rather than one representative case. Recorded here because that is
      the evidence the guards are real, not a claim that they are

## 11. Docs and diagrams

- [x] 11.1 `docs/JOBS.md` — new, plain-language, including the weekday trap and the window rule
- [x] 11.2 `docs/NOTIFICATIONS.md` — new, with a **"when nothing arrives"** table
- [x] 11.3 `ARCHITECTURE.md` — §2 redrawn (Telegram out; scheduler, worker and push service in),
      new §(h) *A scheduled job* and §(i) *A notification's journey*, ER +4 tables and the
      `users` columns, directory guide +`app/jobs/`
- [x] 11.4 `REQUEST-ANATOMY.md` §5c — the anatomy of a job beside a request, with measurements
- [x] 11.5 `DEPLOY.md` and `DEPLOYMENT-EXPLAINED.md` — VAPID vars, the scheduler in the api
      container, Telegram gone
- [x] 11.6 `ROADMAP.md` — both items moved to Done; "small things this made cheap" added
- [x] 11.7 `AGENTS.md` — two new golden rules (11 and 12); an existing numbering collision fixed
- [x] 11.8 `README.md`, `backend/README.md`, `frontend/README.md`
- [x] 11.9 `.env.example` — VAPID block with the rotation warning; Telegram removed
- [x] 11.10 **docs and diagrams reflect what was built** — 57 structural checks pass, and the
      content checker verifies every path, placeholder and concept the Learn section names

## 12. Verification

- [x] 12.1 `uv run ruff format .` and `uv run ruff check .` — clean
- [x] 12.2 `uv run pytest` — **501 passed** (370 before this change), one run
- [x] 12.3 `npm run lint` and `npm run build` — clean; 67 explanations, 34 constants
- [x] 12.4 Migration verified up → down → up against the real database
- [x] 12.5 Live, twice. The first tick at 01:52 produced findings 2.6a and 3.2a. After both
      fixes, a tick at 09:59 gave: `morning_brief` **ok**, `retention_sweep` **silent**,
      `budget_watch` **silent**, and the other three correctly absent — no spurious `missed`
      rows, and `silent` where the pre-fix run had wrongly said `ok` with `rolled_up: -1`
- [x] 12.5a Live, end to end: the morning brief gathered real data, called Gemini, wrote a
      `generated_reviews` row, raised a notification pointing at `/#journal/briefings`, and
      recorded a `turns` row with `kind='job'` — **$0.001442**, 114 in / 43 out, 9.2 s.
      `generated_reviews` had been empty since migration 001 and `turns.kind='job'` unwritten
      since 007. Produced finding 5.2a
- [x] 12.6 Idempotence covered by test rather than by a second live run
- [x] 12.6a ⚠ **The 2.6a fix broke two of my own earlier tests, correctly.** They asserted a
      `missed` row for a job with no history — which is now skipped. Both were given history
      first, and a new pair of tests pins BOTH halves of the rule: a first evaluation is never
      a miss, and once a job has run, a gap **is** recorded. The suite caught this, not I
- [x] 12.7 **Live push on the Pixel — VERIFIED in production, 2026-08-24.** Narendra
      generated VAPID keys, deployed, installed the PWA from Chrome, permitted notifications
      and received them — including with the app closed, which is the only test that proves
      the service worker is running independently of any page. Icons, wordmark and the
      Settings panel confirmed on the device
- [x] 12.8 **Live briefing verified** in Journal → Acero's briefings, in production
- [x] 12.12 ⚠ **Two deployment defects, both found only by deploying.** Neither could have
      been caught locally, and that is the lesson rather than an excuse:
      **(a) `vercel.json` used `"//"` as a comment key.** JSON has no comments; the key is a
      convention some tools tolerate and Vercel's schema rejects outright
      (`should NOT have additional property '//'`). It is valid JSON, so parsing it locally
      proved nothing — only the deploy target's schema knew. The reasoning now lives in
      `frontend/README.md`, together with a note saying why it cannot live in the file.
      **(b) The API sat in Docker's `Created` state**, never started, with empty logs. The
      `docker compose up` was interrupted while waiting on `migrate` (which succeeded,
      exit 0), and with nothing left supervising, `api` was never started. Presented as a
      **CORS error in the browser** — Caddy answered 502, a 502 carries no
      `Access-Control-Allow-Origin`, and the browser reported the symptom it could see.
      `curl -i https://.../health` separated the two in one step. Re-running
      `docker compose up -d` fixed it. Nothing was wrong with the code, the schema or `.env`
- [x] 12.13 Verified from outside the network after the fix: `/health` 200, and the CORS
      preflight from `https://aceroai.vercel.app` returns the correct
      `access-control-allow-origin`
- [x] 12.9 Insights will show a `job` slice: `turns.kind="job"` is asserted by a test to be
      written by a digest
- [x] 12.10 `.env` confirmed not staged before committing
- [x] 12.11 ⚠ Docker Desktop stopped mid-session and recreated the `db` container. Data
      verified intact afterwards (1 user, 23 sessions, 150 messages, 44 facts, 166 turns) —
      the named volume held, as designed. Noted because it is the failure mode the
      deliberately-deferred backup decision is priced against
