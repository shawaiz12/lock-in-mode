""" "Download my data" (ADR 0027): one JSON file with every row stored about the person, in
every user table but `refresh_tokens`; no security internals; exercises by name; only
their own data; 3 per account per clock hour.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.api import rate_limit
from lock_in_mode_api.models import Exercise, RefreshToken, User
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.services import export
from tests.api.test_account_deletion import (
    ALL_NO,
    GYM,
    _auth,
    _full_user,
    _google,
    _guest,
    _train,
    _user_tables,
)

type MakeIdToken = Callable[..., str]
type Json = dict[str, Any]

ME = "/api/v1/me"
EXPORT = "/api/v1/me/export"
HOUR_START = 1_800_000_000 - 1_800_000_000 % 3600  # a clock hour boundary


@pytest.fixture
async def library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_clock(monkeypatch, HOUR_START + 20 * 60)  # 20 minutes into the hour


def _set_clock(monkeypatch: pytest.MonkeyPatch, now: float) -> None:
    monkeypatch.setattr(rate_limit, "clock", lambda: now)


# Where each user table's rows are in the file.
ROWS_IN_FILE: dict[str, Callable[[Json], int]] = {
    "users": lambda f: 1,
    "profiles": lambda f: 0 if f["profile"] is None else 1,
    "plans": lambda f: len(f["plans"]),
    "planned_workouts": lambda f: sum(len(p["workouts"]) for p in f["plans"]),
    "planned_exercises": lambda f: sum(
        len(w["exercises"]) for p in f["plans"] for w in p["workouts"]
    ),
    "workout_sessions": lambda f: len(f["workout_sessions"]),
    "set_logs": lambda f: sum(len(s["sets"]) for s in f["workout_sessions"]),
    "movement_rungs": lambda f: len(f["strength_test"]),
    "exercise_targets": lambda f: len(f["exercise_progress"]),
    "interval_steps": lambda f: 0 if f["interval_progress"] is None else 1,
    "swapped_out_exercises": lambda f: len(f["swapped_out_exercises"]),
    "comebacks": lambda f: len(f["comebacks"]),
    "events": lambda f: len(f["usage_events"]),
    "xp_events": lambda f: len(f["xp"]),
}


def _keys(value: Any) -> set[str]:
    """Every key anywhere in the file."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _values_of(value: Any, key: str) -> list[Any]:
    if isinstance(value, dict):
        found = [value[key]] if key in value else []
        return found + [x for v in value.values() for x in _values_of(v, key)]
    if isinstance(value, list):
        return [x for v in value for x in _values_of(v, key)]
    return []


async def _export(client: AsyncClient, headers: dict[str, str]) -> Json:
    response = await client.get(EXPORT, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_every_user_table_is_exported_or_named_as_not_exported() -> None:
    """A new user table must be added to the export (and here), or to NOT_EXPORTED_TABLES."""
    assert {t.name for t in _user_tables()} == set(ROWS_IN_FILE) | export.NOT_EXPORTED_TABLES
    # Only the token hashes stay out: adding a table here needs a reason in an ADR.
    assert {"refresh_tokens"} == export.NOT_EXPORTED_TABLES


async def test_a_full_user_gets_every_row_they_have(
    client: AsyncClient, db_session: AsyncSession, library: None, google_id_token: MakeIdToken
) -> None:
    other = _auth(await _guest(client))  # someone else's rows must not appear
    assert (await client.put(f"{ME}/profile", json=GYM, headers=other)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=other)).is_success
    assert (await client.post("/api/v1/plans", headers=other)).status_code == 201
    await _train(client, other)
    tokens = await _guest(client)
    await _full_user(client, db_session, tokens)
    user_id = (await client.get(ME, headers=_auth(tokens))).json()["id"]

    file = await _export(client, _auth(tokens))

    for table in _user_tables():
        if table.name in export.NOT_EXPORTED_TABLES:
            continue
        mine = (
            table.c.id == user_id
            if table.name == "users"
            else table.c.user_id == user_id
            if "user_id" in table.c
            else None
        )
        if mine is None:  # nested tables: count through their parent
            continue
        in_db = await db_session.scalar(select(func.count()).select_from(table).where(mine))
        assert ROWS_IN_FILE[table.name](file) == in_db, table.name
        assert in_db, f"the test user has no {table.name} row"
    planned = await db_session.scalar(
        select(func.count())
        .select_from(_table("planned_exercises"))
        .where(
            _table("planned_exercises").c.planned_workout_id.in_(
                [w["id"] for p in file["plans"] for w in p["workouts"]]
            )
        )
    )
    assert ROWS_IN_FILE["planned_exercises"](file) == planned
    sets = await db_session.scalar(
        select(func.count())
        .select_from(_table("set_logs"))
        .where(_table("set_logs").c.session_id.in_([s["id"] for s in file["workout_sessions"]]))
    )
    assert sets
    assert ROWS_IN_FILE["set_logs"](file) == sets
    assert ROWS_IN_FILE["planned_workouts"](file) > 0
    assert (file["format"], file["version"]) == ("lock-in-mode-export", 1)
    assert file["account"]["id"] == user_id and file["account"]["signed_in_with"] == []


