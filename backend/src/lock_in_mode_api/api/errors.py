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
    default_headers: ClassVar[Mapping[str, str]] = {}

    def __init__(
        self, detail: str | None = None, *, headers: Mapping[str, str] | None = None
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        # Per-error headers on top of the class defaults (e.g. Retry-After on a 429).
        self.headers = {**self.default_headers, **(headers or {})}


# --- 401: who are you? ----------------------------------------------------------------


class NotAuthenticated(ApiError):
    status_code = 401
    code = "not_authenticated"
    title = "Not authenticated"
    default_headers = _BEARER_CHALLENGE


class InvalidAccessToken(ApiError):
    status_code = 401
    code = "invalid_access_token"
    title = "Invalid or expired access token"
    default_headers = _BEARER_CHALLENGE


class InvalidRefreshToken(ApiError):
    status_code = 401
    code = "invalid_refresh_token"
    title = "Invalid or expired refresh token"
    default_headers = _BEARER_CHALLENGE


class InvalidIdToken(ApiError):
    status_code = 401
    code = "invalid_id_token"
    title = "Invalid ID token"
    default_headers = _BEARER_CHALLENGE


# --- 404 / 405 / 422: the request itself is wrong (raised by FastAPI, not by us) -------


class NotFound(ApiError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class ProfileNotFound(ApiError):
    """The user hasn't onboarded yet: the app shows onboarding (ADR 0012)."""

    status_code = 404
    code = "profile_not_found"
    title = "Profile not found"


class PlanNotFound(ApiError):
    """No plan yet: after onboarding and the safety screen, call POST /plans (ADR 0017)."""

    status_code = 404
    code = "plan_not_found"
    title = "No plan yet"


class BlockComplete(ApiError):
    """Every workout of the block is done or skipped: show "Block complete!" (ADR 0017)."""

    status_code = 404
    code = "block_complete"
    title = "Block complete"


class SessionNotFound(ApiError):
    """No open session (GET /sessions/current), or no such session for this user."""

    status_code = 404
    code = "session_not_found"
    title = "Session not found"


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


class SafetyScreenRequired(ApiError):
    """The safety screen comes before any plan (ADR 0012)."""

    status_code = 409
    code = "safety_screen_required"
    title = "Safety screen required"


class PlanInProgress(ApiError):
    """A new block starts only when every workout of the current one is done or skipped."""

    status_code = 409
    code = "plan_in_progress"
    title = "Current block isn't finished"


class NotNextWorkout(ApiError):
    """Only the next workout in the queue can be skipped (ADR 0017)."""

    status_code = 409
    code = "not_next_workout"
    title = "Not the next workout"


class SessionFinished(ApiError):
    """The session is finished: sets can't change and it can't finish twice (ADR 0018)."""

    status_code = 409
    code = "session_finished"
    title = "Session already finished"


class SessionInProgress(ApiError):
    """A started workout can't be skipped: finish it instead, half counts (ADR 0018)."""

    status_code = 409
    code = "session_in_progress"
    title = "Workout already started"


# --- 429: slow down ---------------------------------------------------------------------


class RateLimited(ApiError):
    """Too many requests from this IP. Always sent with Retry-After (ADR 0008)."""

    status_code = 429
    code = "rate_limited"
    title = "Too many requests"


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
