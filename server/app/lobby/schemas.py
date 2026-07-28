from app.storage.base import Room


def room_to_dict(room: Room) -> dict:
    return {
        "id": room.id,
        "capacity": room.capacity,
        "joined": len(room.player_ids),
        "state": room.state,
    }


def room_update_message(room: Room) -> dict:
    return {"type": "room_update", **room_to_dict(room)}
