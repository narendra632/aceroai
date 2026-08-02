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
