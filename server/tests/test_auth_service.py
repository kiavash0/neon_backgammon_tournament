from datetime import UTC, date, datetime, timedelta

import pytest

from app.auth import service
from app.storage.factory import get_storage_backend


@pytest.fixture
def storage():
    b = get_storage_backend(backend="sqlite", path=":memory:")
    yield b
    b.close()


NOW = datetime(2026, 7, 28, tzinfo=UTC)


def signup_alice(storage, dob=date(2000, 1, 1), password="hunter22"):
    return service.signup(
        storage,
        email="alice@example.com",
        password=password,
        display_name="Alice",
        dob=dob,
        country="IE",
        now=NOW,
    )


# -- signup / age gate --------------------------------------------------


def test_signup_creates_user_with_hashed_password(storage):
    user = signup_alice(storage)
    assert user.email == "alice@example.com"
    assert user.password_hash != "hunter22"


def test_signup_rejects_duplicate_email(storage):
    signup_alice(storage)
    with pytest.raises(service.SignupError):
        signup_alice(storage)


def test_signup_rejects_under_18(storage):
    # exactly 17 years old on NOW's date
    dob = date(NOW.year - 17, NOW.month, NOW.day)
    with pytest.raises(service.SignupError):
        signup_alice(storage, dob=dob)


def test_signup_accepts_exactly_18_today(storage):
    dob = date(NOW.year - 18, NOW.month, NOW.day)
    user = signup_alice(storage, dob=dob)
    assert user is not None


def test_signup_rejects_18th_birthday_tomorrow(storage):
    tomorrow = NOW.date() + timedelta(days=1)
    dob = date(tomorrow.year - 18, tomorrow.month, tomorrow.day)
    with pytest.raises(service.SignupError):
        signup_alice(storage, dob=dob)


# -- login ---------------------------------------------------------------


def test_login_success_returns_token_pair(storage):
    signup_alice(storage)
    access, refresh = service.login(
        storage, email="alice@example.com", password="hunter22", now=NOW
    )
    assert access and refresh
    assert access != refresh


def test_login_rejects_unknown_email(storage):
    with pytest.raises(service.LoginError):
        service.login(storage, email="ghost@example.com", password="whatever", now=NOW)


def test_login_rejects_wrong_password(storage):
    signup_alice(storage)
    with pytest.raises(service.LoginError):
        service.login(storage, email="alice@example.com", password="wrong", now=NOW)


def test_failed_login_resets_on_success(storage):
    signup_alice(storage)
    for _ in range(3):
        with pytest.raises(service.LoginError):
            service.login(storage, email="alice@example.com", password="wrong", now=NOW)

    service.login(storage, email="alice@example.com", password="hunter22", now=NOW)

    user = storage.get_user_by_email("alice@example.com")
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


# -- bad-credential lockout (SPEC §10.5: rate limit / lock auth endpoints) ---


def test_account_locks_after_max_failed_attempts(storage):
    signup_alice(storage)

    for _ in range(service.MAX_FAILED_LOGIN_ATTEMPTS - 1):
        with pytest.raises(service.LoginError):
            service.login(storage, email="alice@example.com", password="wrong", now=NOW)

    user = storage.get_user_by_email("alice@example.com")
    assert user.locked_until is None  # not locked yet, one attempt short of the threshold

    with pytest.raises(service.LoginError):
        service.login(storage, email="alice@example.com", password="wrong", now=NOW)

    user = storage.get_user_by_email("alice@example.com")
    assert user.locked_until is not None


def test_locked_account_rejects_even_correct_password(storage):
    signup_alice(storage)
    for _ in range(service.MAX_FAILED_LOGIN_ATTEMPTS):
        with pytest.raises(service.LoginError):
            service.login(storage, email="alice@example.com", password="wrong", now=NOW)

    with pytest.raises(service.AccountLocked):
        service.login(storage, email="alice@example.com", password="hunter22", now=NOW)


def test_lockout_expires_after_duration(storage):
    signup_alice(storage)
    for _ in range(service.MAX_FAILED_LOGIN_ATTEMPTS):
        with pytest.raises(service.LoginError):
            service.login(storage, email="alice@example.com", password="wrong", now=NOW)

    later = NOW + service.LOCKOUT_DURATION + timedelta(seconds=1)
    access, refresh = service.login(
        storage, email="alice@example.com", password="hunter22", now=later
    )
    assert access and refresh


# -- refresh ---------------------------------------------------------------


def test_refresh_issues_new_token_pair(storage):
    signup_alice(storage)
    _, refresh_token = service.login(
        storage, email="alice@example.com", password="hunter22", now=NOW
    )
    access2, refresh2 = service.refresh(storage, refresh_token=refresh_token, now=NOW)
    assert access2 and refresh2


def test_refresh_rejects_garbage_token(storage):
    with pytest.raises(service.LoginError):
        service.refresh(storage, refresh_token="not-a-jwt", now=NOW)


def test_refresh_rejects_access_token_used_as_refresh(storage):
    from app.auth.security import create_access_token

    user = signup_alice(storage)
    access = create_access_token(user.id, now=NOW)
    with pytest.raises(service.LoginError):
        service.refresh(storage, refresh_token=access, now=NOW)
