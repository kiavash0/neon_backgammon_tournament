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
