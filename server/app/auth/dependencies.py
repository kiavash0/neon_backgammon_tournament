from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.security import InvalidToken, decode_token
from app.storage.base import StorageBackend, User

_bearer_scheme = HTTPBearer(auto_error=False)


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    storage: StorageBackend = Depends(get_storage),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = decode_token(credentials.credentials, "access")
    except InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from exc

    user = storage.get_user(payload["sub"])
    if user is None or user.is_deleted:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return user
