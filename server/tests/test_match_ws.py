import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.match.runtime import MatchRuntimeManager
from app.storage.base import Match


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


def user_id(client, token):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def create_pending_match(white_id, black_id):
    match = Match(
        id=uuid.uuid4().hex,
        tournament_id="t-test",
        round_number=1,
        player_white_id=white_id,
        player_black_id=black_id,
        status="PENDING",
    )
    return app.state.storage.create_match(match)


def drain_until_state_or_result(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] in ("state", "match_result"):
            return msg


def drain_until_result(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "match_result":
            return msg


# -- full game -------------------------------------------------------------


def test_full_game_over_two_websocket_clients(client):
    token_w = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")
    white_id, black_id = user_id(client, token_w), user_id(client, token_b)
    match = create_pending_match(white_id, black_id)

    with (
        client.websocket_connect(f"/ws?token={token_w}") as ws_w,
        client.websocket_connect(f"/ws?token={token_b}") as ws_b,
    ):
        ws_w.send_json({"type": "match_ready", "mid": match.id})
        ws_b.send_json({"type": "match_ready", "mid": match.id})

        start_w = ws_w.receive_json()
        start_b = ws_b.receive_json()
        assert start_w["type"] == "match_start"
        assert start_b["type"] == "match_start"
        assert {start_w["your_color"], start_b["your_color"]} == {1, -1}

        result = None
        for _ in range(1000):
            msg_w = drain_until_state_or_result(ws_w)
            msg_b = drain_until_state_or_result(ws_b)
            if msg_w["type"] == "match_result":
                result = msg_w
                break
            if msg_b["type"] == "match_result":
                result = msg_b
                break

            mover_msg, mover_ws = (msg_w, ws_w) if msg_w["your_turn"] else (msg_b, ws_b)
            options = mover_msg["legal_moves"]
            assert options, "server must never hand the client an empty choice"
            mover_ws.send_json({"type": "move", "mid": match.id, "seq": options[0]})

        assert result is not None, "game did not terminate within the safety cap"
        assert result["winner_user_id"] in (white_id, black_id)
        assert result["reason"] == "bear_off"

        finished = app.state.storage.get_match(match.id)
        assert finished.status == "FINISHED"
        assert finished.winner_id == result["winner_user_id"]


# -- resign / illegal input --------------------------------------------


def test_resign_ends_match_immediately(client):
    token_w = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")
    white_id, black_id = user_id(client, token_w), user_id(client, token_b)
    match = create_pending_match(white_id, black_id)

    with (
        client.websocket_connect(f"/ws?token={token_w}") as ws_w,
        client.websocket_connect(f"/ws?token={token_b}") as ws_b,
    ):
        ws_w.send_json({"type": "match_ready", "mid": match.id})
        ws_b.send_json({"type": "match_ready", "mid": match.id})
        ws_w.receive_json()  # match_start
        ws_b.receive_json()  # match_start
        drain_until_state_or_result(ws_w)  # dice + state for turn 1
        drain_until_state_or_result(ws_b)

        ws_w.send_json({"type": "resign", "mid": match.id})

        result_b = drain_until_result(ws_b)
        assert result_b["winner_user_id"] == black_id
        assert result_b["reason"] == "resign"


def test_illegal_move_returns_error_and_match_continues(client):
    token_w = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")
    white_id, black_id = user_id(client, token_w), user_id(client, token_b)
    match = create_pending_match(white_id, black_id)

    with (
        client.websocket_connect(f"/ws?token={token_w}") as ws_w,
        client.websocket_connect(f"/ws?token={token_b}") as ws_b,
    ):
        ws_w.send_json({"type": "match_ready", "mid": match.id})
        ws_b.send_json({"type": "match_ready", "mid": match.id})
        start_w = ws_w.receive_json()
        ws_b.receive_json()

        mover_ws, mover_token = (ws_w, token_w) if start_w["your_color"] == 1 else (ws_b, token_b)
        state_msg = drain_until_state_or_result(mover_ws)
        assert state_msg["your_turn"] is True

        mover_ws.send_json({"type": "move", "mid": match.id, "seq": [[0, 1, 99]]})
        err = mover_ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "illegal_move"

        assert app.state.storage.get_match(match.id).status == "RUNNING"


def test_move_out_of_turn_is_rejected(client):
    token_w = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")
    white_id, black_id = user_id(client, token_w), user_id(client, token_b)
    match = create_pending_match(white_id, black_id)

    with (
        client.websocket_connect(f"/ws?token={token_w}") as ws_w,
        client.websocket_connect(f"/ws?token={token_b}") as ws_b,
    ):
        ws_w.send_json({"type": "match_ready", "mid": match.id})
        ws_b.send_json({"type": "match_ready", "mid": match.id})
        start_w = ws_w.receive_json()
        ws_b.receive_json()
        drain_until_state_or_result(ws_w)
        drain_until_state_or_result(ws_b)

        waiting_ws = ws_b if start_w["your_color"] == 1 else ws_w
        waiting_ws.send_json({"type": "move", "mid": match.id, "seq": [[23, 20, 3]]})
        err = waiting_ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "not_your_turn"


def test_ws_rejects_missing_or_invalid_token(client):
    with pytest.raises(Exception):  # noqa: B017 - starlette raises WebSocketDisconnect on reject
        with client.websocket_connect("/ws?token=garbage"):
            pass


# -- turn timeout ------------------------------------------------------


def test_turn_timeout_forfeits_the_turn_and_play_continues(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("TURN_TIMEOUT_SECONDS", "0.2")
    with TestClient(app) as client:
        token_w = signup_and_login(client, "alice")
        token_b = signup_and_login(client, "bob")
        white_id, black_id = user_id(client, token_w), user_id(client, token_b)
        match = create_pending_match(white_id, black_id)

        with (
            client.websocket_connect(f"/ws?token={token_w}") as ws_w,
            client.websocket_connect(f"/ws?token={token_b}") as ws_b,
        ):
            ws_w.send_json({"type": "match_ready", "mid": match.id})
            ws_b.send_json({"type": "match_ready", "mid": match.id})
            start_w = ws_w.receive_json()
            ws_b.receive_json()
            mover_ws = ws_w if start_w["your_color"] == 1 else ws_b
            waiting_ws = ws_b if mover_ws is ws_w else ws_w

            first_state = drain_until_state_or_result(mover_ws)
            assert first_state["your_turn"] is True
            drain_until_state_or_result(waiting_ws)

            # neither side ever sends a move -> mover's timer expires and their
            # turn is forfeited (no checkers moved) or forced if only one option.
            opponent_move = waiting_ws.receive_json()
            assert opponent_move["type"] == "opponent_move"
            assert opponent_move.get("timeout") is True

            # play now continues: the opponent must have received a fresh turn.
            next_state = drain_until_state_or_result(waiting_ws)
            assert next_state["type"] == "state"


def test_three_consecutive_timeouts_forfeits_the_match(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("TURN_TIMEOUT_SECONDS", "0.15")
    with TestClient(app) as client:
        token_w = signup_and_login(client, "alice")
        token_b = signup_and_login(client, "bob")
        white_id, black_id = user_id(client, token_w), user_id(client, token_b)
        match = create_pending_match(white_id, black_id)

        with (
            client.websocket_connect(f"/ws?token={token_w}") as ws_w,
            client.websocket_connect(f"/ws?token={token_b}") as ws_b,
        ):
            ws_w.send_json({"type": "match_ready", "mid": match.id})
            ws_b.send_json({"type": "match_ready", "mid": match.id})
            ws_w.receive_json()
            ws_b.receive_json()

            result = None
            for _ in range(200):
                msg = ws_w.receive_json()
                if msg["type"] == "match_result":
                    result = msg
                    break

            assert result is not None
            assert result["reason"] == "forfeit_timeout"
            assert result["winner_user_id"] in (white_id, black_id)


# -- disconnect / reconnect ----------------------------------------------


def test_reconnect_within_grace_avoids_forfeit(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("RECONNECT_GRACE_SECONDS", "5")
    with TestClient(app) as client:
        token_w = signup_and_login(client, "alice")
        token_b = signup_and_login(client, "bob")
        white_id, black_id = user_id(client, token_w), user_id(client, token_b)
        match = create_pending_match(white_id, black_id)

        with client.websocket_connect(f"/ws?token={token_b}") as ws_b:
            with client.websocket_connect(f"/ws?token={token_w}") as ws_w:
                ws_w.send_json({"type": "match_ready", "mid": match.id})
                ws_b.send_json({"type": "match_ready", "mid": match.id})
                ws_w.receive_json()
                ws_b.receive_json()
            # ws_w block exited -> white disconnected

            time.sleep(0.3)
            assert app.state.storage.get_match(match.id).status == "RUNNING"

            with client.websocket_connect(f"/ws?token={token_w}") as ws_w2:
                ws_w2.send_json({"type": "match_ready", "mid": match.id})
                resumed = ws_w2.receive_json()
                assert resumed["type"] == "state"

            assert app.state.storage.get_match(match.id).status == "RUNNING"


def test_disconnect_past_grace_forfeits_to_opponent(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("RECONNECT_GRACE_SECONDS", "0.2")
    with TestClient(app) as client:
        token_w = signup_and_login(client, "alice")
        token_b = signup_and_login(client, "bob")
        white_id, black_id = user_id(client, token_w), user_id(client, token_b)
        match = create_pending_match(white_id, black_id)

        with client.websocket_connect(f"/ws?token={token_b}") as ws_b:
            with client.websocket_connect(f"/ws?token={token_w}") as ws_w:
                ws_w.send_json({"type": "match_ready", "mid": match.id})
                ws_b.send_json({"type": "match_ready", "mid": match.id})
                ws_w.receive_json()  # match_start
                ws_b.receive_json()  # match_start
                drain_until_state_or_result(ws_b)  # dice + state for turn 1

            time.sleep(0.6)
            result = drain_until_result(ws_b)
            assert result["winner_user_id"] == black_id
            assert result["reason"] == "forfeit_disconnect"

        finished = app.state.storage.get_match(match.id)
        assert finished.status == "FINISHED"
        assert finished.winner_id == black_id


def test_both_players_disconnected_ends_in_double_forfeit(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("STORAGE_PATH", ":memory:")
    monkeypatch.setenv("RECONNECT_GRACE_SECONDS", "0.2")
    monkeypatch.setenv("BOTH_DISCONNECT_GRACE_SECONDS", "0.4")
    with TestClient(app) as client:
        token_w = signup_and_login(client, "alice")
        token_b = signup_and_login(client, "bob")
        white_id, black_id = user_id(client, token_w), user_id(client, token_b)
        match = create_pending_match(white_id, black_id)

        with client.websocket_connect(f"/ws?token={token_w}") as ws_w:
            with client.websocket_connect(f"/ws?token={token_b}") as ws_b:
                ws_w.send_json({"type": "match_ready", "mid": match.id})
                ws_b.send_json({"type": "match_ready", "mid": match.id})
                ws_w.receive_json()
                ws_b.receive_json()
            # ws_b closed here

        # ws_w closed here too -> both disconnected

        time.sleep(1.0)
        finished = app.state.storage.get_match(match.id)
        assert finished.status == "FINISHED"
        assert finished.winner_id in (white_id, black_id)


def test_resume_after_process_restart_gets_playable_state(client):
    """Regression test: a real server restart wipes MatchRuntime (dice live
    only in memory), but match.game_state is persisted (SPEC §5.2 crash
    recovery). A resuming player must get a real dice roll and non-empty
    legal_moves, not a stale "your_turn: true, legal_moves: []" dead end."""
    token_w = signup_and_login(client, "alice")
    token_b = signup_and_login(client, "bob")
    white_id, black_id = user_id(client, token_w), user_id(client, token_b)
    match = create_pending_match(white_id, black_id)

    with (
        client.websocket_connect(f"/ws?token={token_w}") as ws_w,
        client.websocket_connect(f"/ws?token={token_b}") as ws_b,
    ):
        ws_w.send_json({"type": "match_ready", "mid": match.id})
        ws_b.send_json({"type": "match_ready", "mid": match.id})
        start_w = ws_w.receive_json()
        ws_b.receive_json()
        drain_until_state_or_result(ws_w)
        drain_until_state_or_result(ws_b)

    mover_token = token_w if start_w["your_color"] == 1 else token_b

    # simulate a process restart: storage (the sqlite file/connection)
    # survives, but every in-memory runtime is gone.
    app.state.match_runtimes = MatchRuntimeManager()

    with client.websocket_connect(f"/ws?token={mover_token}") as ws_resumed:
        ws_resumed.send_json({"type": "match_ready", "mid": match.id})
        resumed = drain_until_state_or_result(ws_resumed)
        assert resumed["your_turn"] is True
        assert resumed["legal_moves"], "resumed turn must be playable, not a dead end"
