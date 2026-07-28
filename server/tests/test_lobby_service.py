from datetime import UTC, date, datetime

import pytest

from app.auth import service as auth_service
from app.lobby import service
from app.lobby.config import ALL_CAPACITIES, LARGE_CAPACITIES, SMALL_CAPACITIES
from app.storage.factory import get_storage_backend

NOW = datetime(2026, 7, 28, tzinfo=UTC)


@pytest.fixture
def storage():
    b = get_storage_backend(backend="sqlite", path=":memory:")
    yield b
    b.close()


def make_user(storage, tag):
    return auth_service.signup(
        storage,
        email=f"{tag}@example.com",
        password="hunter22",
        display_name=tag,
        dob=date(1990, 1, 1),
        country="IE",
        now=NOW,
    )


# -- pool init -----------------------------------------------------------


def test_ensure_pools_creates_expected_counts(storage):
    service.ensure_pools(storage, now=NOW)
    for cap in SMALL_CAPACITIES:
        assert len(storage.list_rooms(capacity=cap, state=service.OPEN)) == 20
    for cap in LARGE_CAPACITIES:
        assert len(storage.list_rooms(capacity=cap, state=service.OPEN)) == 1


def test_ensure_pools_is_idempotent(storage):
    service.ensure_pools(storage, now=NOW)
    second_batch = service.ensure_pools(storage, now=NOW)
    assert second_batch == []
    for cap in ALL_CAPACITIES:
        assert len(storage.list_rooms(capacity=cap, state=service.OPEN)) == (
            20 if cap in SMALL_CAPACITIES else 1
        )


# -- join / leave ------------------------------------------------------


def test_join_adds_player_and_broadcastable_state(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=2, state=service.OPEN)[0]
    user = make_user(storage, "alice")

    result = service.join_room(storage, room_id=room.id, user_id=user.id, now=NOW)

    assert user.id in result.room.player_ids
    assert result.replacement_room is None
    assert storage.get_user(user.id).current_room_id == room.id


def test_join_is_idempotent_for_same_room(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=4, state=service.OPEN)[0]
    user = make_user(storage, "alice")

    first = service.join_room(storage, room_id=room.id, user_id=user.id, now=NOW)
    second = service.join_room(storage, room_id=room.id, user_id=user.id, now=NOW)

    assert first.room.player_ids == second.room.player_ids
    assert second.room.player_ids.count(user.id) == 1


def test_cannot_join_second_room_while_registered(storage):
    service.ensure_pools(storage, now=NOW)
    room_a, room_b = storage.list_rooms(capacity=2, state=service.OPEN)[:2]
    user = make_user(storage, "alice")

    service.join_room(storage, room_id=room_a.id, user_id=user.id, now=NOW)

    with pytest.raises(service.AlreadyInRoomError):
        service.join_room(storage, room_id=room_b.id, user_id=user.id, now=NOW)


def test_join_missing_room_raises(storage):
    user = make_user(storage, "alice")
    with pytest.raises(service.RoomNotFoundError):
        service.join_room(storage, room_id="ghost", user_id=user.id, now=NOW)


def test_room_fills_and_replenishes_immediately(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=2, state=service.OPEN)[0]
    alice = make_user(storage, "alice")
    bob = make_user(storage, "bob")

    r1 = service.join_room(storage, room_id=room.id, user_id=alice.id, now=NOW)
    assert r1.room.state == service.OPEN
    assert r1.replacement_room is None

    r2 = service.join_room(storage, room_id=room.id, user_id=bob.id, now=NOW)
    assert r2.room.state == service.FULL
    assert len(r2.room.player_ids) == 2
    assert r2.replacement_room is not None
    assert r2.replacement_room.capacity == 2
    assert r2.replacement_room.state == service.OPEN

    open_rooms_of_size_2 = storage.list_rooms(capacity=2, state=service.OPEN)
    assert len(open_rooms_of_size_2) == 20  # pool count preserved: one filled, one spawned


def test_leave_room_frees_the_slot(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=8, state=service.OPEN)[0]
    user = make_user(storage, "alice")
    service.join_room(storage, room_id=room.id, user_id=user.id, now=NOW)

    updated = service.leave_room(storage, room_id=room.id, user_id=user.id)

    assert user.id not in updated.player_ids
    assert storage.get_user(user.id).current_room_id is None


def test_leave_room_not_a_member_raises(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=8, state=service.OPEN)[0]
    user = make_user(storage, "alice")
    with pytest.raises(service.RoomError):
        service.leave_room(storage, room_id=room.id, user_id=user.id)


def test_cannot_leave_a_full_room(storage):
    service.ensure_pools(storage, now=NOW)
    room = storage.list_rooms(capacity=2, state=service.OPEN)[0]
    alice = make_user(storage, "alice")
    bob = make_user(storage, "bob")
    service.join_room(storage, room_id=room.id, user_id=alice.id, now=NOW)
    service.join_room(storage, room_id=room.id, user_id=bob.id, now=NOW)

    with pytest.raises(service.RoomNotJoinableError):
        service.leave_room(storage, room_id=room.id, user_id=alice.id)


def test_after_leaving_user_can_join_a_different_room(storage):
    service.ensure_pools(storage, now=NOW)
    room_a, room_b = storage.list_rooms(capacity=4, state=service.OPEN)[:2]
    user = make_user(storage, "alice")

    service.join_room(storage, room_id=room_a.id, user_id=user.id, now=NOW)
    service.leave_room(storage, room_id=room_a.id, user_id=user.id)
    result = service.join_room(storage, room_id=room_b.id, user_id=user.id, now=NOW)

    assert user.id in result.room.player_ids
