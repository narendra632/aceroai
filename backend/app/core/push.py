"""Sending an encrypted notification to a browser.

Web push in five steps, of which this module is step three:

    1. The browser asks ITS OWN push service (Chrome -> Google FCM, Firefox -> Mozilla,
       Safari -> Apple) for a subscription: an endpoint URL plus two keys.
    2. The frontend posts that subscription to us; we store it.
    3. -> We encrypt the payload with those keys, sign a VAPID token proving the sender
       is us, and POST to the endpoint.
    4. The push service wakes the browser, even with the app closed.
    5. The service worker's `push` handler shows the notification.

**The payload is encrypted end to end.** Google relays the ciphertext and cannot read it,
which is worth knowing given what this application holds.

`pywebpush` is used for the encryption and `py_vapid` for the signature, but **not** for the
HTTP request — `WebPusher.encode()` produces the body without sending, so the request goes
through `httpx`, which this application already uses. That keeps one HTTP client in the app
rather than two, and leaves `aiohttp` (which `pywebpush` pulls in) unimported at runtime on
a 1 GB machine.

Sending is **synchronous**. Every caller — the job runner and the test-notification route —
already runs on a threadpool thread, so blocking there is free, while an async sender would
mean starting or borrowing an event loop from a worker thread. One user has one or two
devices; sequential sends are not a bottleneck worth that complexity.

Everything here is built lazily: importing this module must not require any key, because CI
has none.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# After aes128gcm framing. Measured on a realistic payload: 191 bytes. The limit exists
# because the payload is meant to be a POINTER — the substance lives in the app.
MAX_PAYLOAD_BYTES = 4096

SEND_TIMEOUT_S = 10.0

#: (endpoint, body, headers) -> HTTP status. Substituted in tests so that encryption and
#: VAPID signing stay real and only the network is replaced.
Transport = Callable[[str, bytes, dict[str, str]], int]


class PushGone(Exception):
    """The subscription is permanently dead: delete it, never retry it.

    Raised on 404/410, which is what a push service returns once a browser has been
    uninstalled or its storage cleared. Retrying these forever is how a notification system
    quietly gets slower every month.
    """


class PushFailed(Exception):
    """A transient or unexpected failure. The subscription is kept."""


@dataclass(frozen=True)
class Subscription:
    """The parts of a browser subscription needed to send to it."""

    endpoint: str
    p256dh: str
    auth: str

    def as_info(self) -> dict:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def configured() -> bool:
    """Whether push can be sent at all. False in CI and in a fresh checkout."""
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def _vapid_headers(endpoint: str) -> dict[str, str]:
    """Sign a VAPID token for this endpoint's origin.

    Imported inside the function so that a missing key is an error at SEND time, with a
    clear message, rather than an ImportError at startup on a machine that has no keys.
    """
    from urllib.parse import urlsplit

    from py_vapid import Vapid01

    parts = urlsplit(endpoint)
    audience = f"{parts.scheme}://{parts.netloc}"
    # `from_string`, not `from_raw`. It inspects the decoded length and accepts either the
    # raw 32-byte scalar or a DER/PKCS8 blob. `from_raw` accepts only the former and fails
    # with `ValueError: Invalid EC key` on the latter — which is exactly what a key pasted
    # from a different tool is likely to be, and an unreadable error at 7:30am is a bad way
    # to find that out.
    vapid = Vapid01.from_string(settings.vapid_private_key)
    return vapid.sign({"aud": audience, "sub": settings.vapid_subject})


def encode(subscription: Subscription, payload: dict) -> bytes:
    """Encrypt a payload for one subscription. No network, which is what makes the whole
    sender testable in CI."""
    from pywebpush import WebPusher

    raw = json.dumps(payload, separators=(",", ":")).encode()
    encoded = WebPusher(subscription.as_info()).encode(raw)
    body = encoded["body"]
    if len(body) > MAX_PAYLOAD_BYTES:
        raise PushFailed(f"payload is {len(body)} bytes, over the {MAX_PAYLOAD_BYTES} limit")
    return body


def headers_for(subscription: Subscription, *, ttl: int, urgency: str) -> dict[str, str]:
    return {
        **_vapid_headers(subscription.endpoint),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        # How long the push service holds this for a device that is offline. Required by
        # FCM; without it Chrome rejects the request outright.
        "TTL": str(ttl),
        "Urgency": urgency,
    }


def send(
    subscription: Subscription,
    payload: dict,
    *,
    ttl: int,
    urgency: str = "normal",
    transport: Transport | None = None,
) -> None:
    """Deliver one notification. Raises `PushGone` or `PushFailed`; never returns a status
    the caller has to interpret.

    `transport` exists so tests can substitute the network. Encryption and signing are real
    in tests — only the POST is replaced — which is why this path is genuinely covered in
    CI rather than mocked at the top.
    """
    if not configured():
        raise PushFailed("no VAPID keys configured")

    body = encode(subscription, payload)
    headers = headers_for(subscription, ttl=ttl, urgency=urgency)
    post = transport or _http_post

    status = post(subscription.endpoint, body, headers)

    if status in (404, 410):
        raise PushGone(f"subscription gone ({status})")
    if status >= 400:
        # The response body is deliberately not logged: it is a third party's text, and
        # this application's redaction rules exist because a secret once reached a log.
        raise PushFailed(f"push service returned {status}")


def _http_post(endpoint: str, body: bytes, headers: dict[str, str]) -> int:
    try:
        with httpx.Client(timeout=SEND_TIMEOUT_S) as client:
            return client.post(endpoint, content=body, headers=headers).status_code
    except httpx.HTTPError as exc:
        raise PushFailed(type(exc).__name__) from exc
