"""Password hashing and JWT issuance/verification (SPEC §6.1: argon2id
password hashing, JWT access (15 min) + refresh (30 d))."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

_hasher = PasswordHasher()


class InvalidToken(Exception):
    """Raised when a JWT is malformed, expired, or of the wrong type."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-secret-change-me-please-32bytes-min")


def _create_token(user_id: str, token_type: str, ttl: timedelta, now: datetime | None) -> str:
    now = now or datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_access_token(user_id: str, now: datetime | None = None) -> str:
    return _create_token(user_id, "access", ACCESS_TOKEN_TTL, now)


def create_refresh_token(user_id: str, now: datetime | None = None) -> str:
    return _create_token(user_id, "refresh", REFRESH_TOKEN_TTL, now)


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidToken(f"expected a {expected_type!r} token")
    return payload
