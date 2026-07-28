import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    with TestClient(app) as c:
        yield c


SIGNUP_BODY = {
    "email": "bob@example.com",
    "password": "hunter22",
    "display_name": "Bob",
    "dob": "1990-05-01",
    "country": "ie",
}


def test_signup_returns_profile_with_zero_balance(client):
    resp = client.post("/auth/signup", json=SIGNUP_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "bob@example.com"
    assert body["country"] == "IE"  # normalized to uppercase
    assert body["balance_usd"] == 0.0


def test_signup_rejects_underage(client):
    body = {**SIGNUP_BODY, "email": "kid@example.com", "dob": "2015-01-01"}
    resp = client.post("/auth/signup", json=body)
    assert resp.status_code == 400


def test_signup_rejects_duplicate_email(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    resp = client.post("/auth/signup", json=SIGNUP_BODY)
    assert resp.status_code == 400


def test_signup_rejects_short_password(client):
    body = {**SIGNUP_BODY, "email": "short@example.com", "password": "abc"}
    resp = client.post("/auth/signup", json=body)
    assert resp.status_code == 422


def test_login_then_me_roundtrip(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    login_resp = client.post(
        "/auth/login", json={"email": "bob@example.com", "password": "hunter22"}
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    me_resp = client.get(
        "/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "bob@example.com"


def test_login_rejects_wrong_password(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    resp = client.post("/auth/login", json={"email": "bob@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_rejects_unknown_email(client):
    resp = client.post("/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_bad_credential_lockout_returns_423(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    for _ in range(5):
        client.post("/auth/login", json={"email": "bob@example.com", "password": "wrong"})

    resp = client.post(
        "/auth/login", json={"email": "bob@example.com", "password": "hunter22"}
    )
    assert resp.status_code == 423


def test_me_without_token_is_401(client):
    resp = client.get("/me")
    assert resp.status_code == 401


def test_me_with_garbage_token_is_401(client):
    resp = client.get("/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_refresh_flow(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    login_resp = client.post(
        "/auth/login", json={"email": "bob@example.com", "password": "hunter22"}
    )
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 200
    new_access = refresh_resp.json()["access_token"]

    me_resp = client.get("/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me_resp.status_code == 200


def test_refresh_rejects_access_token(client):
    client.post("/auth/signup", json=SIGNUP_BODY)
    login_resp = client.post(
        "/auth/login", json={"email": "bob@example.com", "password": "hunter22"}
    )
    access_token = login_resp.json()["access_token"]

    resp = client.post("/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401
