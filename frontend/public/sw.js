/* Acero's service worker: an offline shell, and the surface push notifications land on.
 *
 * Hand-written rather than generated. `vite-plugin-pwa` brings Workbox and a build-time
 * configuration layer to produce a precache manifest; this needs two things — an offline
 * shell and a `push` listener — and the caching strategy chosen below needs no generated
 * manifest at all:
 *
 *   navigation      -> network first, falling back to the cached shell
 *   hashed assets   -> cache first (they are content-addressed; they cannot go stale)
 *   API requests    -> never touched (cross-origin, authenticated, always fresh)
 *
 * The one thing to be careful about: this file must NOT be cached by the CDN, or a new
 * version can never replace it. See `vercel.json`.
 */

const VERSION = "acero-v1";
const SHELL = "/";

// Bumping VERSION is the entire cache-invalidation story: `activate` deletes every cache
// that is not the current one.
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll([SHELL]))
      // A failed precache must not block installation — the page still works online, and
      // an uninstallable worker means no notifications at all.
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isAsset(url) {
  return url.origin === self.location.origin && /\/assets\/.+\.[0-9a-f]{8,}\./.test(url.pathname);
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // The user's data is NEVER served from a cache. The API is a different origin and every
  // response is authenticated and current; a stale task list is worse than an error.
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(VERSION).then((cache) => cache.put(SHELL, copy));
          return response;
        })
        .catch(() => caches.match(SHELL).then((cached) => cached || Response.error())),
    );
    return;
  }

  if (isAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put(request, copy));
            return response;
          }),
      ),
    );
  }
});

/* --- notifications ---------------------------------------------------------------- */

self.addEventListener("push", (event) => {
  // The payload arrived encrypted and the browser has already decrypted it. If anything
  // is malformed, still show SOMETHING: the alternative is a push that was delivered,
  // billed and silently dropped, which is indistinguishable from a broken subscription.
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }

  const title = data.title || "Acero";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "",
      // Colour icon for the notification itself; the badge MUST be a flat white
      // silhouette or Android renders it as a grey blob.
      icon: "/icon-192.png",
      badge: "/badge-mono.png",
      // Same tag replaces rather than stacks, so a second overdue-task nudge supersedes
      // the first instead of building a pile.
      tag: data.tag || "acero",
      renotify: Boolean(data.tag),
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Focus a window that is already open rather than opening a second one — the common
      // case is the app already running on another tab or in the background.
      for (const client of clients) {
        if (new URL(client.url).origin === self.location.origin) {
          client.navigate(target).catch(() => undefined);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});

/* A subscription can be replaced by the browser without the user doing anything — after a
 * long idle period, or when storage is reclaimed. Re-subscribing here and telling the
 * server keeps notifications working without a second permission prompt. Without this the
 * subscription simply dies and nothing ever arrives again. */
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(
    (async () => {
      const old = event.oldSubscription || (await self.registration.pushManager.getSubscription());
      const key = event.newSubscription
        ? null
        : old && old.options && old.options.applicationServerKey;
      const fresh =
        event.newSubscription ||
        (await self.registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key,
        }));

      const api = self.__ACERO_API__;
      const token = self.__ACERO_TOKEN__;
      if (!api || !token || !fresh) return;

      const json = fresh.toJSON();
      await fetch(`${api}/api/notifications/push`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          endpoint: json.endpoint,
          p256dh: json.keys.p256dh,
          auth: json.keys.auth,
        }),
      }).catch(() => undefined);
    })(),
  );
});

/* The page hands the worker what it needs to re-register a rotated subscription. A service
 * worker cannot read localStorage, so these arrive by message instead — and they are held
 * in memory only, never persisted. */
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "acero-config") {
    self.__ACERO_API__ = data.api;
    self.__ACERO_TOKEN__ = data.token;
  }
});
