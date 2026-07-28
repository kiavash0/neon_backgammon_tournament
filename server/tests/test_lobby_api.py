import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    with TestClient(app) as c:
        yield c


def signup_and_login(client, tag):
    client.post(
        "/auth/signup",
        json={
            "email": f"{tag}@example.com",
            "password": "hunter22",
            "display_name": tag,
            "dob": "1990-01-01",
            "country": "ie",
        },
    )
    resp = client.post("/auth/login", json={"email": f"{tag}@example.com", "password": "hunter22"})
    return resp.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_lobby_lists_seeded_room_pools(client):
    resp = client.get("/lobby")
    assert resp.status_code == 200
    rooms = resp.json()["rooms"]
    capacities = [r["capacity"] for r in rooms]
    assert capacities.count(2) == 20
    assert capacities.count(512) == 1
    assert all(r["state"] == "OPEN" and r["joined"] == 0 for r in rooms)


def test_join_and_leave_room(client):
    token = signup_and_login(client, "alice")
    room_id = client.get("/lobby").json()["rooms"][0]["id"]

    join_resp = client.post(f"/rooms/{room_id}/join", headers=auth_headers(token))
    assert join_resp.status_code == 200
    assert join_resp.json()["joined"] == 1

    leave_resp = client.post(f"/rooms/{room_id}/leave", headers=auth_headers(token))
    assert leave_resp.status_code == 200
    assert leave_resp.json()["joined"] == 0


def test_join_requires_auth(client):
    room_id = client.get("/lobby").json()["rooms"][0]["id"]
    resp = client.post(f"/rooms/{room_id}/join")
    assert resp.status_code == 401


def test_join_unknown_room_is_404(client):
    token = signup_and_login(client, "alice")
    resp = client.post("/rooms/does-not-exist/join", headers=auth_headers(token))
    assert resp.status_code == 404


def test_cannot_join_two_rooms_at_once(client):
    token = signup_and_login(client, "alice")
    rooms = [r["id"] for r in client.get("/lobby").json()["rooms"] if r["capacity"] == 2][:2]

    first = client.post(f"/rooms/{rooms[0]}/join", headers=auth_headers(token))
    assert first.status_code == 200

    second = client.post(f"/rooms/{rooms[1]}/join", headers=auth_headers(token))
    assert second.status_code == 409


def test_filling_a_room_spawns_a_replacement(client):
    room2_ids = [r["id"] for r in client.get("/lobby").json()["rooms"] if r["capacity"] == 2]
    room_id = room2_ids[0]

    token_a = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")

    client.post(f"/rooms/{room_id}/join", headers=auth_headers(token_a))
    fill_resp = client.post(f"/rooms/{room_id}/join", headers=auth_headers(token_b))
    assert fill_resp.status_code == 200
    assert fill_resp.json()["state"] == "FULL"

    open_size_2 = [r for r in client.get("/lobby").json()["rooms"] if r["capacity"] == 2]
    assert len(open_size_2) == 20  # still 20 open — one filled, one freshly spawned


def test_websocket_receives_room_update_broadcast(client):
    token = signup_and_login(client, "alice")
    room_id = client.get("/lobby").json()["rooms"][0]["id"]

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe_lobby"})
        snapshot = ws.receive_json()
        assert snapshot["type"] == "lobby_snapshot"

        client.post(f"/rooms/{room_id}/join", headers=auth_headers(token))

        update = ws.receive_json()
        assert update["type"] == "room_update"
        assert update["id"] == room_id
        assert update["joined"] == 1
