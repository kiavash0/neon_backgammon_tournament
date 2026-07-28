"""Lobby room-pool logic (SPEC §5.1): fixed-size room pools that
auto-replenish the instant a room fills, and the "one room at a time"
join rule. Tournament start itself (FULL -> TOURNAMENT_RUNNING) is out of
scope here — that's the tournament manager's job (Phase A7).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.lobby.config import ALL_CAPACITIES, target_pool_size
from app.storage.base import Room, StorageBackend

OPEN = "OPEN"
FULL = "FULL"


class RoomError(Exception):
    """Base class for lobby/room errors."""


class RoomNotFoundError(RoomError):
    pass


class RoomNotJoinableError(RoomError):
    pass


class AlreadyInRoomError(RoomError):
    pass


class UserNotFoundError(RoomError):
    pass


@dataclass
class JoinResult:
    room: Room
    replacement_room: Room | None  # set when this join filled the room
    left_room: Room | None = None  # set when joining auto-switched out of another OPEN room


def ensure_pools(storage: StorageBackend, now: datetime | None = None) -> list[Room]:
    """Idempotent: top up every capacity's OPEN room count to its pool
    target. Safe to call on every startup."""
    now = now or datetime.now(UTC)
    created: list[Room] = []
    for capacity in ALL_CAPACITIES:
        existing = len(storage.list_rooms(capacity=capacity, state=OPEN))
        target = target_pool_size(capacity)
        for _ in range(target - existing):
            created.append(_spawn_room(storage, capacity, now))
    return created


def _spawn_room(storage: StorageBackend, capacity: int, now: datetime | None = None) -> Room:
    now = now or datetime.now(UTC)
    room = Room(id=uuid.uuid4().hex, capacity=capacity, state=OPEN, created_at=now.isoformat())
    return storage.create_room(room)


def join_room(
    storage: StorageBackend, *, room_id: str, user_id: str, now: datetime | None = None
) -> JoinResult:
    room = storage.get_room(room_id)
    if room is None:
        raise RoomNotFoundError(f"room {room_id!r} does not exist")

    user = storage.get_user(user_id)
    if user is None or user.is_deleted:
        raise UserNotFoundError("user not found")

    if user_id in room.player_ids:
        return JoinResult(room=room, replacement_room=None)  # idempotent re-join

    left_room = None
    if user.current_room_id is not None:
        prior = storage.get_room(user.current_room_id)
        if prior is None or prior.state in ("FINISHED", "CANCELLED"):
            # Stale registration (room long gone) — self-heal instead of
            # locking the user out of the lobby forever.
            user.current_room_id = None
        elif prior.state == OPEN:
            # Joining a different room while waiting in an OPEN one just
            # switches rooms — still "at most one room at a time" (SPEC §5.1),
            # without forcing the user through a manual leave first.
            if user_id in prior.player_ids:
                prior.player_ids.remove(user_id)
                storage.update_room(prior)
                left_room = prior
            user.current_room_id = None
        else:
            # FULL / TOURNAMENT_RUNNING: a tournament is pending or active —
            # that registration can't be abandoned by clicking another room.
            raise AlreadyInRoomError("you are in an active tournament")

    if room.state != OPEN or len(room.player_ids) >= room.capacity:
        raise RoomNotJoinableError("room is not open for joining")

    room.player_ids.append(user_id)
    user.current_room_id = room_id
    storage.update_user(user)

    replacement = None
    if len(room.player_ids) >= room.capacity:
        room.state = FULL
        replacement = _spawn_room(storage, room.capacity, now)
    storage.update_room(room)

    return JoinResult(room=room, replacement_room=replacement, left_room=left_room)


def leave_room(storage: StorageBackend, *, room_id: str, user_id: str) -> Room:
    room = storage.get_room(room_id)
    if room is None:
        raise RoomNotFoundError(f"room {room_id!r} does not exist")
    if room.state != OPEN:
        raise RoomNotJoinableError("can only leave a room while it is still open")
    if user_id not in room.player_ids:
        raise RoomError("user is not in this room")

    room.player_ids.remove(user_id)
    storage.update_room(room)

    user = storage.get_user(user_id)
    if user is not None:
        user.current_room_id = None
        storage.update_user(user)

    return room
