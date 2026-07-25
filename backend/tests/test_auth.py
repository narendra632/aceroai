from tests.conftest import TEST_EMAIL, TEST_PASSWORD


def test_login_success_sets_cookie(client, user):
    r = client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert r.status_code == 200
    assert r.json() == {"email": TEST_EMAIL}
    assert "access_token" in r.cookies


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
