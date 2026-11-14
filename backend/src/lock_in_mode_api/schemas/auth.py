from typing import Literal

from pydantic import BaseModel, Field


class TokenPair(BaseModel):
    """What every successful sign-in or refresh returns."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=200)


class IdTokenRequest(BaseModel):
    """Google sign-in: just the ID token the app got from Google."""

    # Real ID tokens are ~1-2 KB; the cap stops someone posting megabytes at us.
    id_token: str = Field(min_length=1, max_length=4096)


class AppleIdTokenRequest(IdTokenRequest):
    nonce: str = Field(
        min_length=1,
        max_length=200,
        description="The raw nonce. The app sent its SHA-256 hex digest to Apple.",
    )
