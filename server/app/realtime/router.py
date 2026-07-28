from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.lobby.schemas import room_to_dict
from app.storage.base import StorageBackend

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    manager = websocket.app.state.lobby_manager
    storage: StorageBackend = websocket.app.state.storage
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "subscribe_lobby":
                rooms = storage.list_rooms(state="OPEN")
                await websocket.send_json(
                    {"type": "lobby_snapshot", "rooms": [room_to_dict(r) for r in rooms]}
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
