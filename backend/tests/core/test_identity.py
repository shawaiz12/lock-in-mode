"""ID token verification, tested with our own RSA keys (no network).

We play "Google/Apple": generate a key pair, sign tokens with the private key,
and hand the verifier the public key, exactly as the real JWKS would.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.algorithms import RSAAlgorithm

from lock_in_mode_api.core import identity
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.identity import (
    APPLE_ISSUERS,
    GOOGLE_ISSUERS,
    IdTokenVerifier,
    InvalidIdTokenError,
    ProviderNotConfiguredError,
    hash_nonce,
)

CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-key-1"

_provider_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _public_jwk(private_key: rsa.RSAPrivateKey) -> jwt.PyJWK:
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return jwt.PyJWK({**jwk, "kid": KID, "alg": "RS256", "use": "sig"})


def _resolve(_token: str) -> jwt.PyJWK:
    """Stands in for PyJWKClient: always returns the provider's public key."""
    return _public_jwk(_provider_key)


def _verifier(issuers: tuple[str, ...] = GOOGLE_ISSUERS) -> IdTokenVerifier:
    return IdTokenVerifier(issuers=issuers, audiences=[CLIENT_ID], resolve_signing_key=_resolve)


def _id_token(
    *,
    key: rsa.RSAPrivateKey = _provider_key,
    drop: tuple[str, ...] = (),
    **overrides: Any,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-user-123",
        "iat": now,
        "exp": now + timedelta(hours=1),
        **overrides,
    }
    for name in drop:
        claims.pop(name)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


# --- the happy path ----------------------------------------------------------


def test_valid_token_returns_the_provider_sub() -> None:
    assert _verifier().verify(_id_token()).sub == "google-user-123"


@pytest.mark.parametrize("issuer", GOOGLE_ISSUERS)
def test_both_google_issuer_spellings_are_accepted(issuer: str) -> None:
    assert _verifier().verify(_id_token(iss=issuer)).sub == "google-user-123"


def test_token_for_one_of_several_client_ids_is_accepted() -> None:
    verifier = IdTokenVerifier(
        issuers=GOOGLE_ISSUERS,
        audiences=["android-client", CLIENT_ID],
        resolve_signing_key=_resolve,
    )
    assert verifier.verify(_id_token()).sub == "google-user-123"


def test_small_clock_difference_is_tolerated() -> None:
    expired_30s_ago = datetime.now(UTC) - timedelta(seconds=30)
    assert _verifier().verify(_id_token(exp=expired_30s_ago)).sub == "google-user-123"


# --- forged or misused tokens ------------------------------------------------


def test_token_for_another_app_is_rejected() -> None:
    # A real Google token, but issued to someone else's app: the classic mistake.
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(aud="someone-elses-app"))


def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(iss="https://evil.example.com"))


def test_expired_token_is_rejected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(exp=datetime.now(UTC) - timedelta(minutes=5)))


def test_token_signed_with_another_key_is_rejected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(key=_attacker_key))


def test_hs256_token_signed_with_the_public_key_is_rejected() -> None:
    # Algorithm confusion: the attacker uses the (public!) key as an HMAC secret.
    # PyJWT refuses to create such a token, so we build it by hand.
    public_pem = _provider_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    now = int(datetime.now(UTC).timestamp())
    header = {"alg": "HS256", "typ": "JWT", "kid": KID}
    claims = {"iss": GOOGLE_ISSUERS[0], "aud": CLIENT_ID, "sub": "x", "iat": now, "exp": now + 3600}
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    forged = f"{signing_input}.{_b64(signature)}"

    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(forged)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.mark.parametrize("claim", ["sub", "aud", "iss", "exp", "iat"])
def test_missing_required_claim_is_rejected(claim: str) -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(drop=(claim,)))


def test_empty_sub_is_rejected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify(_id_token(sub=""))


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier().verify("not-a-jwt")


def test_key_download_failure_is_an_invalid_token_not_a_crash() -> None:
    def _unreachable(_token: str) -> jwt.PyJWK:
        raise jwt.PyJWKClientError("Fail to fetch data from the url")

    verifier = IdTokenVerifier(
        issuers=GOOGLE_ISSUERS, audiences=[CLIENT_ID], resolve_signing_key=_unreachable
    )
    with pytest.raises(InvalidIdTokenError):
        verifier.verify(_id_token())


# --- Apple's nonce -----------------------------------------------------------


def _apple_token(**overrides: Any) -> str:
    return _id_token(iss=APPLE_ISSUERS[0], **overrides)


def test_apple_token_with_matching_nonce_is_accepted() -> None:
    token = _apple_token(nonce=hash_nonce("raw-nonce-from-app"))
    verified = _verifier(APPLE_ISSUERS).verify(token, raw_nonce="raw-nonce-from-app")
    assert verified.sub == "google-user-123"


def test_wrong_nonce_is_rejected() -> None:
    token = _apple_token(nonce=hash_nonce("raw-nonce-from-app"))
    with pytest.raises(InvalidIdTokenError):
        _verifier(APPLE_ISSUERS).verify(token, raw_nonce="some-other-nonce")


def test_missing_nonce_claim_is_rejected_when_a_nonce_is_expected() -> None:
    with pytest.raises(InvalidIdTokenError):
        _verifier(APPLE_ISSUERS).verify(_apple_token(), raw_nonce="raw-nonce-from-app")


# --- configuration -----------------------------------------------------------


@pytest.fixture
def _fresh_verifier_cache() -> Iterator[None]:
    identity.get_google_verifier.cache_clear()
    identity.get_apple_verifier.cache_clear()
    yield
    identity.get_google_verifier.cache_clear()
    identity.get_apple_verifier.cache_clear()


@pytest.mark.usefixtures("_fresh_verifier_cache")
def test_providers_are_off_until_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_ids", [])
    monkeypatch.setattr(settings, "apple_bundle_id", None)
    with pytest.raises(ProviderNotConfiguredError):
        identity.get_google_verifier()
    with pytest.raises(ProviderNotConfiguredError):
        identity.get_apple_verifier()


@pytest.mark.usefixtures("_fresh_verifier_cache")
def test_configured_provider_builds_a_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    # Building one makes no network call: keys are only fetched on first verify.
    monkeypatch.setattr(settings, "google_client_ids", [CLIENT_ID])
    assert isinstance(identity.get_google_verifier(), IdTokenVerifier)


def test_verifier_requires_an_audience() -> None:
    with pytest.raises(ValueError, match="audience"):
        IdTokenVerifier(issuers=GOOGLE_ISSUERS, audiences=[], resolve_signing_key=_resolve)
