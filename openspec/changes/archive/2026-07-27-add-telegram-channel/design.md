## Context

Feature 1 established `handle_message(db, user, text, channel, session_id)` as the
single entry point for all chat, yielding `(event, data)` pairs. The `users`
table already has a nullable, unique `telegram_chat_id`. `settings.telegram_bot_token`
already exists. The app lifespan in `main.py` has a reserved spot for the poller.
This is a backend-only, additive feature.

## Goals / Non-Goals

**Goals:**
- Chat with Acero from Telegram, routed through the unchanged one-brain handler.
- Secure to a single linked chat; safe to run with or without a token.
- No new dependency; no schema change; works locally (no hosting) for testing.

**Non-Goals:**
- Token-by-token live editing of Telegram replies (send one complete message).
- Group chats, inline mode, media, commands beyond `/start`.
- Multi-user (still single-user).

## Decisions

**1. Raw Bot API over `httpx`, not python-telegram-bot.**
`getUpdates` (long-poll) and `sendMessage` are two simple HTTP calls; `httpx` is
already installed. Avoids a heavy new dependency and keeps the channel thin
(golden rule 1). *Alternative rejected:* python-telegram-bot — more capable but a
large dependency and its own event loop/abstractions we don't need.

**2. Consume the handler's stream, send one message.**
Telegram rate-limits message edits, so live token streaming is a poor fit for a
first version. The channel iterates `handle_message`, accumulates `delta` events
into the full reply, and sends it once with `sendMessage`. Still the same brain —
the channel just consumes the generator fully instead of forwarding deltas.

**3. Long-poll loop as a lifespan background task.**
On startup (only if `telegram_bot_token` is set), spawn an `asyncio` task that
loops: `getUpdates(offset, timeout=25)` → handle each update → advance offset. On
shutdown, cancel the task. Errors are caught and retried with a short backoff so
one bad update never kills the loop. Absent token → task never starts (keeps CI
and unconfigured local runs working — and, like the LLM client, nothing that
needs the token is touched at import).

**4. Allowlist via the user's `telegram_chat_id`, linked by `/start`.**
The bot serves exactly one chat. Linking is trust-on-first-use: the first
`/start` while `telegram_chat_id is NULL` binds that sender to the user and
confirms; afterward only that chat id is served and others get a short "not
authorized" reply. The bot token is itself a secret, so the exposure window is
tiny. *Alternative considered:* an explicit chat id in `.env` — more setup
friction (you must discover your numeric id first); `/start` linking is friendlier
and re-settable. Open to your preference (see Open Questions).

**5. Session continuity.**
Before calling the handler, look up the user's most-recent `chat_sessions` row
with channel `telegram`; pass its id (or `None` to let the handler create the
first). One ongoing Telegram thread keeps context, matching how a messaging app
feels.

## Risks / Trade-offs

- **Long-poll loop crashing** → wrap each iteration in try/except with backoff;
  log and continue. The loop is resilient to transient network/API errors.
- **Duplicate/replayed updates** → always advance `offset` past processed
  updates so each is handled once.
- **TOFU linking edge case** (a stranger `/start`s before you) → mitigated by the
  secret token and obscurity; re-link is a one-liner if needed. Switchable to an
  explicit-id allowlist if you prefer.
- **Blocking DB in an async loop** → reuse the handler's existing
  `run_in_threadpool` pattern for any direct DB lookups in the channel.

## Migration Plan

Additive: new file + lifespan wiring. No DB migration. Rollback = revert the
change and leave `TELEGRAM_BOT_TOKEN` unset. To use it: put the token in `.env`,
restart the backend, send `/start` from Telegram.

## Open Questions

- **Linking method**: `/start` trust-on-first-use (recommended) vs an explicit
  numeric chat id in `.env`. Defaulting to `/start` unless you prefer explicit.
