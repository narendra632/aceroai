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

- `VAPID_PUBLIC_KEY` — genuinely public. The frontend **fetches** it from
  `GET /api/notifications/push` rather than holding a build-time copy, so there is one source
  of truth and rotating the pair needs no frontend rebuild.
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

**⚠ `Urgency` decides whether your phone wakes up.** This is the single header that made
notifications feel unreliable, and it is worth understanding properly.

RFC 8030 defines four levels, described as the *minimum device state at which a message is
worth delivering*: `very-low` for advertisements, `low` for topic updates, `normal` for chat,
`high` for a time-sensitive alert. On Android, anything below `high` may be held while the
device is dozing and released only when it is next picked up.

Acero used to send digests as `Urgency: low`. Measured in production on 2026-08-26: the
day-end summary was dispatched at **21:03:12, zero seconds** after its row was written, and
appeared on the phone at roughly **21:40**, when it was next unlocked. Every one of the last
25 notifications had been dispatched within 0–9 seconds and no delivery error had ever been
recorded. The server was never slow — it was politely asking to be ignored, and the push
service obliged.

**Everything is now sent `high`, as a constant rather than a per-kind table.** This
application has no advertisement tier: every notification it sends is one you scheduled and
are waiting for, and a summary of your day has its entire value in arriving at the end of
that day.

This does **not** override quiet hours. Urgency tells the push service how to reach a
*sleeping device*; whether you want to be reached at all is decided earlier, and by you.

**`TTL` is required, and is derived from the job's own staleness bound.** It says how long
the push service should hold a message for a device that is offline; Chrome rejects a request
without it.

It used to come from the same hand-maintained set of kind strings as `Urgency` — 24 hours for
a summary, 4 hours for a nudge — and that set **contradicted the jobs it described**.
`day_end_summary` declares `catch_up=3h`, *"by midnight, so it still lands on the day it
describes"*, and was then handed to the push service with instructions to hold it for a full
day: to deliver the thing the runner would have refused to produce that late.
`morning_brief` said *"delivered by 11:30 or not at all"* and did the same.

A job already declares how stale its output may be. `notifications.ttl_for` turns that one
declaration into the TTL, so the two decisions cannot drift apart again:

| Job | `catch_up` | `TTL` |
|---|---|---|
| `morning_brief` | 4 h | 4 h |
| `day_end_summary` | 3 h | 3 h |
| `task_nudge` | 45 min | 45 min |
| `retention_sweep` | **none** — "however late" | four weeks (the maximum FCM accepts) |

A notification no job produced — the test push from Settings — uses `PUSH_TTL_DEFAULT_S`.

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
hours on purpose — you asked for this one — and every refusal names the cause rather than
failing silently.

Then, in order:

| Symptom | Cause | Fix |
|---|---|---|
| "This server has no notification keys configured" | `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` missing | Generate them, put them in `.env`, restart the API |
| "No device is subscribed yet" | Permission granted but never subscribed | Press *Turn on for this device* |
| "Notifications are blocked for this site" | Permission was refused at some point | **The app cannot ask again.** Re-allow in the browser's site settings |
| Nothing at all on iPhone | Not installed to the Home Screen | Share → Add to Home Screen |
| Test works, real ones do not | Quiet hours, repetition suppression, or the job is off | Check the bell — the row will be there with no send time. Check Settings → the job's toggle |
| A nudge repeats after you dismiss it | It should not — see §8 | Dismissing does not re-arm the nudge behind it. If it does, `already_said` has been taught to filter deleted rows |
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
| `task_overdue` | `task_nudge` | Checked hourly 09–19, buzzes at most every 2 h, coalesced, **repeated until addressed** |
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
| Repetition suppression | per subject | A **measurement** already reported stays quiet until it changes band. **Work you have to do** repeats until you do it |
| Daily ceiling | **0 — none** | Set it only as an escape hatch. See below |

Quiet hours default to the server setting when unset. **Equal start and end means off** — a
zero-length window is no window, and it is the only available encoding, because NULL already
means "use the default". The Settings toggle writes `0/0`.

