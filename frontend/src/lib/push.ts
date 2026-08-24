/* Registering the service worker, and subscribing this browser to notifications.
 *
 * The permission model is the part worth understanding, because it is unforgiving:
 *
 *   "default"  - not asked yet. We may ask, ONCE, and only from a user gesture.
 *   "granted"  - subscribed, or can be.
 *   "denied"   - **the app can never ask again.** Only the user can undo this, in browser
 *                settings. So the UI has to say so rather than offering a button that
 *                silently does nothing.
 *
 * ⚠ On iOS, web push works ONLY after the app is installed to the home screen (Safari
 * 16.4+). On Android Chrome and desktop it works without installing. That is Apple's rule,
 * not something to engineer around — `pushBlockedReason` reports it so the interface can
 * be honest up front instead of leaving the user waiting for a notification that will
 * never arrive.
 */

import * as api from "./api";

export type PermissionState = "unsupported" | "default" | "granted" | "denied";

const SW_URL = "/sw.js";

export function supported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // iOS Safari predates the standard and reports it here instead.
    (navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

export function isIos(): boolean {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    // iPadOS 13+ reports itself as a Mac; the touch points give it away.
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

/** Why push cannot work here, or null when it can. Shown before the user tries. */
export function pushBlockedReason(): string | null {
  if (!supported()) return "This browser does not support notifications.";
  if (isIos() && !isStandalone()) {
    return "On iPhone and iPad, notifications only work once Acero is added to the Home Screen.";
  }
  return null;
}

export function permission(): PermissionState {
  if (!supported()) return "unsupported";
  return Notification.permission as PermissionState;
}

export async function register(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  try {
    const registration = await navigator.serviceWorker.register(SW_URL, {
      scope: "/",
    });
    void sendConfig(registration);
    return registration;
  } catch {
    // A failed registration must never break the app. It costs offline support and
    // notifications; everything else works exactly as before.
    return null;
  }
}

/** Hand the worker what it needs to re-register a rotated subscription.
 *
 *  A service worker cannot read localStorage, which is where the auth token lives, so it
 *  arrives by message and is held in the worker's memory only. */
async function sendConfig(
  registration: ServiceWorkerRegistration,
): Promise<void> {
  const worker =
    registration.active ?? (await navigator.serviceWorker.ready).active;
  const token = api.getToken();
  if (!worker || !token) return;
  worker.postMessage({
    type: "acero-config",
    api: import.meta.env.VITE_API_URL,
    token,
  });
}

/** VAPID public keys travel as base64url; `applicationServerKey` wants raw bytes.
 *
 *  Typed against `ArrayBuffer` explicitly: TypeScript's `Uint8Array` is generic over
 *  `ArrayBufferLike`, which includes `SharedArrayBuffer`, and `applicationServerKey` will
 *  not accept that union. Allocating the buffer first pins it. */
function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

export type SubscribeResult = { ok: true } | { ok: false; reason: string };

export async function subscribe(publicKey: string): Promise<SubscribeResult> {
  const blocked = pushBlockedReason();
  if (blocked) return { ok: false, reason: blocked };
  if (!publicKey) {
    return {
      ok: false,
      reason: "This server has no notification keys configured.",
    };
  }

  // MUST be called from a user gesture, and only once — a "denied" is permanent from the
  // app's side.
  const granted = await Notification.requestPermission();
  if (granted !== "granted") {
    return {
      ok: false,
      reason:
        granted === "denied"
          ? "Notifications are blocked for this site. You can re-allow them in your browser's site settings — Acero cannot ask again."
          : "Notifications were not enabled.",
    };
  }

  const registration =
    (await register()) ?? (await navigator.serviceWorker.ready);
  if (!registration)
    return { ok: false, reason: "The background worker could not start." };

  try {
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ??
      (await registration.pushManager.subscribe({
        // Required: the browser will not permit a silent push.
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      }));

    const json = subscription.toJSON();
    if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
      return {
        ok: false,
        reason: "The browser returned an incomplete subscription.",
      };
    }
    await api.subscribePush({
      endpoint: json.endpoint,
      p256dh: json.keys.p256dh,
      auth: json.keys.auth,
    });
    void sendConfig(registration);
    return { ok: true };
  } catch {
    return { ok: false, reason: "Could not subscribe to notifications." };
  }
}

export async function unsubscribe(): Promise<void> {
  if (!supported()) return;
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  // Tell the server FIRST. If the browser unsubscribes and the POST then fails, the
  // server keeps an endpoint that can never be delivered to — it would eventually be
  // cleaned up by a 410, but only after wasting a send on every notification until then.
  await api.unsubscribePush(subscription.endpoint).catch(() => undefined);
  await subscription.unsubscribe().catch(() => undefined);
}

export async function hasSubscription(): Promise<boolean> {
  if (!supported()) return false;
  const registration = await navigator.serviceWorker.getRegistration();
  return Boolean(await registration?.pushManager.getSubscription());
}
