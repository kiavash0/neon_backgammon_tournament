import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.storage.base import Room, Tournament, User
from app.storage.sqlite_backend import SqliteBackend
from app.tournament import orchestrator, service


class FakeConnections:
    def __init__(self):
        self.sent = []

    async def send(self, user_id, message):
        self.sent.append((user_id, message))


class FakeTournamentConnections:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, tournament_id, message):
        self.broadcasts.append((tournament_id, message))


def fake_app(storage):
    return SimpleNamespace(
        state=SimpleNamespace(
            storage=storage,
            connections=FakeConnections(),
            tournament_connections=FakeTournamentConnections(),
            match_runtimes=SimpleNamespace(get=lambda mid: None),
        )
    )


def make_user(storage, tag):
    return storage.create_user(
        User(
            id=uuid.uuid4().hex,
            email=f"{tag}@example.com",
            password_hash="x",
            display_name=tag,
            dob="1990-01-01",
            country="IE",
            created_at=datetime.now(UTC).isoformat(),
        )
    )


def test_recovery_advances_a_fully_resolved_non_final_round():
    """SPEC §5.2 crash recovery: server dies after round 1's last match
    finishes but before round 2 is generated -> restart picks it up."""
    storage = SqliteBackend(":memory:")
    users = [make_user(storage, f"u{i}") for i in range(4)]
    ids = [u.id for u in users]

    room = storage.create_room(
        Room(
            id=uuid.uuid4().hex,
            capacity=4,
            state="TOURNAMENT_RUNNING",
            created_at=datetime.now(UTC).isoformat(),
            player_ids=ids,
        )
    )
    tournament = storage.create_tournament(
        Tournament(
            id=uuid.uuid4().hex,
            room_id=room.id,
            capacity=4,
            status="RUNNING",
            bracket={"seed_order": ids, "rounds": {}},
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    round1 = service.create_round(storage, tournament, round_number=1, ordered_ids=ids)
    tournament.bracket["rounds"]["1"] = [m.id for m in round1]
    tournament = storage.update_tournament(tournament)

    # both round-1 matches "finished" as if played, but the process died
    # before the tournament manager could generate round 2.
    for i, m in enumerate(round1):
        m.status = "FINISHED"
        m.winner_id = m.player_white_id if i == 0 else m.player_black_id
        storage.update_match(m)

    app = fake_app(storage)
    asyncio.run(orchestrator.recover_tournaments(app))

    recovered = storage.get_tournament(tournament.id)
    assert recovered.status == "RUNNING"
    assert "2" in recovered.bracket["rounds"]

    round2 = [m for m in storage.list_matches(tournament.id) if m.round_number == 2]
    assert len(round2) == 1
    expected_winners = {round1[0].winner_id, round1[1].winner_id}
    assert {round2[0].player_white_id, round2[0].player_black_id} == expected_winners

    storage.close()


def test_recovery_finishes_tournament_when_final_round_resolved():
    """Crash after the final match finishes but before prize credit."""
    storage = SqliteBackend(":memory:")
    users = [make_user(storage, f"u{i}") for i in range(2)]
    ids = [u.id for u in users]

    room = storage.create_room(
        Room(
            id=uuid.uuid4().hex,
            capacity=2,
            state="TOURNAMENT_RUNNING",
            created_at=datetime.now(UTC).isoformat(),
            player_ids=ids,
        )
    )
    tournament = storage.create_tournament(
        Tournament(
            id=uuid.uuid4().hex,
            room_id=room.id,
            capacity=2,
            status="RUNNING",
            bracket={"seed_order": ids, "rounds": {}},
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    final_round = service.create_round(storage, tournament, round_number=1, ordered_ids=ids)
    tournament.bracket["rounds"]["1"] = [m.id for m in final_round]
    tournament = storage.update_tournament(tournament)

    match = final_round[0]
    match.status = "FINISHED"
    match.winner_id = match.player_white_id
    storage.update_match(match)
    service.log_match_impressions(storage, tournament.id, match)

    app = fake_app(storage)
    asyncio.run(orchestrator.recover_tournaments(app))

    recovered = storage.get_tournament(tournament.id)
    assert recovered.status == "FINISHED"
    assert recovered.winner_user_id == match.player_white_id
    assert recovered.prize_usd_est > 0
    assert storage.get_balance(match.player_white_id) == recovered.prize_usd_est

    recovered_room = storage.get_room(room.id)
    assert recovered_room.state == "FINISHED"

    storage.close()


def test_recovery_is_idempotent_and_leaves_finished_tournaments_alone():
    storage = SqliteBackend(":memory:")
    users = [make_user(storage, f"u{i}") for i in range(2)]
    ids = [u.id for u in users]
    room = storage.create_room(
        Room(
            id=uuid.uuid4().hex,
            capacity=2,
            state="FINISHED",
            created_at=datetime.now(UTC).isoformat(),
            player_ids=ids,
        )
    )
    tournament = storage.create_tournament(
        Tournament(
            id=uuid.uuid4().hex,
            room_id=room.id,
            capacity=2,
            status="FINISHED",
            bracket={"seed_order": ids, "rounds": {"1": []}},
            winner_user_id=ids[0],
            prize_usd_est=0.03,
            created_at=datetime.now(UTC).isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
        )
    )

    app = fake_app(storage)
    asyncio.run(orchestrator.recover_tournaments(app))

    unchanged = storage.get_tournament(tournament.id)
    assert unchanged.status == "FINISHED"
    assert unchanged.prize_usd_est == 0.03

    storage.close()
