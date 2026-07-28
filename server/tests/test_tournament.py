from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("TOURNAMENT_GET_READY_SECONDS", "0.1")
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


def user_id(client, token):
    return client.get("/me", headers=auth_headers(token)).json()["id"]


def drain_until(ws, types):
    while True:
        msg = ws.receive_json()
        if msg["type"] in types:
            return msg


def play_match(ws_a, ws_b, mid):
    ws_a.send_json({"type": "match_ready", "mid": mid})
    ws_b.send_json({"type": "match_ready", "mid": mid})
    ws_a.receive_json()  # match_start
    ws_b.receive_json()  # match_start

    for _ in range(1000):
        msg_a = drain_until(ws_a, ("state", "match_result"))
        msg_b = drain_until(ws_b, ("state", "match_result"))
        if msg_a["type"] == "match_result":
            return msg_a
        if msg_b["type"] == "match_result":
            return msg_b
        mover_ws, mover_msg = (ws_a, msg_a) if msg_a["your_turn"] else (ws_b, msg_b)
        mover_ws.send_json({"type": "move", "mid": mid, "seq": mover_msg["legal_moves"][0]})

    raise AssertionError("match did not terminate within the safety cap")


def test_eight_player_tournament_completes_end_to_end(client):
    tokens = [signup_and_login(client, f"p{i}") for i in range(8)]
    ids = [user_id(client, t) for t in tokens]

    room_id = next(r["id"] for r in client.get("/lobby").json()["rooms"] if r["capacity"] == 8)

    with ExitStack() as stack:
        sockets = {
            ids[i]: stack.enter_context(client.websocket_connect(f"/ws?token={tokens[i]}"))
            for i in range(8)
        }

        for i in range(8):
            client.post(f"/rooms/{room_id}/join", headers=auth_headers(tokens[i]))

        for uid in ids:
            start = drain_until(sockets[uid], ("tournament_start",))
            assert start["capacity"] == 8

        tournament_id = next(t.id for t in app.state.storage.list_tournaments(status="RUNNING"))

        # -- round 1: 8 players, 4 matches --
        round1_mid_by_user = {}
        for uid in ids:
            msg = drain_until(sockets[uid], ("round_start",))
            assert msg["round"] == 1
            round1_mid_by_user[uid] = msg["mid"]

        round1_pairs: dict[str, list[str]] = {}
        for uid, mid in round1_mid_by_user.items():
            round1_pairs.setdefault(mid, []).append(uid)
        assert len(round1_pairs) == 4

        round1_winners = []
        for mid, (u_a, u_b) in round1_pairs.items():
            result = play_match(sockets[u_a], sockets[u_b], mid)
            round1_winners.append(result["winner_user_id"])
        assert len(round1_winners) == 4

        # -- round 2: 4 survivors, 2 matches --
        round2_mid_by_user = {}
        for uid in round1_winners:
            msg = drain_until(sockets[uid], ("round_start",))
            assert msg["round"] == 2
            round2_mid_by_user[uid] = msg["mid"]

        round2_pairs: dict[str, list[str]] = {}
        for uid, mid in round2_mid_by_user.items():
            round2_pairs.setdefault(mid, []).append(uid)
        assert len(round2_pairs) == 2

        round2_winners = []
        for mid, (u_a, u_b) in round2_pairs.items():
            result = play_match(sockets[u_a], sockets[u_b], mid)
            round2_winners.append(result["winner_user_id"])
        assert len(round2_winners) == 2

        # -- round 3 (final): 2 survivors, 1 match --
        round3_mid_by_user = {}
        for uid in round2_winners:
            msg = drain_until(sockets[uid], ("round_start",))
            assert msg["round"] == 3
            round3_mid_by_user[uid] = msg["mid"]

        (final_mid,) = set(round3_mid_by_user.values())
        u_a, u_b = round2_winners
        result = play_match(sockets[u_a], sockets[u_b], final_mid)
        champion = result["winner_user_id"]

        tournament_result = drain_until(sockets[champion], ("tournament_result",))
        assert tournament_result["tid"] == tournament_id
        assert tournament_result["winner_user_id"] == champion
        assert tournament_result["prize_usd_est"] > 0

    tournament = app.state.storage.get_tournament(tournament_id)
    assert tournament.status == "FINISHED"
    assert tournament.winner_user_id == champion
    assert tournament.prize_usd_est > 0

    room = app.state.storage.get_room(room_id)
    assert room.state == "FINISHED"

    assert app.state.storage.get_balance(champion) == tournament.prize_usd_est

    # 7 matches total for an 8-player single-elim bracket (n - 1).
    all_matches = app.state.storage.list_matches(tournament_id)
    assert len(all_matches) == 7
    assert all(m.status in ("FINISHED", "FORFEITED") for m in all_matches)
