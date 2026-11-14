"""Error response shapes, for the OpenAPI docs (ADR 0007). See api/errors.py."""

from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 9457 problem details. Clients branch on `code`."""

    type: str = Field(description="Link to this error's entry in docs/errors.md.")
    title: str
    status: int
    code: str = Field(examples=["provider_account_in_use"])
    detail: str | None = None


class FieldError(BaseModel):
    location: str = Field(examples=["body"])
    field: str = Field(examples=["nonce"])
    code: str = Field(examples=["missing"])
    message: str = Field(examples=["Field required"])


class ValidationProblem(Problem):
    errors: list[FieldError]
