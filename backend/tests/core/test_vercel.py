"""Running the API on Vercel, with Supabase's transaction pooler (ADR 0031).

The pooler itself is tested for real in CI (scripts/pooler_check.py: many users at once
through PgBouncer in transaction mode). These tests pin down the settings that make it
work, and the files Vercel and the deploy job read.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from lock_in_mode_api.core.config import Settings, settings
from lock_in_mode_api.main import app

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

SHOW_THE_ENGINE = """
from lock_in_mode_api.core.db import engine
print(type(engine.pool).__name__, engine.pool._pre_ping)
"""

CONNECT_WITH_THE_APP_ENGINE = """
import asyncio
from sqlalchemy import text
from lock_in_mode_api.core.db import engine

async def main() -> None:
    for _ in range(3):  # several connections, several statements
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            await connection.execute(text("SELECT count(*) FROM exercises"))
    await engine.dispose()

asyncio.run(main())
"""


def _child(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


# --- the transaction pooler setting ----------------------------------------------------


def test_behind_a_transaction_pooler_no_prepared_statement_is_cached() -> None:
    pooled = Settings(postgres_transaction_pooler=True)

    args = pooled.database_connect_args
    assert args["statement_cache_size"] == 0  # asyncpg's cache
    assert pooled.database_url.query == {"prepared_statement_cache_size": "0"}  # SQLAlchemy's
    # The statements SQLAlchemy still prepares get a name no other client can be using.
    names = {args["prepared_statement_name_func"]() for _ in range(50)}
    assert len(names) == 50
    assert all(name.startswith("__asyncpg_") for name in names)


def test_without_a_transaction_pooler_nothing_changes() -> None:
    assert settings.postgres_transaction_pooler is False
    assert settings.database_connect_args == {"timeout": 5, "ssl": "prefer"}
    assert settings.database_url.query == {}


@pytest.mark.parametrize(
    ("pooler", "expected"),
    [("true", "NullPool False"), ("false", "AsyncAdaptedQueuePool True")],
    ids=["pooler-no-own-pool", "direct-own-pool"],
)
def test_the_app_keeps_its_own_pool_only_without_a_transaction_pooler(
    pooler: str, expected: str
) -> None:
    result = _child(["-c", SHOW_THE_ENGINE], POSTGRES_TRANSACTION_POOLER=pooler)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "args",
    [["-c", CONNECT_WITH_THE_APP_ENGINE], ["-m", "alembic", "current"]],
    ids=["app-engine", "migrations"],
)
def test_the_pooler_options_are_real_driver_options(args: list[str]) -> None:
    # A misspelt option would only fail on the first real connection, on Vercel.
    result = _child(args, POSTGRES_TRANSACTION_POOLER="true")

    assert result.returncode == 0, result.stderr


# --- what Vercel reads --------------------------------------------------------------------


def test_vercel_serves_the_real_app() -> None:
    entrypoint = tomllib.loads((BACKEND / "pyproject.toml").read_text())["tool"]["vercel"][
        "entrypoint"
    ]
    module_name, variable = entrypoint.split(":")
    spec = importlib.util.spec_from_file_location("vercel_entry", BACKEND / f"{module_name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert getattr(module, variable) is app
    assert str(BACKEND / "src") in sys.path


def test_vercel_runs_in_mumbai_and_only_ci_deploys() -> None:
    config = json.loads((BACKEND / "vercel.json").read_text())

    # Same region as Supabase and Upstash: every query is a short trip.
    assert config["regions"] == ["bom1"]
    # No deploy per push or per pull request: a preview would run unreviewed code
    # against the real database. Only the CI deploy job deploys, after the tests.
    assert config["git"]["deploymentEnabled"] is False


def test_the_upload_leaves_out_secrets_and_everything_but_the_api() -> None:
    ignored = (REPO / ".vercelignore").read_text().splitlines()

    for pattern in (".env", ".env.*", "/mobile", "/backend/tests"):
        assert pattern in ignored


# --- the deploy job and the hourly cleanup ----------------------------------------------


def _workflow(name: str) -> dict:  # type: ignore[type-arg]
    return yaml.safe_load((REPO / ".github" / "workflows" / name).read_text())  # type: ignore[no-any-return]


def test_the_deploy_migrates_first_then_deploys_then_waits_for_the_commit() -> None:
    steps = [step.get("run", "") for step in _workflow("ci.yml")["jobs"]["deploy"]["steps"]]
    migrate = next(i for i, run in enumerate(steps) if "alembic upgrade head" in run)
    deploy = next(i for i, run in enumerate(steps) if "vercel@" in run)
    wait = next(i for i, run in enumerate(steps) if "/health/live" in run)

    assert migrate < deploy < wait
    assert "--prod" in steps[deploy]
    assert 'APP_VERSION="$GITHUB_SHA"' in steps[deploy]


def test_the_cleanup_runs_every_hour_with_the_same_code() -> None:
    workflow = _workflow("cleanup.yml")
    # PyYAML reads the key "on" as True (YAML 1.1).
    schedule = workflow[True]["schedule"][0]["cron"]
    run = workflow["jobs"]["cleanup"]["steps"][-1]["run"]

    assert schedule.split()[1:] == ["*", "*", "*", "*"]  # every hour, every day
    assert "python -m lock_in_mode_api.cleanup" in run
