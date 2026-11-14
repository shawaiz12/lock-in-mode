from typing import Any

from fastapi import APIRouter

from lock_in_mode_api.api.errors import PROBLEM_JSON
from lock_in_mode_api.api.v1 import auth, me
from lock_in_mode_api.schemas.problem import Problem, ValidationProblem


def _problem_doc(model: type[Problem], description: str) -> dict[str, Any]:
    """OpenAPI entry for an error response served as application/problem+json."""
    return {
        "description": description,
        "content": {PROBLEM_JSON: {"schema": {"$ref": f"#/components/schemas/{model.__name__}"}}},
        "model": model,  # makes FastAPI add the schema to components
    }


# Documented once for every v1 endpoint (ADR 0007). Declaring 422 here also replaces
# FastAPI's built-in 422 schema, which no longer matches what we send.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: _problem_doc(ValidationProblem, "Request body or parameters are invalid"),
    "default": _problem_doc(Problem, "Any other error. Branch on `code`; see docs/errors.md"),
}

router = APIRouter(prefix="/api/v1", responses=_ERROR_RESPONSES)
router.include_router(auth.router)
router.include_router(me.router)
