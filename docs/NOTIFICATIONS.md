# NOTIFICATIONS.md — how Acero reaches you

> Plain language first. The work that *produces* notifications is in
> [`JOBS.md`](JOBS.md); the architecture is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 1. The rule everything else follows

> **A notification is a database row. Push is one way of drawing attention to it.**

The row is written **before** any attempt is made to send anything. That ordering is the
whole design, and it survives every way delivery can fail:

- you refused notification permission
- your laptop was closed
- it was 2am and quiet hours suppressed it
- you had already had six notifications that day
- the push failed
- you swiped it off the lockscreen while walking

In every one of those cases the notification still exists, in the bell at the top of the app.
A system whose only memory of *"two tasks are overdue"* is a toast you dismissed is not a
system that reduces what you have to keep in your head.

**A failed push is not failed work.** The job that raised the notification is recorded as
successful; the failure is recorded against the *device*. Conflating them would make a phone
left in a drawer look like broken software.

---

## 2. How web push actually works

Five participants, and four of them belong to somebody else.

```
1. Your browser asks ITS OWN push service for a subscription.
   Chrome -> Google (FCM).  Firefox -> Mozilla.  Safari -> Apple.
   We do not choose; the browser does.
   It returns: an endpoint URL + two keys (p256dh, auth)

2. The page sends that subscription to our API, which stores it.

3. When something happens, the server:
     - encrypts the payload with YOUR BROWSER'S keys   (aes128gcm)
     - signs a short-lived token proving the sender is us   (VAPID)
     - POSTs the ciphertext to the endpoint URL

4. The push service wakes your device — even with the app closed.

5. The service worker's `push` handler runs and shows the notification.
   Tapping it focuses the app at the right screen.
```

**The payload is encrypted end to end.** Google relays the ciphertext and cannot read it.
Worth knowing, given what this application holds.

---

## 3. VAPID keys

A single P-256 key pair identifying this server to every push service.

```bash
cd backend
uv run python -m app.scripts.generate_vapid
```

It prints a public and a private key and **writes nothing** — you paste them into `.env`
yourself.

- `VAPID_PUBLIC_KEY` — genuinely public. It is served to the browser, and the frontend needs
  it as `VITE_VAPID_PUBLIC_KEY` to subscribe at all.
- `VAPID_PRIVATE_KEY` — a secret. It lives only in `.env`, is never serialised into any
  response, and a test asserts it never appears in the push-status payload.
- `VAPID_SUBJECT` — a contact URI (`mailto:` or `https:`) the push service can use to reach
  the operator about a misbehaving sender. Required by the spec.

⚠ **Generate this once.** Every existing subscription is bound to the public key it was
created with, so replacing the pair silently invalidates every device that has already
subscribed. They keep their permission and simply stop receiving anything — the worst kind of
failure, because nothing reports it.

---

## 4. The details that bite

**Dead subscriptions must be deleted, not retried.** A push service returns `404` or `410
Gone` once a browser has been uninstalled or its storage cleared. Ignoring that accumulates
endpoints that every job then pays for, forever. Acero deletes on those two codes and keeps
the subscription on anything else.

**Subscriptions rotate on their own.** A browser can replace one without the user doing
anything. The service worker listens for `pushsubscriptionchange`, re-subscribes and re-posts
— without a second permission prompt. Without that handler the subscription simply dies.

**The payload is ~4 KB after encryption.** So it carries `{title, body, url, tag}` and
nothing else. It is a **pointer**; the substance lives in the app. Measured, a realistic
payload encrypts to **191 bytes**.

**`TTL` is required.** It says how long the push service should hold a message for a device
that is offline. Chrome rejects a request without it. Acero uses 24 hours for a summary and
4 hours for a nudge — a stale reminder is worse than none.

**`tag` coalesces.** Two notifications sharing a tag replace one another on the device rather
than stacking, so a second overdue-task nudge supersedes the first instead of building a
pile.

**The badge must be monochrome.** Android renders the small status-bar badge as a silhouette;
a colour icon becomes a grey blob. `public/badge-mono.png` is a flat white shape on
transparent, and that is deliberate.

