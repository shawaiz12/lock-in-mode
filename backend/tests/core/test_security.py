import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.security import (
    ALGORITHM,
    ISSUER,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

SECRET = settings.jwt_secret.get_secret_value()


def _sign(payload: dict[str, object], secret: str = SECRET, algorithm: str = ALGORITHM) -> str:
    """Hand-craft a token, so tests can build ones our code would never issue."""
    return jwt.encode(payload, secret, algorithm=algorithm)


def _valid_claims(user_id: uuid.UUID) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "sub": str(user_id),
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "access",
    }


# --- access tokens ------------------------------------------------------------


def test_access_token_round_trip_returns_user_id() -> None:
    user_id = uuid.uuid4()

    assert decode_access_token(create_access_token(user_id)) == user_id


def test_access_token_expires_after_configured_ttl() -> None:
    issued_long_ago = datetime.now(UTC) - timedelta(minutes=settings.access_token_ttl_minutes + 1)
    token = create_access_token(uuid.uuid4(), now=issued_long_ago)

    with pytest.raises(InvalidAccessTokenError, match="expired"):
        decode_access_token(token)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = _sign(_valid_claims(uuid.uuid4()), secret="attacker-secret-" + "x" * 32)

    with pytest.raises(InvalidAccessTokenError, match="Signature"):
        decode_access_token(token)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(tampered)


def test_unsigned_alg_none_token_is_rejected() -> None:
    """Classic JWT attack: claim "alg: none" and send no signature at all."""
    token = jwt.encode(_valid_claims(uuid.uuid4()), key="", algorithm="none")

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


def test_token_from_another_issuer_is_rejected() -> None:
    claims = _valid_claims(uuid.uuid4()) | {"iss": "someone-else"}

    with pytest.raises(InvalidAccessTokenError, match="issuer"):
        decode_access_token(_sign(claims))


def test_token_that_is_not_an_access_token_is_rejected() -> None:
    claims = _valid_claims(uuid.uuid4()) | {"type": "refresh"}

    with pytest.raises(InvalidAccessTokenError, match="not an access token"):
        decode_access_token(_sign(claims))


@pytest.mark.parametrize("missing", ["sub", "exp", "iat", "iss"])
def test_token_missing_a_required_claim_is_rejected(missing: str) -> None:
    claims = _valid_claims(uuid.uuid4())
    del claims[missing]

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(_sign(claims))


def test_token_whose_subject_is_not_a_uuid_is_rejected() -> None:
    claims = _valid_claims(uuid.uuid4()) | {"sub": "not-a-uuid"}

    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(_sign(claims))


# --- refresh tokens -----------------------------------------------------------


def test_refresh_tokens_are_long_and_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(1000)}

    assert len(tokens) == 1000
    assert all(len(token) >= 43 for token in tokens)  # 32 bytes -> 43 base64 chars


def test_refresh_token_hash_is_stable_and_never_the_token_itself() -> None:
    token = generate_refresh_token()

    digest = hash_refresh_token(token)

    assert digest == hash_refresh_token(token)
    assert len(digest) == 64  # fits the String(64) column
    assert token not in digest
