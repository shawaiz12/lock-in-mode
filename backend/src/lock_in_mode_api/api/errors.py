"""One error shape for the whole API: RFC 9457 Problem Details (ADR 0007).

Every error response looks like this, with `Content-Type: application/problem+json`:

    {
      "type": "https://github.com/.../docs/errors.md#provider_account_in_use",
      "title": "Account already in use",
      "status": 409,
      "detail": "This Google account already belongs to another user",
      "code": "provider_account_in_use"
    }

Clients branch on `code`. `title` and `detail` are for humans and may change.
Every code is listed in docs/errors.md (a test keeps the two in sync).
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

ERROR_DOCS_URL = "https://github.com/shawaiz12/lock-in-mode/blob/main/docs/errors.md"
PROBLEM_JSON = "application/problem+json"
_BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


class ApiError(Exception):
    """Base class. Routes and dependencies raise a subclass; the handler renders it."""

    status_code: ClassVar[int]
    code: ClassVar[str]
    title: ClassVar[str]
    headers: ClassVar[Mapping[str, str]] = {}

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


# --- 401: who are you? ----------------------------------------------------------------


class NotAuthenticated(ApiError):
    status_code = 401
    code = "not_authenticated"
    title = "Not authenticated"
    headers = _BEARER_CHALLENGE


class InvalidAccessToken(ApiError):
    status_code = 401
    code = "invalid_access_token"
    title = "Invalid or expired access token"
    headers = _BEARER_CHALLENGE


class InvalidRefreshToken(ApiError):
    status_code = 401
    code = "invalid_refresh_token"
    title = "Invalid or expired refresh token"
    headers = _BEARER_CHALLENGE


class InvalidIdToken(ApiError):
    status_code = 401
    code = "invalid_id_token"
    title = "Invalid ID token"
    headers = _BEARER_CHALLENGE


# --- 404 / 405 / 422: the request itself is wrong (raised by FastAPI, not by us) -------


class NotFound(ApiError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class MethodNotAllowed(ApiError):
    status_code = 405
    code = "method_not_allowed"
    title = "Method not allowed"


class ValidationFailed(ApiError):
    status_code = 422
    code = "validation_failed"
    title = "Request validation failed"


# --- 409: conflicts with existing data ---------------------------------------------------


class ProviderAccountInUse(ApiError):
    """The app should warn that guest progress won't come along (ADR 0006)."""

    status_code = 409
    code = "provider_account_in_use"
    title = "Account already in use"


class ProviderAlreadyLinked(ApiError):
    status_code = 409
    code = "provider_already_linked"
    title = "A different account is already linked"


# --- 5xx: our side --------------------------------------------------------------------


class InternalError(ApiError):
    status_code = 500
    code = "internal_error"
    title = "Internal server error"


class ProviderUnavailable(ApiError):
    status_code = 503
    code = "provider_unavailable"
    title = "Sign-in provider unavailable"


class DatabaseUnavailable(ApiError):
    status_code = 503
    code = "database_unavailable"
    title = "Database unavailable"


# Any other HTTP error FastAPI/Starlette raises (rare) gets this generic code.
GENERIC_HTTP_ERROR_CODE = "http_error"

_BY_STATUS: dict[int, type[ApiError]] = {404: NotFound, 405: MethodNotAllowed}


def all_error_codes() -> set[str]:
    """Every code the API can return. Used by the docs test."""
    codes = {GENERIC_HTTP_ERROR_CODE}
    pending = list(ApiError.__subclasses__())
    while pending:
        cls = pending.pop()
        codes.add(cls.code)
        pending.extend(cls.__subclasses__())
    return codes


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{ERROR_DOCS_URL}#{code}",
        "title": title,
        "status": status,
        "code": code,
    }
    if detail and detail != title:
        body["detail"] = detail
    body.update(extra or {})
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


# --- handlers -------------------------------------------------------------------------


async def _api_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return problem_response(
        status=exc.status_code,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        headers=exc.headers,
    )


async def _http_exception(_request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's own errors: unknown route (404), wrong method (405), ..."""
    assert isinstance(exc, StarletteHTTPException)
    known = _BY_STATUS.get(exc.status_code)
    return problem_response(
        status=exc.status_code,
        code=known.code if known else GENERIC_HTTP_ERROR_CODE,
        title=known.title if known else HTTPStatus(exc.status_code).phrase,
        detail=exc.detail if isinstance(exc.detail, str) else None,
        headers=exc.headers,  # keeps e.g. the `Allow` header on 405
    )


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {
            "location": str(error["loc"][0]),  # body, query, path, header
            "field": ".".join(str(part) for part in error["loc"][1:]),
            "code": error["type"],  # e.g. missing, string_too_short, json_invalid
            "message": error["msg"],
            # Deliberately NOT echoing error["input"]: it can hold tokens or nonces.
        }
        for error in exc.errors()
    ]
    count = len(errors)
    return problem_response(
        status=ValidationFailed.status_code,
        code=ValidationFailed.code,
        title=ValidationFailed.title,
        detail=f"{count} invalid field{'s' if count != 1 else ''}",
        extra={"errors": errors},
    )


async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    # Never send the exception text to the client: it can contain internals.
    # Starlette re-raises after this, so the full traceback is still logged.
    return problem_response(
        status=InternalError.status_code,
        code=InternalError.code,
        title=InternalError.title,
    )


def add_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
