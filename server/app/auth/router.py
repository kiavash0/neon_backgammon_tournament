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


def _to_me_response(storage: StorageBackend, user: User) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        dob=user.dob,
        country=user.country,
        created_at=user.created_at,
        balance_usd=storage.get_balance(user.id),
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
