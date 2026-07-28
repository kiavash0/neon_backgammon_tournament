from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_user, get_storage
from app.lobby import service
from app.lobby.schemas import room_to_dict, room_update_message
from app.storage.base import StorageBackend, User
from app.tournament.orchestrator import start_tournament

router = APIRouter()


@router.get("/lobby")
def list_lobby(storage: StorageBackend = Depends(get_storage)) -> dict:
    rooms = storage.list_rooms(state=service.OPEN)
    return {"rooms": [room_to_dict(r) for r in rooms]}


@router.post("/rooms/{room_id}/join")
async def join_room(
    room_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    try:
        result = service.join_room(storage, room_id=room_id, user_id=user.id)
    except service.RoomNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (service.AlreadyInRoomError, service.RoomNotJoinableError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.RoomError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    manager = request.app.state.lobby_manager
    await manager.broadcast(room_update_message(result.room))
    if result.replacement_room is not None:
        await manager.broadcast(room_update_message(result.replacement_room))
    if result.left_room is not None:
        await manager.broadcast(room_update_message(result.left_room))

    if result.room.state == service.FULL:
        await start_tournament(request.app, result.room)

    return room_to_dict(result.room)


@router.post("/rooms/{room_id}/leave")
async def leave_room(
    room_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> dict:
    try:
        room = service.leave_room(storage, room_id=room_id, user_id=user.id)
    except service.RoomNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.RoomNotJoinableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.RoomError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    manager = request.app.state.lobby_manager
    await manager.broadcast(room_update_message(room))

    return room_to_dict(room)
