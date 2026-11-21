"""Doing a workout (ADR 0018): start or continue, tick sets, finish with feedback, the
strength-test placement, and "half counts". Through the API with the real library."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import MovementRung, Plan, PlannedWorkout, WorkoutSession
from lock_in_mode_api.models.enums import MovementSlot, PlanEndReason, WorkoutStatus
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.plan_types import is_weighted

SESSIONS = "/api/v1/sessions"
PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
PROFILE = "/api/v1/me/profile"
SAFETY = "/api/v1/me/safety-screen"
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
GYM = HOME | {"location": "gym"}
LIBRARY = {e.slug: e for e in load_library().exercises}

type Headers = dict[str, str]
type Json = dict[str, Any]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _plan(client: AsyncClient, headers: Headers, answers: Json = HOME) -> Json:
    assert (await client.put(PROFILE, json=answers, headers=headers)).status_code == 201
    assert (await client.post(SAFETY, json=ALL_NO, headers=headers)).status_code == 200
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.fixture
async def plan(client: AsyncClient, guest: Headers) -> Json:
    return await _plan(client, guest)


async def _workout(client: AsyncClient, headers: Headers, workout_id: str) -> Json:
    return dict((await client.get(f"/api/v1/workouts/{workout_id}", headers=headers)).json())


async def _start(client: AsyncClient, headers: Headers, workout_id: str) -> Response:
    return await client.post(SESSIONS, json={"workout_id": workout_id}, headers=headers)


def _set_url(session_id: str, planned_exercise_id: str, set_number: int = 1) -> str:
    return f"{SESSIONS}/{session_id}/sets/{planned_exercise_id}/{set_number}"


async def _tick(
    client: AsyncClient,
    headers: Headers,
    session_id: str,
    exercise: Json,
    set_number: int = 1,
    **values: Any,
) -> Response:
    url = _set_url(session_id, exercise["id"], set_number)
    return await client.put(url, json=values or {"reps": 10}, headers=headers)


async def _finish(
    client: AsyncClient, headers: Headers, session_id: str, feedback: str | None = None
) -> Response:
    body = {} if feedback is None else {"feedback": feedback}
    return await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)


def _test_move(workout: Json, slug: str) -> Json:
    return next(e for e in workout["main"] if e["is_test"] and e["exercise"]["slug"] == slug)


# --- starting and continuing -------------------------------------------------------------


async def test_start_the_next_workout_then_continue_it(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    first = await _start(client, guest, plan["next_workout_id"])
    again = await _start(client, guest, plan["next_workout_id"])

    assert first.status_code == 201
    assert again.status_code == 200  # "Continue"
    assert again.json()["id"] == first.json()["id"]
    current = (await client.get(f"{SESSIONS}/current", headers=guest)).json()
    assert current["id"] == first.json()["id"]
    assert current["workout_id"] == plan["next_workout_id"]
    assert current["finished_at"] is None and current["sets"] == []


async def test_no_open_session_is_not_found(client: AsyncClient, guest: Headers) -> None:
    response = await client.get(f"{SESSIONS}/current", headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"


async def test_only_the_next_workout_can_be_started(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    response = await _start(client, guest, plan["workouts"][2]["id"])

    assert response.status_code == 409
    assert response.json()["code"] == "not_next_workout"


async def test_another_users_workout_cannot_be_started(client: AsyncClient, plan: Json) -> None:
    stranger = (await client.post("/api/v1/auth/guest")).json()["access_token"]

    response = await _start(
        client, {"Authorization": f"Bearer {stranger}"}, plan["next_workout_id"]
    )

    assert response.status_code == 404


# --- ticking sets ---------------------------------------------------------------------


async def test_ticking_a_set_twice_keeps_the_last_values(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]

    first = await _tick(client, guest, session_id, exercise, reps=8)
    fixed = await _tick(client, guest, session_id, exercise, reps=9, weight_kg=12.5)

    assert first.status_code == fixed.status_code == 200
    sets = (await client.get(f"{SESSIONS}/current", headers=guest)).json()["sets"]
    assert sets == [
        {
            "planned_exercise_id": exercise["id"],
            "set_number": 1,
            "reps": 9,
            "weight_kg": 12.5,
            "seconds": None,
        }
    ]


async def test_unticking_a_set_removes_it(client: AsyncClient, guest: Headers, plan: Json) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]
    await _tick(client, guest, session_id, exercise)

    response = await client.delete(_set_url(session_id, exercise["id"]), headers=guest)

    assert response.status_code == 204
    assert (await client.get(f"{SESSIONS}/current", headers=guest)).json()["sets"] == []


async def test_a_set_needs_reps_or_seconds_and_a_sensible_number(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]

    empty = await client.put(_set_url(session_id, exercise["id"]), json={}, headers=guest)
    set_zero = await client.put(
        _set_url(session_id, exercise["id"], 0), json={"reps": 5}, headers=guest
    )
    negative = await _tick(client, guest, session_id, exercise, reps=-1)

    assert empty.status_code == set_zero.status_code == negative.status_code == 422


async def test_an_exercise_from_another_workout_cannot_be_ticked(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    other = (await _workout(client, guest, plan["workouts"][1]["id"]))["main"][0]

    response = await _tick(client, guest, session_id, other)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- finishing --------------------------------------------------------------------------


async def test_finishing_marks_the_workout_done_and_moves_the_queue(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]

    response = await _finish(client, guest, session_id, "just_right")

    assert response.status_code == 200
    result = response.json()
    assert result["feedback"] == "just_right"
    assert result["finished_at"] is not None
    assert result["next_workout_id"] == plan["workouts"][1]["id"]
    assert result["block_complete"] is False
    queue = (await client.get(CURRENT, headers=guest)).json()["workouts"]
    assert queue[0]["status"] == "done"


async def test_feedback_can_be_skipped_and_is_then_empty(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]

    result = (await _finish(client, guest, session_id)).json()

    assert result["feedback"] is None  # no answer, not "just right"


async def test_half_a_workout_counts(client: AsyncClient, guest: Headers, plan: Json) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]
    await _tick(client, guest, session_id, exercise)  # 1 set of many

    result = (await _finish(client, guest, session_id, "too_hard")).json()

    assert result["next_workout_id"] == plan["workouts"][1]["id"]
    assert len(result["sets"]) == 1


async def test_a_finished_session_is_locked(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]
    await _finish(client, guest, session_id)

    for response in (
        await _finish(client, guest, session_id),
        await _tick(client, guest, session_id, exercise),
        await client.delete(_set_url(session_id, exercise["id"]), headers=guest),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "session_finished"


async def test_starting_the_next_workout_finishes_the_open_one(
    client: AsyncClient, guest: Headers, plan: Json, db_session: AsyncSession
) -> None:
    first = (await _start(client, guest, plan["workouts"][0]["id"])).json()["id"]

    response = await _start(client, guest, plan["workouts"][1]["id"])

    assert response.status_code == 201
    old = await db_session.get(WorkoutSession, uuid.UUID(first), populate_existing=True)
    assert old is not None and old.finished_at is not None
    queue = (await client.get(CURRENT, headers=guest)).json()["workouts"]
    assert [w["status"] for w in queue[:2]] == ["done", "pending"]


async def test_a_started_workout_cannot_be_skipped(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    await _start(client, guest, plan["next_workout_id"])

    response = await client.post(f"/api/v1/workouts/{plan['next_workout_id']}/skip", headers=guest)

    assert response.status_code == 409
    assert response.json()["code"] == "session_in_progress"


async def test_finishing_the_last_workout_completes_the_block(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    for workout in plan["workouts"][:-1]:
        await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=guest)
    session_id = (await _start(client, guest, plan["workouts"][-1]["id"])).json()["id"]

    result = (await _finish(client, guest, session_id)).json()

    assert result["block_complete"] is True
    assert result["next_workout_id"] is None


# --- the strength test (KB section 2) ---------------------------------------------------


async def _do_the_test(
    client: AsyncClient, headers: Headers, plan: Json, results: dict[str, Json]
) -> Json:
    workout = await _workout(client, headers, plan["next_workout_id"])
    session_id = (await _start(client, headers, workout["id"])).json()["id"]
    for slug, values in results.items():
        await _tick(client, headers, session_id, _test_move(workout, slug), **values)
    return dict((await _finish(client, headers, session_id, "just_right")).json())


def _bodyweight_difficulties(workouts: list[Json], movement: MovementSlot) -> set[int]:
    return {
        e["exercise"]["difficulty"]
        for w in workouts
        for e in w["main"]
        if LIBRARY[e["exercise"]["slug"]].movement_slot == movement
        and not is_weighted(LIBRARY[e["exercise"]["slug"]])
    }


async def test_the_test_places_each_movement_and_the_rest_of_the_block_follows(
    client: AsyncClient, guest: Headers, plan: Json, db_session: AsyncSession
) -> None:
    result = await _do_the_test(
        client,
        guest,
        plan,
        {"push-up": {"reps": 3}, "bodyweight-squat": {"reps": 30}, "plank": {"seconds": 45}},
    )

    placed = {p["movement"]: (p["result"], p["unit"], p["exercise"]["slug"]) for p in
              result["placements"]}  # fmt: skip
    assert placed == {
        "horizontal_push": (3, "reps", "knee-push-up"),
        "squat": (30, "reps", "one-and-a-half-squat"),
        "brace": (45, "seconds", "plank"),
    }
    rungs = {
        r.movement: r.difficulty
        for r in await db_session.scalars(select(MovementRung).where(MovementRung.result >= 0))
    }
    assert rungs == {MovementSlot.HORIZONTAL_PUSH: 2, MovementSlot.SQUAT: 3, MovementSlot.BRACE: 2}

    later = [await _workout(client, guest, w["id"]) for w in plan["workouts"][1:]]
    assert _bodyweight_difficulties(later, MovementSlot.HORIZONTAL_PUSH) == {2}
    assert _bodyweight_difficulties(later, MovementSlot.SQUAT) == {3}
    assert not any(e["is_test"] for w in later for e in w["main"])
    assert all(w["total_minutes"] <= 30 for w in later)


async def test_a_test_move_left_unlogged_places_nothing(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    result = await _do_the_test(client, guest, plan, {"push-up": {"reps": 20}})

    assert [p["movement"] for p in result["placements"]] == ["horizontal_push"]


async def test_placement_carries_into_the_next_block(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    await _do_the_test(client, guest, plan, {"push-up": {"reps": 0}})
    for workout in plan["workouts"][1:]:
        await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=guest)

    second = (await client.post(PLANS, headers=guest)).json()

    workouts = [await _workout(client, guest, w["id"]) for w in second["workouts"]]
    assert _bodyweight_difficulties(workouts, MovementSlot.HORIZONTAL_PUSH) == {1}
    assert not any(e["is_test"] for w in workouts for e in w["main"])  # test is done


async def test_gym_test_places_nothing_and_the_weight_pre_fills_next_time(
    client: AsyncClient, guest: Headers
) -> None:
    plan = await _plan(client, guest, GYM)
    workout = await _workout(client, guest, plan["next_workout_id"])
    lift = next(e for e in workout["main"] if e["is_test"])
    session_id = (await _start(client, guest, workout["id"])).json()["id"]
    await _tick(client, guest, session_id, lift, reps=10, weight_kg=40)

    result = (await _finish(client, guest, session_id)).json()

    assert result["placements"] == []
    later = [await _workout(client, guest, w["id"]) for w in plan["workouts"][1:]]
    same_lift = [
        e for w in later for e in w["main"] if e["exercise"]["id"] == lift["exercise"]["id"]
    ]
    assert same_lift  # big lifts come back
    assert all(e["last"]["weight_kg"] == 40 and e["last"]["reps"] == 10 for e in same_lift)


async def test_nothing_is_pre_filled_before_the_first_log(
    client: AsyncClient, guest: Headers, plan: Json
) -> None:
    workout = await _workout(client, guest, plan["next_workout_id"])

    assert all(e["last"] is None for e in workout["main"])


# --- answers change mid-workout ---------------------------------------------------------


async def test_changing_answers_mid_workout_finishes_it_and_keeps_the_logs(
    client: AsyncClient, guest: Headers, plan: Json, db_session: AsyncSession
) -> None:
    session_id = (await _start(client, guest, plan["next_workout_id"])).json()["id"]
    exercise = (await _workout(client, guest, plan["next_workout_id"]))["main"][1]
    await _tick(client, guest, session_id, exercise)

    await client.put(PROFILE, json=HOME | {"days_per_week": 4}, headers=guest)

    finished = await db_session.get(WorkoutSession, uuid.UUID(session_id), populate_existing=True)
    assert finished is not None and finished.finished_at is not None
    done = await db_session.get(
        PlannedWorkout, uuid.UUID(plan["next_workout_id"]), populate_existing=True
    )
    assert done is not None and done.status == WorkoutStatus.DONE
    old = await db_session.get(Plan, uuid.UUID(plan["id"]), populate_existing=True)
    assert old is not None and old.end_reason == PlanEndReason.ANSWERS_CHANGED
    new = (await client.get(CURRENT, headers=guest)).json()
    assert new["block_number"] == 2
