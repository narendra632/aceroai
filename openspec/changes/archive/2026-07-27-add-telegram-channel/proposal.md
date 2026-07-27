## Why

Feature 1 proved the "one brain": all chat flows through
`core/handler.handle_message`. Feature 2 adds Telegram as a second channel so
Narendra can talk to Acero from his phone — and it's the payoff of that design:
the Telegram side is a thin adapter that calls the *same* `handle_message`, with
zero conversational logic of its own. It also means the assistant is reachable
without hosting anything (long-polling makes outbound calls to Telegram).

## What Changes

- New `channels/telegram.py`: a long-poller that calls the Telegram Bot API
  `getUpdates` in a loop and, for each authorized message, routes it through
  `handle_message(user, text, channel="telegram", session_id=...)`, collects the
  reply, and sends it back with `sendMessage`.
- **Reuse the ongoing Telegram session** per user (continue the latest
  `chat_sessions` row with channel `telegram`, or create one on first message)
  so Telegram conversations keep context.
- **Allowlist**: only the single user's `users.telegram_chat_id` is served.
  Linking happens via `/start` (trust-on-first-use: the first `/start` binds the
  sender's chat id to the user; afterwards only that chat is served, others get a
  polite "not authorized").
- **Lifespan wiring**: the poller starts as a background task in the app
  lifespan (`main.py`) — but only when `TELEGRAM_BOT_TOKEN` is set, so local runs
  and CI without a token simply skip it.
- No new dependency: use the already-installed `httpx` against the Bot API. No
  schema change (`users.telegram_chat_id` already exists).
- Docs: `backend/README.md` gains a short "Telegram" section; `.env.example`
  already has `TELEGRAM_BOT_TOKEN`.

## Capabilities

### New Capabilities
- `telegram`: an authorized Telegram long-poll channel that routes messages
  through the one-brain handler and replies via the Bot API, with a chat-id
  allowlist and per-user session continuity.

### Modified Capabilities
<!-- none — web-chat behavior is unchanged; the handler is reused as-is -->

## Impact

- **Code:** new `backend/app/channels/telegram.py`; `main.py` lifespan starts the
  poller; possibly a tiny `channels/__init__.py` helper. `handle_message` is used
  unchanged.
- **Config:** `TELEGRAM_BOT_TOKEN` (already in settings/.env.example). Optional
  `telegram_poll_timeout` default.
- **Dependencies:** none new (`httpx` already installed).
- **Testing:** unit-test the update-handling logic (allowlist, routing, reply)
  with a faked Bot API + faked `handle_message`; no live Telegram in CI.
- **Runtime:** the bot works while the backend runs locally (long-poll is
  outbound); no hosting required to test on mobile.
