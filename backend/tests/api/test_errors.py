"""Every error has the same RFC 9457 shape (ADR 0007)."""

import re
from collections.abc import AsyncIterator
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from lock_in_mode_api.api.errors import ERROR_DOCS_URL, all_error_codes
from lock_in_mode_api.core.db import get_db_session
from lock_in_mode_api.main import app

ERRORS_DOC = Path(__file__).resolve().parents[3] / "docs" / "errors.md"


async def test_our_errors_are_problem_documents(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")  # no token

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {
        "type": f"{ERROR_DOCS_URL}#not_authenticated",
        "title": "Not authenticated",
        "status": 401,
        "code": "not_authenticated",
        # no "detail": it would only repeat the title
    }


async def test_unknown_route_is_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


async def test_wrong_method_keeps_the_allow_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/guest")  # it's POST-only

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert response.headers["Allow"] == "POST"


async def test_validation_errors_list_fields_without_echoing_input(client: AsyncClient) -> None:
    secret = "s" * 201  # one character over the refresh token limit
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": secret})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["detail"] == "1 invalid field"
    assert body["errors"] == [
        {
            "location": "body",
            "field": "refresh_token",
            "code": "string_too_long",
            "message": "String should have at most 200 characters",
        }
    ]
    assert secret not in response.text  # tokens must never be reflected back


async def test_malformed_json_is_a_validation_error(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/refresh",
        content=b'{"refresh_token": ',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "json_invalid"


async def test_unexpected_errors_are_500_without_internals() -> None:
    class _BrokenSession:
        async def execute(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("password=hunter2 in a stack trace")

    async def _broken() -> AsyncIterator[_BrokenSession]:
        yield _BrokenSession()

    app.dependency_overrides[get_db_session] = _broken
    # raise_app_exceptions=False: behave like a real server and return the response,
    # instead of re-raising the error into the test (see test_health.py for that side).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "internal_error"
    assert "hunter2" not in response.text


def test_every_error_code_is_documented() -> None:
    documented = set(re.findall(r"^## (\w+)$", ERRORS_DOC.read_text(), flags=re.MULTILINE))

    assert documented == all_error_codes()
