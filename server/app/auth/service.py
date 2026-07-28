"""Signup / login / refresh business logic. Talks only to StorageBackend,
never to a specific database (SPEC §3).
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.auth.security import (
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.storage.base import StorageBackend, User

MIN_AGE_YEARS = 18  # SPEC §2.5: age gate 18+ at signup
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class SignupError(Exception):
    """Signup request cannot be fulfilled (bad age, duplicate email, ...)."""


class LoginError(Exception):
    """Generic auth failure — always a 401, never reveals which check failed."""


class AccountLocked(LoginError):
    """Too many recent failed logins; distinct so callers can 423 instead of 401."""


def _age_years(dob: date, today: date) -> int:
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def signup(
    storage: StorageBackend,
    *,
    email: str,
    password: str,
    display_name: str,
    dob: date,
    country: str,
    now: datetime | None = None,
) -> User:
    now = now or datetime.now(UTC)

    if _age_years(dob, now.date()) < MIN_AGE_YEARS:
        raise SignupError(f"must be at least {MIN_AGE_YEARS} years old to sign up")
    if storage.get_user_by_email(email) is not None:
        raise SignupError("an account with this email already exists")

    user = User(
        id=uuid.uuid4().hex,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        dob=dob.isoformat(),
        country=country,
        created_at=now.isoformat(),
    )
    return storage.create_user(user)


def login(
    storage: StorageBackend, *, email: str, password: str, now: datetime | None = None
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    user = storage.get_user_by_email(email)

    if user is None or user.is_deleted:
        # Same generic error as a wrong password: don't reveal whether the email exists.
        raise LoginError("invalid email or password")

    if user.locked_until and datetime.fromisoformat(user.locked_until) > now:
        raise AccountLocked("account temporarily locked due to repeated failed logins")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = (now + LOCKOUT_DURATION).isoformat()
        storage.update_user(user)
        raise LoginError("invalid email or password")

    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        storage.update_user(user)

    return create_access_token(user.id, now), create_refresh_token(user.id, now)


def refresh(
    storage: StorageBackend, *, refresh_token: str, now: datetime | None = None
) -> tuple[str, str]:
    now = now or datetime.now(UTC)
    try:
        payload = decode_token(refresh_token, "refresh")
    except InvalidToken as exc:
        raise LoginError("invalid or expired refresh token") from exc

    user = storage.get_user(payload["sub"])
    if user is None or user.is_deleted:
        raise LoginError("invalid or expired refresh token")

    return create_access_token(user.id, now), create_refresh_token(user.id, now)
