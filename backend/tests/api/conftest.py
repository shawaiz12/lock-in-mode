"""Fixtures for API tests: a fake Google and a fake Apple.

Each fixture swaps the real verifier (which would download Google's/Apple's public
keys) for one that trusts a key pair generated here, and returns a function that
signs ID tokens with the matching private key. The API then runs its real
verification code on real signed tokens, with no network.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from lock_in_mode_api.api.deps import apple_verifier, google_verifier
from lock_in_mode_api.core.identity import (
    APPLE_ISSUERS,
    GOOGLE_ISSUERS,
    IdTokenVerifier,
    hash_nonce,
)
from lock_in_mode_api.main import app

GOOGLE_CLIENT_ID = "test-app.apps.googleusercontent.com"
APPLE_BUNDLE_ID = "com.test.lockinmode"
APPLE_NONCE = "raw-nonce-from-the-app"

# Generating RSA keys takes a moment, so do it once for the whole module.
_provider_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_jwk = jwt.PyJWK(
    {
        **RSAAlgorithm.to_jwk(_provider_key.public_key(), as_dict=True),
        "kid": "test",
        "alg": "RS256",
    }
)

type MakeIdToken = Callable[..., str]


def _sign(issuer: str, audience: str, sub: str, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(hours=1),
        **claims,
    }
    return jwt.encode(payload, _provider_key, algorithm="RS256", headers={"kid": "test"})


def _local_verifier(issuers: tuple[str, ...], audience: str) -> IdTokenVerifier:
    return IdTokenVerifier(
        issuers=issuers, audiences=[audience], resolve_signing_key=lambda _token: _public_jwk
    )


@pytest.fixture
def google_id_token() -> MakeIdToken:
    """`google_id_token("sub")` → a Google ID token for that account."""
    app.dependency_overrides[google_verifier] = lambda: _local_verifier(
        GOOGLE_ISSUERS, GOOGLE_CLIENT_ID
    )

    def make(sub: str = "google-user-1") -> str:
        return _sign(GOOGLE_ISSUERS[0], GOOGLE_CLIENT_ID, sub)

    return make


@pytest.fixture
def apple_id_token() -> MakeIdToken:
    """`apple_id_token("sub")` → an Apple ID token carrying hash(APPLE_NONCE)."""
    app.dependency_overrides[apple_verifier] = lambda: _local_verifier(
        APPLE_ISSUERS, APPLE_BUNDLE_ID
    )

    def make(sub: str = "apple-user-1") -> str:
        return _sign(APPLE_ISSUERS[0], APPLE_BUNDLE_ID, sub, nonce=hash_nonce(APPLE_NONCE))

    return make
