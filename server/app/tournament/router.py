from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user, get_storage
from app.storage.base import StorageBackend

router = APIRouter(dependencies=[Depends(get_current_user)])


def _tournament_to_dict(t) -> dict:
    return {
        "id": t.id,
        "room_id": t.room_id,
        "capacity": t.capacity,
        "status": t.status,
        "bracket": t.bracket,
        "winner_user_id": t.winner_user_id,
        "prize_usd_est": t.prize_usd_est,
        "created_at": t.created_at,
        "finished_at": t.finished_at,
    }


def _match_to_dict(m) -> dict:
    return {
        "id": m.id,
        "tournament_id": m.tournament_id,
        "round_number": m.round_number,
        "bracket_slot": m.bracket_slot,
        "player_white_id": m.player_white_id,
        "player_black_id": m.player_black_id,
        "status": m.status,
        "winner_id": m.winner_id,
        "game_state": m.game_state,
    }


@router.get("/tournaments/{tournament_id}")
def get_tournament(tournament_id: str, storage: StorageBackend = Depends(get_storage)) -> dict:
    tournament = storage.get_tournament(tournament_id)
    if tournament is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tournament not found")
    return _tournament_to_dict(tournament)


@router.get("/tournaments/{tournament_id}/matches/{match_id}")
def get_tournament_match(
    tournament_id: str, match_id: str, storage: StorageBackend = Depends(get_storage)
) -> dict:
    match = storage.get_match(match_id)
    if match is None or match.tournament_id != tournament_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "match not found")
    return _match_to_dict(match)