---

## 5. ⚠ iPhone and iPad

**Web push works on iOS only if the app has been added to the Home Screen** (Safari 16.4+).
Not "works worse" — does not work at all. On Android Chrome and on desktop it works without
installing.

That is Apple's rule and there is nothing to engineer around it. The app detects the
situation and says so *before* you try, rather than leaving you waiting for a notification
that will never arrive.

Narendra uses a **Pixel with Chrome**, where installing is optional.

---

## 6. When nothing arrives

This is the part worth reading twice, because five parties are involved and four are somebody
else's.

**Start with the test button.** Settings → Notifications → *Send a test*. It bypasses quiet
hours and the daily cap on purpose — you asked for this one — and every refusal names the
cause rather than failing silently.

Then, in order:

| Symptom | Cause | Fix |
|---|---|---|
| "This server has no notification keys configured" | `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` missing | Generate them, put them in `.env`, restart the API |
| "No device is subscribed yet" | Permission granted but never subscribed | Press *Turn on for this device* |
| "Notifications are blocked for this site" | Permission was refused at some point | **The app cannot ask again.** Re-allow in the browser's site settings |
| Nothing at all on iPhone | Not installed to the Home Screen | Share → Add to Home Screen |
| Test works, real ones do not | Quiet hours, the daily cap, or the job is off | Check the bell — the row will be there with no send time. Check Settings → the job's toggle |
| Worked yesterday, silent today | Subscription died | The next send gets a `410` and removes it. Re-subscribe |
| Nothing after a deploy | A cached `sw.js` | It is served `no-cache` by `vercel.json`; hard-refresh, and check Application → Service Workers |

**Reading the record.** A notification with `pushed_at = NULL` was written but never reached a
device — that is not a bug, it is the system telling you which of the above happened.

**Reading the logs.** The server logs the reason a push was suppressed
(`notification X recorded but not pushed: quiet hours`) and records the failure on the
subscription row (`last_error`, `last_error_at`).

---

## 7. What gets pushed

**Now:**

| Kind | From | When |
|---|---|---|
| `morning_brief` | `morning_brief` | 07:30 |
| `day_end_summary` | `day_end_summary` | 21:00 |
| `task_overdue` | `task_nudge` | Hourly 09–21, coalesced, once per changed set |
| `budget` | `budget_watch` | Once at 80% of the month's limit, once at 100% |
| `journal_empty` | `journal_nudge` | 20:30, **off by default** |
| `test` | the button | On demand |

**Later:** a weekly review, a memory conflict needing review, disk usage on the VM, an MCP
action awaiting approval.

---

## 8. Interrupting less

Three controls, all applied centrally so no individual job can forget them:

| Control | Default | Effect |
|---|---|---|
| Per-job toggle | from the registry | Off means the job does not run at all — not merely silenced |
| Quiet hours | 22:00 – 07:00 | Row **is** written; the push is suppressed. It is in the bell in the morning |
| Daily cap | 6 | Beyond it, rows are written and pushes dropped |

Quiet hours default to the server setting when unset. **Equal start and end means off** — a
zero-length window is no window, and it is the only available encoding, because NULL already
means "use the default". The Settings toggle writes `0/0`.

---

## 9. Where the code is

```
backend/app/core/push.py                encryption, VAPID signing, the send
backend/app/services/notifications.py   the store-then-deliver rule, and the policy
backend/app/api/notifications.py        list, mark read, subscribe, test
backend/app/scripts/generate_vapid.py   the one-time key generation

frontend/public/sw.js                   receives the push, shows it, handles the click
frontend/src/lib/push.ts                permission, subscribe, unsubscribe
frontend/src/components/NotificationBell.tsx       the bell and its panel
frontend/src/components/NotificationSettings.tsx   turning it on, and the job toggles
frontend/vercel.json                    keeps sw.js out of the CDN cache
```

Tests: `backend/tests/test_notifications.py` and `test_api_notifications.py`. They use a fake
**transport** rather than a fake sender — encryption and VAPID signing are real, and only the
HTTP POST is replaced, so the two parts most likely to be subtly wrong are genuinely
exercised in CI.
