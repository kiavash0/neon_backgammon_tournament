from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.lobby.router import router as lobby_router
from app.lobby.service import ensure_pools
from app.match.runtime import MatchRuntimeManager
from app.realtime.manager import (
    LobbyConnectionManager,
    TournamentConnectionManager,
    UserConnectionRegistry,
)
from app.realtime.router import router as realtime_router
from app.security.fraud_gate import assert_safe_to_boot
from app.storage.factory import get_storage_backend
from app.tournament.orchestrator import recover_tournaments
from app.tournament.router import router as tournament_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    assert_safe_to_boot()
    app.state.storage = get_storage_backend()
    app.state.lobby_manager = LobbyConnectionManager()
    app.state.connections = UserConnectionRegistry()
    app.state.tournament_connections = TournamentConnectionManager()
    app.state.match_runtimes = MatchRuntimeManager()
    ensure_pools(app.state.storage)
    await recover_tournaments(app)
    yield
    app.state.storage.close()


app = FastAPI(title="Neon Backgammon Tournament", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(lobby_router)
app.include_router(tournament_router)
app.include_router(realtime_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