### Why there is no daily ceiling

There used to be one, defaulting to six. `task_nudge` alone can fire six times a day, so
it was **binding in ordinary use** — which means it was silently discarding notifications
that were wanted, beginning with the most frequent one, the repeating overdue-task ping.

A ceiling reached during normal operation is not a safety limit. It is an undocumented
feature that stops telling you things after lunch.

Volume is governed instead by **the nature of the subject** — see *Saying something once* in
`JOBS.md`. A measurement is reported when it crosses into a worse band; work you still have
to do is reported until you do it. That is the right control for expected volume.

⚠ The ceiling counts **deliveries, not records**. One overdue record reminded about seven
times has interrupted you six times, and a ceiling that counted rows would let a repeating
nudge past it unchecked.

The setting is kept at `0` rather than deleted because it is the wrong control for
*unexpected* volume, and that is a real failure mode: a job that loops, or one whose tag
changes every run, is untouched by per-tag suppression. `DAILY_PUSH_CAP` is the only bound
such a job would respect. It costs one falsy check and is the difference between a bad hour
and a bad hour with no way to stop it.

### What removal does and does not change

Notifications can be removed — individually, or all the read ones at once — and restored
from the undo toast. Two things removal deliberately leaves alone:

- **A band-crossing alert stays suppressed.** `already_said` asks what has been *said*, not
  what is still on screen. Otherwise dismissing a disk warning would make the next check push
  it again.
- **An overdue reminder is not stopped by removing it.** The opposite: the situation is still
  true, so the next check writes a fresh record and buzzes again. Deal with the task or move
  its due date — those are the only two exits.
- **The day's delivered count is unchanged.** It counts *deliveries*, not surviving
  receipts. The phone already buzzed; clearing the panel does not un-buzz it. Shown in
  Settings as "N sent today".

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

---

## 10. Reading the server's condition

`GET /api/insights/vitals` — authenticated, never cached — reports disk, memory, database
size, 1-minute load, process uptime, and when the scheduler last ticked. The Insights page
polls it every 10 seconds, and **stops while the tab is hidden**: a forgotten background tab
would otherwise poll the VM about 8,600 times a day to render a page nobody is looking at,
generating load *by* the monitoring, *on* the machine being monitored.

It is deliberately **not** part of `/health`. That endpoint is unauthenticated — Caddy probes
it, and it is what proves the backend is alive from outside the network. It returns
`{"status": "ok"}` and nothing else, and a test pins that.

### ⚠ Memory and load are blank on Windows. This is not a bug.

They come from `/proc/meminfo` and `/proc/loadavg`, which exist only on Linux. On a Windows
development machine those two tiles are simply **absent**, and disk, database size and the
scheduler heartbeat are all present as normal. On the VM everything appears.

Absent rather than zero, deliberately: a zero is a wrong answer wearing the confidence of a
right one, and "0% memory pressure" is the most reassuring possible way to say "I have no
idea".

Memory reads **`MemAvailable`, not `MemFree`** — on any box running Postgres, `MemFree` is
alarming and meaningless, because the kernel has spent the rest on page cache and will
reclaim it the moment anything needs it. `MemFree` would report 98% pressure on a perfectly
healthy machine.

### The scheduler heartbeat

`last_tick` comes from the scheduler's own in-process timestamp, set every tick — **not** from
the newest `job_runs` row.

A `job_runs` row is written only when an occurrence actually fires, and the jobs cluster in
waking hours: there are six hours between the 21:00 nudge and the 03:15 sweep in which a
perfectly healthy scheduler writes nothing at all. Reading "newest job run" as a heartbeat
would report a dead scheduler every single night, and a signal that cries wolf nightly is one
nobody reads on the morning it is right.

`null` means "this process has not ticked yet" — true after a restart, and true for at most
one interval. It is read alongside uptime, which is what separates *just booted* from *the
ticker has stopped*.

This is the one failure the system could not otherwise report about itself: if the scheduler
thread dies while the API keeps serving, no request fails, no log line appears, and no job
records an error. Scheduled work simply stops happening.
