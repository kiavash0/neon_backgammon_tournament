from datetime import UTC, datetime, timedelta

import pytest

from app.auth.security import (
    InvalidToken,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True
    assert verify_password("wrong password", h) is False


def test_hash_is_not_plaintext():
    assert hash_password("secret") != "secret"


def test_access_and_refresh_tokens_decode_with_correct_type():
    access = create_access_token("user-1")
    refresh = create_refresh_token("user-1")

    assert decode_token(access, "access")["sub"] == "user-1"
    assert decode_token(refresh, "refresh")["sub"] == "user-1"


def test_decode_rejects_wrong_token_type():
    access = create_access_token("user-1")
    with pytest.raises(InvalidToken):
        decode_token(access, "refresh")


def test_decode_rejects_garbage_token():
    with pytest.raises(InvalidToken):
        decode_token("not-a-jwt", "access")


def test_decode_rejects_expired_token():
    past = datetime.now(UTC) - timedelta(hours=1)
    token = create_access_token("user-1", now=past)
    with pytest.raises(InvalidToken):
        decode_token(token, "access")
