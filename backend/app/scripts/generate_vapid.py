"""Generate the one keypair that lets this server send push notifications.

    uv run python -m app.scripts.generate_vapid

Prints a public and a private key. **Writes nothing** — this repository's tooling never
touches `.env`; you paste them in yourself.

VAPID is how a push service knows a message is from you rather than from anyone who happens
to have found a subscription endpoint. The private key signs a short-lived token on every
send; the public key is handed to the browser at subscribe time so it can bind the
subscription to you.

**Generate this ONCE.** Every existing subscription is bound to the public key it was
created with, so replacing the pair silently invalidates every device that has already
subscribed — they keep their permission and simply stop receiving anything. Recovering means
unsubscribing and re-subscribing on each device.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(raw: bytes) -> str:
    """URL-safe base64 with padding stripped — the form the Web Push spec uses."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def generate() -> tuple[str, str]:
    """Return (public_key, private_key), both base64url."""
    private = ec.generate_private_key(ec.SECP256R1())
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    # The RAW 32-byte private scalar — the conventional Web Push form, and what every
    # other VAPID tool emits. DER/PKCS8 also loads (see `core/push._vapid`), but a key
    # generated here should look like a key generated anywhere else.
    private_raw = private.private_numbers().private_value.to_bytes(32, "big")
    return _b64(public_raw), _b64(private_raw)


def main() -> int:
    # ASCII only, deliberately. A Windows console defaults to cp1252, which cannot encode
    # the warning sign or an em dash — and this crashed with UnicodeEncodeError on the
    # first real run, which would have been the very first command anyone typed after
    # reading the setup docs. A setup script that dies on the platform it is run from is
    # worse than no script.
    public, private = generate()
    print("VAPID keypair generated. Add these to .env - this script writes nothing.\n")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("VAPID_SUBJECT=mailto:you@example.com   # a real contact for the push service\n")
    print(
        "The frontend needs nothing. It fetches the public key from\n"
        "GET /api/notifications/push, so there is one source of truth and rotating the\n"
        "pair needs no frontend rebuild.\n"
    )
    print(
        "WARNING: generate this ONCE. Replacing the pair invalidates every device that\n"
        "has already subscribed: they keep their permission and quietly receive nothing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
