"""Settings API: auth, per-user scoping, provider availability, and the guarantee that
credentials are never exposed through the UI."""

from app.config import settings


def test_requires_auth(client):
    assert client.get("/api/settings").status_code == 401
    assert client.patch("/api/settings", json={"provider": "google"}).status_code == 401


def test_read_returns_defaults_and_catalog(auth_client):
    body = auth_client.get("/api/settings").json()
    assert body["provider"] == settings.llm_provider
    assert body["model_chat"] == settings.model_chat
    assert "google" in body["model_catalog"]
    assert isinstance(body["available_providers"], list)


def test_update_models_persists(auth_client):
    r = auth_client.patch("/api/settings", json={"model_chat": "gemini-3.7-flash"})
    assert r.status_code == 200
    assert r.json()["model_chat"] == "gemini-3.7-flash"
    # survives a fresh read
    assert auth_client.get("/api/settings").json()["model_chat"] == "gemini-3.7-flash"


def test_blank_model_falls_back_to_default(auth_client):
    auth_client.patch("/api/settings", json={"model_chat": "gemini-3.7-flash"})
    body = auth_client.patch("/api/settings", json={"model_chat": ""}).json()
    assert body["model_chat"] == settings.model_chat


def test_unknown_provider_rejected(auth_client):
    r = auth_client.patch("/api/settings", json={"provider": "definitely-not-a-provider"})
    assert r.status_code == 400
    assert auth_client.get("/api/settings").json()["provider"] == settings.llm_provider


def test_unconfigured_provider_rejected(auth_client, monkeypatch):
    """OpenAI without a key must not be selectable."""
    monkeypatch.setattr(settings, "openai_api_key", "")
    r = auth_client.patch("/api/settings", json={"provider": "openai"})
    assert r.status_code == 400
    assert "openai" not in auth_client.get("/api/settings").json()["available_providers"]


def test_configured_provider_is_selectable(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    assert "openai" in auth_client.get("/api/settings").json()["available_providers"]
    assert auth_client.patch("/api/settings", json={"provider": "openai"}).json()["provider"] == (
        "openai"
    )


def test_never_exposes_credentials(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-super-secret-value")
    raw = auth_client.get("/api/settings").text
    assert "sk-super-secret-value" not in raw
    assert "api_key" not in raw


def test_embedding_shown_pinned_with_explanation(auth_client):
    emb = auth_client.get("/api/settings").json()["embedding"]
    assert emb["pinned"] is True
    assert emb["model"] == settings.embed_model
    assert emb["dimensions"] == settings.embed_dim
    assert len(emb["note"]) > 40  # a real explanation, not a label


def test_settings_are_per_user(auth_client, db, other_user):
    auth_client.patch("/api/settings", json={"model_chat": "gemini-3.7-flash"})
    db.refresh(other_user)
    assert other_user.model_chat is None  # untouched


# --- the monthly spend limit ---------------------------------------------------------


def test_budget_is_off_until_it_is_set(auth_client):
    body = auth_client.get("/api/settings").json()["budget"]
    assert body["state"] == "off"
    assert body["limit_usd"] is None
    # Spend is reported anyway, so the interface can show what a month costs BEFORE
    # asking the user to pick a ceiling out of thin air.
    assert "spent_usd" in body


def test_setting_and_raising_a_limit(auth_client):
    body = auth_client.patch("/api/settings", json={"monthly_budget_usd": "5.00"}).json()
    assert body["budget"]["limit_usd"] == "5.00"
    assert body["budget"]["state"] == "ok"

    raised = auth_client.patch("/api/settings", json={"monthly_budget_usd": "20"}).json()
    assert raised["budget"]["limit_usd"] == "20.00"


def test_turning_the_limit_off_again(auth_client):
    """`monthly_budget_usd: null` already means "not sent", so switching a limit OFF
    needs its own flag — without one it could be raised forever but never removed."""
    auth_client.patch("/api/settings", json={"monthly_budget_usd": "5.00"})

    body = auth_client.patch("/api/settings", json={"clear_budget": True}).json()

    assert body["budget"]["limit_usd"] is None
    assert body["budget"]["state"] == "off"


def test_a_zero_or_negative_limit_is_rejected(auth_client):
    """Silently storing 0 would read as "no limit" in one place and "block everything" in
    another. Refusing it keeps one meaning."""
    assert auth_client.patch("/api/settings", json={"monthly_budget_usd": "0"}).status_code == 400
    assert auth_client.patch("/api/settings", json={"monthly_budget_usd": "-3"}).status_code == 400


def test_budget_has_its_own_lightweight_route(auth_client):
    """The chat screen re-reads this after every turn and has no use for the catalogue."""
    r = auth_client.get("/api/settings/budget")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "limit_usd",
        "spent_usd",
        "remaining_usd",
        "used_ratio",
        "state",
        "resets_on",
        "warn_ratio",
    }


def test_budget_route_requires_auth(client):
    assert client.get("/api/settings/budget").status_code == 401


def test_a_budget_is_per_user(auth_client, db, other_user):
    auth_client.patch("/api/settings", json={"monthly_budget_usd": "5.00"})
    db.refresh(other_user)
    assert other_user.monthly_budget_usd is None
