"""Token helpers (ADR 0005).

Access tokens: short-lived JWTs signed with HS256, checked on every request
without a database lookup.
Refresh tokens: long random strings; only their SHA-256 hash is stored.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from lock_in_mode_api.core.config import settings

ALGORITHM = "HS256"
ISSUER = "lock-in-mode-api"
ACCESS_TOKEN_TYPE = "access"


class InvalidAccessTokenError(Exception):
    """The access token is missing, malformed, expired or not ours."""


def create_access_token(user_id: uuid.UUID, *, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iss": ISSUER,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_ttl_minutes),
        "type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id inside a valid access token, or raise InvalidAccessTokenError."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            # Only accept the one algorithm we sign with. Never trust the token's
            # own "alg" header: that is how "alg: none" attacks work.
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["sub", "iss", "iat", "exp"]},
        )
        if payload.get("type") != ACCESS_TOKEN_TYPE:
            raise InvalidAccessTokenError("not an access token")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:  # ValueError: "sub" isn't a UUID
        raise InvalidAccessTokenError(str(exc)) from exc


def generate_refresh_token() -> str:
    """A new refresh token: 32 random bytes (256 bits), URL-safe text."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest. A fast hash is enough: the token is random, not a password."""
    return hashlib.sha256(token.encode()).hexdigest()