def _table(name: str) -> Any:
    return next(t for t in _user_tables() if t.name == name)


async def test_nothing_secret_and_exercises_by_name(
    client: AsyncClient, db_session: AsyncSession, library: None, google_id_token: MakeIdToken
) -> None:
    tokens = await _guest(client)
    await _full_user(client, db_session, tokens)
    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("sub-123")}, headers=_auth(tokens)
    )
    assert link.status_code == 200

    response = await client.get(EXPORT, headers=_auth(tokens))

    text = response.text
    file = response.json()
    assert file["account"]["signed_in_with"] == ["google"]
    assert "sub-123" not in text
    assert tokens.refresh_token not in text
    for token_hash in await db_session.scalars(select(RefreshToken.token_hash)):
        assert token_hash not in text
    assert not _keys(file) & {"google_sub", "apple_sub", "token_hash", "user_id", "exercise_id"}
    names = set(await db_session.scalars(select(Exercise.name)))
    exercises = _values_of(file, "exercise")
    assert exercises and all(name in names for name in exercises)
    assert {k: file["profile"][k] for k in GYM} == GYM  # their answers, as they gave them
    assert response.headers["content-disposition"] == (
        'attachment; filename="lock-in-mode-data.json"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(text) == file


async def test_the_numbers_are_the_ones_logged(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    tokens = await _guest(client)
    await _full_user(client, db_session, tokens)

    file = await _export(client, _auth(tokens))

    set_logs = _table("set_logs")
    rows = (
        await db_session.execute(select(set_logs.c.id, set_logs.c.reps, set_logs.c.weight_kg))
    ).all()
    by_id = {str(i): (reps, weight) for i, reps, weight in rows}
    sets = [s for w in file["workout_sessions"] for s in w["sets"]]
    assert {s["id"]: (s["reps"], s["weight_kg"]) for s in sets} == by_id
    assert all(s["exercise"] for s in sets)
    assert re.match(r"\d{4}-\d\d-\d\dT", file["exported_at"])


async def test_a_new_guest_gets_an_almost_empty_file(client: AsyncClient) -> None:
    tokens = await _guest(client)

    file = await _export(client, _auth(tokens))

    assert file["profile"] is None and file["interval_progress"] is None
    assert file["plans"] == file["workout_sessions"] == file["comebacks"] == []
    assert [e["name"] for e in file["usage_events"]] == ["signed_up"]
    assert file["account"]["is_guest"] is True


async def test_not_signed_in_is_401(client: AsyncClient) -> None:
    assert (await client.get(EXPORT)).status_code == 401


# --- 3 per account per hour ---------------------------------------------------------------


async def test_three_an_hour_per_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, google_id_token: MakeIdToken
) -> None:
    tokens = await _guest(client)
    other = await _google(client, google_id_token("g"))
    for _ in range(3):
        assert (await client.get(EXPORT, headers=_auth(tokens))).status_code == 200

    fourth = await client.get(EXPORT, headers=_auth(tokens))

    assert fourth.status_code == 429
    assert fourth.json()["code"] == "rate_limited"
    assert fourth.headers["retry-after"] == str(40 * 60)  # 20 minutes into the hour
    assert fourth.json()["detail"] == (
        "You can download your data 3 times an hour. Try again in 40 minutes."
    )
    # Someone else isn't affected, and the next hour starts again.
    assert (await client.get(EXPORT, headers=_auth(other))).status_code == 200
    _set_clock(monkeypatch, HOUR_START + 3600)
    assert (await client.get(EXPORT, headers=_auth(tokens))).status_code == 200


async def test_one_minute_left_is_singular(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_clock(monkeypatch, HOUR_START + 3600 - 30)
    tokens = await _guest(client)
    for _ in range(3):
        await client.get(EXPORT, headers=_auth(tokens))

    fourth = await client.get(EXPORT, headers=_auth(tokens))

    assert fourth.json()["detail"].endswith("Try again in 1 minute.")
    assert fourth.headers["retry-after"] == "30"


async def test_the_limit_doesnt_count_refused_requests_from_others(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _guest(client)
    for _ in range(5):
        assert (await client.get(EXPORT)).status_code == 401  # no user: nothing counted
    user = await db_session.scalar(select(User))
    assert user is not None
    for _ in range(3):
        assert (await client.get(EXPORT, headers=_auth(tokens))).status_code == 200
