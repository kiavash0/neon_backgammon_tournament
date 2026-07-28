from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import service
from app.auth.dependencies import get_current_user, get_storage
from app.auth.schemas import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from app.storage.base import StorageBackend, User

router = APIRouter()


def _room_situation(
    storage: StorageBackend, user: User
) -> tuple[dict | None, str | None, str | None]:
    if user.current_room_id is None:
        return None, None, None
    room = storage.get_room(user.current_room_id)
    if room is None:
        return None, None, None
    room_info = {
        "id": room.id,
        "capacity": room.capacity,
        "joined": len(room.player_ids),
        "state": room.state,
    }
    if room.state != "TOURNAMENT_RUNNING":
        return room_info, None, None
    tournament = next(
        (t for t in storage.list_tournaments(status="RUNNING") if t.room_id == room.id), None
    )
    if tournament is None:
        return room_info, None, None
    active_match = next(
        (
            m
            for m in storage.list_matches(tournament.id)
            if m.status in ("PENDING", "RUNNING")
            and user.id in (m.player_white_id, m.player_black_id)
        ),
        None,
    )
    return room_info, tournament.id, active_match.id if active_match else None


def _to_me_response(storage: StorageBackend, user: User) -> MeResponse:
    room_info, tournament_id, match_id = _room_situation(storage, user)
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        dob=user.dob,
        country=user.country,
        created_at=user.created_at,
        balance_usd=storage.get_balance(user.id),
        current_room=room_info,
        active_tournament_id=tournament_id,
        active_match_id=match_id,
    )


@router.post("/auth/signup", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, storage: StorageBackend = Depends(get_storage)) -> MeResponse:
    try:
        user = service.signup(
            storage,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            dob=body.dob,
            country=body.country.upper(),
        )
    except service.SignupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _to_me_response(storage, user)


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, storage: StorageBackend = Depends(get_storage)) -> TokenResponse:
    try:
        access, refresh_token = service.login(storage, email=body.email, password=body.password)
    except service.AccountLocked as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
    except service.LoginError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return TokenResponse(access_token=access, refresh_token=refresh_token)


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh_tokens(
    body: RefreshRequest, storage: StorageBackend = Depends(get_storage)
) -> TokenResponse:
    try:
        access, refresh_token = service.refresh(storage, refresh_token=body.refresh_token)
    except service.LoginError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return TokenResponse(access_token=access, refresh_token=refresh_token)


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user),
    storage: StorageBackend = Depends(get_storage),
) -> MeResponse:
    return _to_me_response(storage, user)
