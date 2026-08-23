"""Production hardening: startup secret check, cookie attributes, and the
SOUL_PATH persona override."""

import pytest

from app.config import DEV_JWT_SECRET, settings
from app.core import composer
from app.main import check_production_config
from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def test_prod_with_default_secret_refuses_to_start(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "jwt_secret", DEV_JWT_SECRET)
    with pytest.raises(RuntimeError):
        check_production_config()


def test_prod_with_real_secret_is_fine(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "jwt_secret", "a-real-secret")
    check_production_config()  # no raise


def test_dev_with_default_secret_is_fine(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "jwt_secret", DEV_JWT_SECRET)
    check_production_config()  # no raise


def test_login_cookie_uses_configured_attributes(client, user, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200
    cookie = r.headers.get("set-cookie", "").lower()
    assert "secure" in cookie
    assert "samesite=none" in cookie


def test_soul_path_override_is_used(monkeypatch, tmp_path):
    persona = tmp_path / "SOUL.md"
    persona.write_text("PERSONA-FROM-SOUL-PATH", encoding="utf-8")
    monkeypatch.setattr(settings, "soul_path", str(persona))

    assert composer._read_persona() == "PERSONA-FROM-SOUL-PATH"


def test_httpx_request_logging_is_silenced():
    """Telegram embeds the bot token in the URL path, and httpx logs full request URLs at
    INFO — so the secret was written to the console and to production logs on every poll.
    Confirmed live in this app's own logs before this was fixed."""
    import logging

    from app.main import configure_logging

    configure_logging()

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
    # Our own logs must still be visible — the point is to hide URLs, not go quiet.
    assert logging.getLogger("aceroai.timing").level <= logging.INFO


def test_secrets_are_scrubbed_from_log_text_including_tracebacks():
    """Silencing httpx was necessary and NOT sufficient. The token also travels inside the
    exception message — `HTTPStatusError` embeds the failing URL — and that text is
    rendered by the formatter, well after any filter on the record has run. Verified live:
    the token was still in the logs after httpx was raised to WARNING.
    """
    import logging

    from app.main import RedactingFormatter

    fmt = RedactingFormatter("%(message)s")
    token = "bot8661034745:AAEP7sRaeg-o6dr4XmukfcSEyqxKk8BeKN4"

    def render(message: str, exc: Exception | None = None) -> str:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, message, (), None)
        if exc is not None:
            record.exc_info = (type(exc), exc, None)
        return fmt.format(record)

    # 1. in a plain message
    assert token not in render(f"calling https://api.telegram.org/{token}/getUpdates")
    # 2. in an exception's text, which is where it survived the first fix
    leaked = RuntimeError(f"409 for url 'https://api.telegram.org/{token}/getUpdates'")
    rendered = render("poll failed", leaked)
    assert token not in rendered
    assert "AAEP7sRaeg" not in rendered
    # 3. generic credential-bearing query parameters
    assert "sk-abc123secret" not in render("GET /v1?api_key=sk-abc123secret&x=1")
    # Redaction must not swallow the surrounding message.
    assert "poll failed" in rendered


# --- .env.example must not silently override a code default ------------------------


def test_env_example_does_not_pin_a_stale_default():
    """`.env.example` is copied to make a real `.env`, so a numeric value pinned there
    becomes the effective setting on every machine that copied it — permanently, and
    invisibly, even after the code default moves.

    Found live: the template pinned `MEMORY_RECALL_K=12` from before the default became
    16, so the running app was still recalling 12 while every document said 16. The
    Learn page's constants endpoint is what surfaced it, by showing the value actually
    in force rather than the one in the source.

    Strings are exempt — a URL, a region or a model name is genuinely environment-specific
    and is *meant* to be set here.
    """
    import re
    from pathlib import Path

    from app.config import Settings

    example = Path(__file__).resolve().parents[2] / ".env.example"
    pinned = dict(
        re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", example.read_text(encoding="utf-8"), re.M)
    )

    stale = []
    for name, field in Settings.model_fields.items():
        default = field.default
        if default is None or isinstance(default, str):
            continue
        value = pinned.get(name.upper())
        if value is None:
            continue
        if value.strip() != str(default):
            stale.append(f"{name.upper()}={value.strip()} but the code default is {default}")

    assert not stale, (
        "`.env.example` pins a value that no longer matches the code default:\n  "
        + "\n  ".join(stale)
        + "\nComment it out so the default applies, or update it deliberately."
    )
