from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def test_login_success_sets_cookie_and_returns_token(client, user):
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == TEST_EMAIL
    assert body["token"]  # returned for cross-site header auth
    assert "access_token" in r.cookies


def test_bearer_token_authenticates(client, user):
    token = client.post(
        "/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    ).json()["token"]
    client.cookies.clear()  # prove it's the header, not the cookie
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"email": TEST_EMAIL}


def test_bad_bearer_token_rejected(client):
    client.cookies.clear()
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_login_wrong_password(client, user):
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": "nope"})
    assert r.status_code == 401
    assert "access_token" not in r.cookies


def test_login_unknown_email(client):
    r = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"})
    assert r.status_code == 401


def test_protected_route_requires_cookie(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/chat/sessions").status_code == 401


def test_me_and_logout(auth_client):
    assert auth_client.get("/api/auth/me").json() == {"email": TEST_EMAIL}
    assert auth_client.post("/api/auth/logout").status_code == 200
    assert auth_client.get("/api/auth/me").status_code == 401
