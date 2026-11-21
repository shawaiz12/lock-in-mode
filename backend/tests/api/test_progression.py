"""Progression through the API (ADR 0019): double progression, the feedback taps, falling
short, the early recovery week, and progress carrying into the next block. Real library.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import ExerciseTarget, MovementRung
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.plan_types import is_weighted

SESSIONS = "/api/v1/sessions"
PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
HOME: dict[str, Any] = {
    "goal": "build_muscle",
    "level": "beginner",
    "location": "home",
    "days_per_week": 3,
    "minutes_per_session": 30,
}
GYM = HOME | {"location": "gym", "level": "some_experience"}
LIBRARY = {e.slug: e for e in load_library().exercises}

type Headers = dict[str, str]
type Json = dict[str, Any]
type Log = Callable[[Json], Json | None]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _plan(client: AsyncClient, headers: Headers, answers: Json = HOME) -> Json:
    assert (await client.put("/api/v1/me/profile", json=answers, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=ALL_NO, headers=headers)).is_success
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _workout(client: AsyncClient, headers: Headers, workout_id: str) -> Json:
    return dict((await client.get(f"/api/v1/workouts/{workout_id}", headers=headers)).json())


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


def _strength(workout: Json) -> list[Json]:
    """Main-block strength rows: the ones that progress."""
    return [e for e in workout["main"] if e["reps_in_reserve"] is not None and not e["is_test"]]


def _top(e: Json) -> Json:
    return {"seconds": e["seconds"]} if e["seconds"] else {"reps": e["reps_max"]}


def _top_with(weight: float) -> Log:
    return lambda e: _top(e) | ({"weight_kg": weight} if _weighted(e) else {})


def _bottom(e: Json) -> Json:
    return {"seconds": e["seconds"]} if e["seconds"] else {"reps": e["reps_min"]}


def _weighted(e: Json) -> bool:
    return is_weighted(LIBRARY[e["exercise"]["slug"]])


async def _do(
    client: AsyncClient,
    headers: Headers,
    log: Log | None = None,
    feedback: str | None = None,
    only: set[str] | None = None,
) -> tuple[Json, Json]:
    """Do the next workout: tick every set of its strength rows with `log(row)`. Returns
    (the workout as it was served, the finish result)."""
    workout = await _next(client, headers)
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    session_id = response.json()["id"]
    for row in _strength(workout):
        values = None if log is None else log(row)
        if values is None or (only is not None and row["exercise"]["id"] not in only):
            continue
        for number in range(1, row["sets"] + 1):
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{number}"
            assert (await client.put(url, json=values, headers=headers)).status_code == 200
    body = {} if feedback is None else {"feedback": feedback}
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)
    assert result.status_code == 200, result.text
    return workout, dict(result.json())


async def _skip_to(client: AsyncClient, headers: Headers, exercise_id: str) -> Json:
    """Skip ahead until the next workout has this exercise; return its row."""
    for _ in range(30):
        workout = await _next(client, headers)
        rows = [e for e in _strength(workout) if e["exercise"]["id"] == exercise_id]
        if rows:
            return rows[0]
        await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
    raise AssertionError("exercise never came back")


def _changes(result: Json) -> dict[str, str]:
    return {p["exercise"]["id"]: p["change"] for p in result["progress"]}


@pytest.fixture
async def home(client: AsyncClient, guest: Headers) -> Headers:
    """A home beginner with the strength test done (nothing logged: no placements)."""
    await _plan(client, guest)
    await _do(client, guest)
    return guest


# --- double progression -----------------------------------------------------------------


async def test_bodyweight_top_reps_add_a_set_then_a_harder_move(
    client: AsyncClient, home: Headers, db_session: AsyncSession
) -> None:
    served, result = await _do(client, home, _top, "just_right")
    row = next(e for e in _strength(served) if not _weighted(e) and not e["seconds"])
    exercise = row["exercise"]
    assert _changes(result)[exercise["id"]] == "extra_set"

    again = await _skip_to(client, home, exercise["id"])
    assert again["sets"] == row["sets"] + 1  # the plan saved row["sets"]
    assert again["reps_min"] == row["reps_min"]

    _, result = await _do(client, home, _top, only={exercise["id"]})
    assert _changes(result)[exercise["id"]] == "harder_move"
    rung = await db_session.scalar(
        select(MovementRung.difficulty).where(
            MovementRung.movement == LIBRARY[exercise["slug"]].movement_slot
        )
    )
    assert rung is not None and rung > exercise["difficulty"]
    plan = (await client.get(CURRENT, headers=home)).json()
    pending = [w for w in plan["workouts"] if w["status"] == "pending"]
    later = [await _workout(client, home, w["id"]) for w in pending]
    same_movement = [
        e["exercise"]
        for w in later
        for e in w["main"]
        if LIBRARY[e["exercise"]["slug"]].movement_slot == LIBRARY[exercise["slug"]].movement_slot
        and not _weighted(e)
    ]
    assert same_movement and all(e["difficulty"] == rung for e in same_movement)


async def test_a_harder_move_keeps_a_strength_test_still_waiting(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    """Skip the test (it moves on, ADR 0017), then earn a harder move before doing it: the
    rebuild must not wipe the test out of the block."""
    plan = await _plan(client, guest)
    await client.post(f"/api/v1/workouts/{plan['next_workout_id']}/skip", headers=guest)
    workout = await _next(client, guest)
    assert not any(e["is_test"] for e in workout["main"])
    row = next(e for e in _strength(workout) if not _weighted(e) and not e["seconds"])
    owner = uuid.UUID((await client.get("/api/v1/me", headers=guest)).json()["id"])
    exercise_id = uuid.UUID(row["exercise"]["id"])
    db_session.add(ExerciseTarget(user_id=owner, exercise_id=exercise_id, set_change=1))
    await db_session.flush()  # as if they had already earned the extra set

    _, result = await _do(client, guest, _top, only={row["exercise"]["id"]})

    assert _changes(result)[row["exercise"]["id"]] == "harder_move"
    plan = (await client.get(CURRENT, headers=guest)).json()
    pending = [w for w in plan["workouts"] if w["status"] == "pending"]
    tests = [e for w in pending for e in (await _workout(client, guest, w["id"]))["main"]]
    assert any(e["is_test"] for e in tests)


async def test_done_workouts_keep_the_numbers_they_had(client: AsyncClient, home: Headers) -> None:
    served, _ = await _do(client, home, _top)

    history = await _workout(client, home, served["id"])

    assert [e["sets"] for e in history["main"]] == [e["sets"] for e in served["main"]]


async def test_gym_top_reps_suggest_the_next_weight_and_reps_start_again(
    client: AsyncClient, guest: Headers
) -> None:
    await _plan(client, guest, GYM)
    await _do(client, guest)
    served, result = await _do(client, guest, _top_with(20.0), "just_right")
    lift = next(e for e in _strength(served) if _weighted(e) and not e["seconds"])
    progress = next(p for p in result["progress"] if p["exercise"]["id"] == lift["exercise"]["id"])
    assert progress["change"] == "heavier"
    assert progress["weight_kg"] in (22.5, 24.0, 25.0)

    again = await _skip_to(client, guest, lift["exercise"]["id"])

    assert again["weight_kg"] == progress["weight_kg"]
    assert again["last"]["weight_kg"] == 20.0
    assert (again["sets"], again["reps_min"]) == (lift["sets"], lift["reps_min"])


async def test_the_last_weight_pre_fills_when_there_is_no_step(
    client: AsyncClient, guest: Headers
) -> None:
    await _plan(client, guest, GYM)
    await _do(client, guest)
    served, _ = await _do(client, guest, lambda e: _bottom(e) | {"weight_kg": 30.0})
    lift = next(e for e in _strength(served) if _weighted(e) and not e["seconds"])

    again = await _skip_to(client, guest, lift["exercise"]["id"])

    assert again["weight_kg"] == 30.0


# --- the feedback tap ----------------------------------------------------------------------


async def test_too_easy_once_aims_two_reps_higher_next_time(
    client: AsyncClient, home: Headers
) -> None:
    served, result = await _do(client, home, _bottom, "too_easy")
    row = next(e for e in _strength(served) if not e["seconds"] and e["reps_min"] < e["reps_max"])
    assert _changes(result)[row["exercise"]["id"]] == "more_reps"

    again = await _skip_to(client, home, row["exercise"]["id"])

    assert again["reps_min"] == min(row["reps_min"] + 2, row["reps_max"])


async def test_too_easy_twice_steps_up_everything_done_before(
    client: AsyncClient, home: Headers
) -> None:
    first, _ = await _do(client, home, _bottom, "too_easy")
    second, result = await _do(client, home, _bottom, "too_easy")

    changes = _changes(result)
    assert all(changes[e["exercise"]["id"]] != "more_reps" for e in _strength(second))
    plan = (await client.get(CURRENT, headers=home)).json()
    upcoming = {
        e["exercise"]["id"]
        for w in plan["workouts"]
        if w["status"] == "pending" and not w["recovery"]
        for e in _strength(await _workout(client, home, w["id"]))
    }
    done_before = {e["exercise"]["id"] for e in _strength(first)} & upcoming
    assert done_before and done_before <= set(changes)
    assert {changes[i] for i in done_before} <= {"extra_set", "longer_hold", "heavier"}


async def test_too_hard_twice_steps_back(client: AsyncClient, home: Headers) -> None:
    await _do(client, home, _bottom, "too_hard")
    second, result = await _do(client, home, _bottom, "too_hard")

    changes = _changes(result)
    assert {changes[e["exercise"]["id"]] for e in _strength(second)} <= {
        "easier_move",
        "shorter_hold",
        "fewer_sets",
        "lighter",
    }
    assert result["recovery_earned"] is True  # 2 of the week's 3: more than half


async def test_a_skipped_tap_doesnt_break_a_pair(client: AsyncClient, home: Headers) -> None:
    """Skipped is no answer (ADR 0018): too easy, (skipped), too easy is a pair."""
    await _do(client, home, _bottom, "too_easy")
    await _do(client, home, _bottom)
    _, result = await _do(client, home, _bottom, "too_easy")

    assert set(_changes(result).values()) & {"extra_set", "heavier"}


async def test_just_right_in_between_breaks_a_pair(client: AsyncClient, home: Headers) -> None:
    await _do(client, home, _bottom, "too_easy")
    await _do(client, home, _bottom, "just_right")
    _, result = await _do(client, home, _bottom, "too_easy")

    assert set(_changes(result).values()) <= {"more_reps", "longer_hold"}


# --- falling short ---------------------------------------------------------------------------


async def test_first_set_well_short_twice_steps_that_exercise_back(
    client: AsyncClient, home: Headers, db_session: AsyncSession
) -> None:
    def short(e: Json) -> Json:
        return {"seconds": 1} if e["seconds"] else {"reps": 0}

    served, result = await _do(client, home, short, "just_right")
    row = _strength(served)[0]
    assert row["exercise"]["id"] not in _changes(result)
    await _skip_to(client, home, row["exercise"]["id"])

    _, result = await _do(client, home, short, only={row["exercise"]["id"]})

    assert _changes(result)[row["exercise"]["id"]] in {"easier_move", "shorter_hold", "fewer_sets"}
    saved = await db_session.scalar(
        select(ExerciseTarget.short_runs).where(ExerciseTarget.exercise_id == row["exercise"]["id"])
    )
    assert saved == 0


# --- the early recovery week -----------------------------------------------------------------


async def test_too_hard_on_most_of_a_week_brings_the_recovery_week_forward(
    client: AsyncClient, guest: Headers
) -> None:
    await _plan(client, guest)
    _, first = await _do(client, guest, None, "too_hard")
    assert first["recovery_earned"] is False

    _, second = await _do(client, guest, None, "too_hard")

    assert second["recovery_earned"] is True
    plan = (await client.get(CURRENT, headers=guest)).json()
    statuses = [(w["recovery"], w["status"]) for w in plan["workouts"]]
    assert statuses[:2] == [(False, "done"), (False, "done")]
    assert {s for r, s in statuses[2:] if not r} == {"replaced_by_recovery"}
    assert {s for r, s in statuses if r} == {"pending"}
    assert (await _next(client, guest))["recovery"] is True
    assert plan["block_complete"] is False


async def test_the_recovery_week_changes_nothing(
    client: AsyncClient, home: Headers, db_session: AsyncSession
) -> None:
    plan = (await client.get(CURRENT, headers=home)).json()
    for workout in plan["workouts"]:
        if workout["status"] == "pending" and not workout["recovery"]:
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=home)

    served, result = await _do(client, home, _top, "too_easy")

    assert served["recovery"] is True
    assert result["progress"] == [] and result["recovery_earned"] is False
    assert (await db_session.scalars(select(ExerciseTarget))).all() == []


# --- the next block -------------------------------------------------------------------------


async def test_progress_carries_into_the_next_block(client: AsyncClient, guest: Headers) -> None:
    await _plan(client, guest, GYM)
    await _do(client, guest)
    served, result = await _do(client, guest, _top_with(20.0))
    stepped = {p["exercise"]["id"]: p["weight_kg"] for p in result["progress"] if p["weight_kg"]}
    plan = (await client.get(CURRENT, headers=guest)).json()
    for workout in plan["workouts"]:
        if workout["status"] == "pending":
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=guest)

    second = (await client.post(PLANS, headers=guest)).json()

    rows = [
        e
        for w in second["workouts"]
        for e in _strength(await _workout(client, guest, w["id"]))
        if e["exercise"]["id"] in stepped and not w["recovery"]
    ]
    assert rows  # big lifts stay from block to block
    assert all(e["weight_kg"] == stepped[e["exercise"]["id"]] for e in rows)
