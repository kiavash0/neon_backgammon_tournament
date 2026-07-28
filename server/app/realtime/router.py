from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.auth.security import InvalidToken, decode_token
from app.lobby.schemas import room_to_dict
from app.match.ws_handlers import handle_message, handle_player_disconnected
from app.storage.base import StorageBackend

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    storage: StorageBackend = websocket.app.state.storage
    token = websocket.query_params.get("token")
    user = None
    if token:
        try:
            payload = decode_token(token, "access")
            user = storage.get_user(payload["sub"])
        except InvalidToken:
            user = None

    if user is None or user.is_deleted:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    lobby_manager = websocket.app.state.lobby_manager
    connections = websocket.app.state.connections
    await lobby_manager.connect(websocket)
    await connections.register(user.id, websocket)

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "subscribe_lobby":
                rooms = storage.list_rooms(state="OPEN")
                await websocket.send_json(
                    {"type": "lobby_snapshot", "rooms": [room_to_dict(r) for r in rooms]}
                )
            else:
                await handle_message(websocket.app, user, message)
    except WebSocketDisconnect:
        lobby_manager.disconnect(websocket)
        connections.unregister(user.id, websocket)
        await handle_player_disconnected(websocket.app, user.id)
