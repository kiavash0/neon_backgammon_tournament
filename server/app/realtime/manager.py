"""Connection registry for the single /ws endpoint (SPEC §6.3). Phase A5
only implements the lobby channel; `subscribe_tournament`/match messages
land in A6/A7 without needing a different endpoint or manager shape.
"""

from fastapi import WebSocket


class LobbyConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for connection in self._connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self._connections.discard(connection)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


class UserConnectionRegistry:
    """Tracks each user's single live WebSocket connection so match/tournament
    handlers can push a message to a specific player. Also implements
    SPEC §5.4: a second device logging in transfers the session by kicking
    the old socket, rather than allowing duplicate connections.
    """

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def register(self, user_id: str, websocket: WebSocket) -> None:
        old = self._connections.get(user_id)
        if old is not None and old is not websocket:
            try:
                await old.close(code=4000)
            except Exception:
                pass
        self._connections[user_id] = websocket

    def unregister(self, user_id: str, websocket: WebSocket) -> None:
        if self._connections.get(user_id) is websocket:
            del self._connections[user_id]

    def get(self, user_id: str) -> WebSocket | None:
        return self._connections.get(user_id)

    def is_connected(self, user_id: str) -> bool:
        return user_id in self._connections

    async def send(self, user_id: str, message: dict) -> None:
        websocket = self._connections.get(user_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
        except Exception:
            pass
