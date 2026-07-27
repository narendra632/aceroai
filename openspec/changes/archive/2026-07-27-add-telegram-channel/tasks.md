## 1. Bot API client

- [ ] 1.1 In `channels/telegram.py`, thin async helpers over `httpx` for `getUpdates(offset, timeout)` and `sendMessage(chat_id, text)` using `settings.telegram_bot_token`
- [ ] 1.2 A helper to load the single user and resolve/create their ongoing `telegram` session (DB work via `run_in_threadpool`)

## 2. Update handling (the thin adapter)

- [ ] 2.1 `handle_update(update)`: extract chat_id + text; enforce the allowlist (linked `users.telegram_chat_id`); handle `/start` linking (trust-on-first-use) and the not-authorized reply
- [ ] 2.2 For authorized text: call `handle_message(db, user, text, "telegram", session_id)`, accumulate `delta` events into the full reply, `sendMessage` once; surface `error` events as a short message
- [ ] 2.3 Keep all conversation logic in the handler — the channel only transports (golden rule 1)

## 3. Poller lifecycle

- [ ] 3.1 `run_poller()`: loop `getUpdates` with a long timeout, advance `offset` past processed updates, try/except with short backoff so one bad update never kills the loop
- [ ] 3.2 `main.py` lifespan: start the poller as an `asyncio` task only when `telegram_bot_token` is set; cancel it cleanly on shutdown

## 4. Tests + docs

- [ ] 4.1 `tests/test_telegram.py`: fake Bot API (monkeypatch send/get) + fake `handle_message`; assert allowlist enforcement, `/start` linking, routing + reply, and stranger rejection — no live Telegram
- [ ] 4.2 Confirm the app still imports/starts with no token (poller skipped); `uv run pytest` + `ruff` green
- [ ] 4.3 `backend/README.md`: short "Telegram channel" section (how it works, `/start` linking, that no hosting is needed to test)

## 5. Manual verify (needs your bot token)

- [ ] 5.1 With `TELEGRAM_BOT_TOKEN` in `.env`, run the backend; send `/start` then a message from your phone; confirm the reply and that the turns persist under a `telegram` session
