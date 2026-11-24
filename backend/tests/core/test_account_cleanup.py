"""The hourly account cleanup inside the API (ADR 0024): it keeps running after a failed
run, and the app starts it (or not) from the setting."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest

import lock_in_mode_api.main as main
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.services import account


class _Stop(Exception):
    """Ends the endless loop after a few turns."""


async def test_a_failed_run_is_logged_and_the_next_run_still_happens(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runs: list[str] = []

    async def purge(session: Any) -> int:
        runs.append("run")
        if len(runs) == 1:
            raise RuntimeError("database down")
        return 3

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise _Stop

    @asynccontextmanager
    async def session_local() -> Any:
        yield object()

    monkeypatch.setattr(account, "purge_due", purge)
    monkeypatch.setattr(account, "SessionLocal", session_local)
    caplog.set_level(logging.INFO, logger=account.logger.name)

    with pytest.raises(_Stop):
        await account.run_cleanup(3600, sleep=sleep)

    assert runs == ["run", "run", "run"]  # the failure didn't stop it
    assert sleeps == [3600, 3600, 3600]
    assert "Account cleanup failed" in caplog.text
    assert "erased 3 account(s)" in caplog.text


class _Closable:
    async def dispose(self) -> None: ...

    async def aclose(self) -> None: ...


@pytest.mark.parametrize(("seconds", "started"), [(3600, True), (0, False)])
async def test_the_app_starts_the_cleanup_unless_switched_off(
    monkeypatch: pytest.MonkeyPatch, seconds: int, started: bool
) -> None:
    calls: list[float] = []
    cancelled = asyncio.Event()

    async def cleanup(interval: float) -> None:
        calls.append(interval)
        try:
            await asyncio.Event().wait()  # runs until the app stops
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main, "run_cleanup", cleanup)
    monkeypatch.setattr(settings, "account_cleanup_interval_seconds", seconds)
    # Shutdown closes the engine and Redis: give it stand-ins so other tests keep theirs.
    monkeypatch.setattr(main, "engine", _Closable())
    monkeypatch.setattr(main, "redis_client", _Closable())

    async with main.lifespan(main.app):
        await asyncio.sleep(0)  # let the task start

    assert calls == ([seconds] if started else [])
    assert cancelled.is_set() is started  # stopped cleanly on shutdown
