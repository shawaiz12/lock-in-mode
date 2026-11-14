"""Verify Google and Apple ID tokens (ADR 0005).

The mobile app signs the user in with Google or Apple and gets back an ID token:
a JWT that the provider signed with its private key. We check that token with the
provider's *public* keys, published as a JWKS ("JSON Web Key Set") at a fixed URL,
and then trust the `sub` claim inside it: the provider's permanent id for that user.

This module only answers "is this token genuine, and whose is it?".
Finding or creating the user is the auth service's job.
"""

import hashlib
import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from functools import cache

import jwt

from lock_in_mode_api.core.config import settings

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Google documents both spellings as valid issuers.
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUERS = ("https://appleid.apple.com",)

# Both providers sign with RS256. Accepting only this stops "algorithm confusion"
# attacks (e.g. a token that claims HS256 and is "signed" with our public key).
ALGORITHMS = ["RS256"]

# Tolerate small clock differences between Google/Apple's servers and ours.
CLOCK_LEEWAY = timedelta(seconds=60)

# Given a token, return the public key that should have signed it (picked by the
# token's "kid" header). In production this is PyJWKClient; tests pass their own.
type SigningKeyResolver = Callable[[str], jwt.PyJWK]


class InvalidIdTokenError(Exception):
    """The ID token is malformed, forged, expired, or meant for another app."""


class ProviderNotConfiguredError(Exception):
    """Sign-in with this provider is switched off (no client id configured)."""


@dataclass(frozen=True)
class VerifiedIdentity:
    """Who the provider says this is. `sub` never changes for a given account."""

    sub: str


def hash_nonce(raw_nonce: str) -> str:
    """SHA-256 hex digest, the form the app puts into the Apple sign-in request."""
    return hashlib.sha256(raw_nonce.encode()).hexdigest()


class IdTokenVerifier:
    def __init__(
        self,
        *,
        issuers: Sequence[str],
        audiences: Sequence[str],
        resolve_signing_key: SigningKeyResolver,
    ) -> None:
        if not audiences:
            raise ValueError("at least one audience (client id) is required")
        self._issuers = tuple(issuers)
        self._audiences = list(audiences)
        self._resolve_signing_key = resolve_signing_key

    def verify(self, token: str, *, raw_nonce: str | None = None) -> VerifiedIdentity:
        """Check signature, issuer, audience and expiry; optionally the nonce.

        Blocking: the first call (and every key rotation) downloads the JWKS.
        Call it from async code with `asyncio.to_thread`.
        """
        try:
            signing_key = self._resolve_signing_key(token)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=ALGORITHMS,
                audience=self._audiences,  # must be OUR app, not someone else's
                issuer=self._issuers,
                leeway=CLOCK_LEEWAY,
                options={"require": ["sub", "iss", "aud", "exp", "iat"]},
            )
        except jwt.PyJWTError as exc:  # includes PyJWKClientError (key download failed)
            raise InvalidIdTokenError(str(exc)) from exc

        if raw_nonce is not None:
            # The app sent sha256(nonce) to the provider and the raw nonce to us.
            # A stolen token can't be replayed without also knowing the raw nonce.
            token_nonce = claims.get("nonce")
            if not isinstance(token_nonce, str) or not hmac.compare_digest(
                token_nonce, hash_nonce(raw_nonce)
            ):
                raise InvalidIdTokenError("nonce mismatch")

        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise InvalidIdTokenError("invalid sub claim")
        return VerifiedIdentity(sub=sub)


def _jwks_resolver(url: str) -> SigningKeyResolver:
    # PyJWKClient caches the key set (5 min) and refetches when it sees an unknown
    # "kid", so key rotation by Google/Apple is handled without a restart.
    client = jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)
    return client.get_signing_key_from_jwt


@cache  # one verifier (and one key cache) per process
def get_google_verifier() -> IdTokenVerifier:
    if not settings.google_client_ids:
        raise ProviderNotConfiguredError("google")
    return IdTokenVerifier(
        issuers=GOOGLE_ISSUERS,
        audiences=settings.google_client_ids,
        resolve_signing_key=_jwks_resolver(GOOGLE_JWKS_URL),
    )


@cache
def get_apple_verifier() -> IdTokenVerifier:
    if not settings.apple_bundle_id:
        raise ProviderNotConfiguredError("apple")
    return IdTokenVerifier(
        issuers=APPLE_ISSUERS,
        audiences=[settings.apple_bundle_id],
        resolve_signing_key=_jwks_resolver(APPLE_JWKS_URL),
    )
