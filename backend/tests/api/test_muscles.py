"""The muscle map and the new-bests count through the API (ADR 0036). Real library."""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, PlannedWorkoutExercise, WorkoutSession
from lock_in_mode_api.models.enums import HEAD_GROUP, MuscleGroup, MuscleHead
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

ME = "/api/v1/me"
MUSCLES = "/api/v1/me/muscles"
BESTS = "/api/v1/me/bests"
SESSIONS = "/api/v1/sessions"
NEXT = "/api/v1/plans/current/next"
ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
GYM: dict[str, Any] = {
    "goal": "build_muscle",
    "level": "some_experience",
    "location": "gym",
    "days_per_week": 3,
    "minutes_per_session": 60,
}

type Headers = dict[str, str]
type Json = dict[str, Any]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


async def _guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    headers = await _guest(client)
    assert (await client.put(f"{ME}/profile", json=GYM, headers=headers)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post("/api/v1/plans", headers=headers)).status_code == 201
    return headers


def _main(workout: Json) -> list[Json]:
    return [row for row in workout["main"] if not row["swapped_out"]]


async def _targets(db: AsyncSession, exercise_id: str) -> list[str]:
    targets = await db.scalar(select(Exercise.targets).where(Exercise.id == exercise_id))
    assert targets
    return list(targets)


def _group_sets(muscles: Json) -> dict[str, int]:
    return {g["group"]: g["sets"] for g in muscles["groups"]}


def _head_sets(muscles: Json) -> dict[str, int]:
    return {h["head"]: h["sets"] for g in muscles["groups"] for h in g["heads"]}


async def _do(client: AsyncClient, headers: Headers, ticks: list[tuple[Json, Json]]) -> Json:
    """Start the next workout, tick these (row, values) as set 1, finish."""
    workout = dict((await client.get(NEXT, headers=headers)).json())
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert started.status_code == 201, started.text
    session_id = started.json()["id"]
    for row, values in ticks:
        url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
        assert (await client.put(url, json=values, headers=headers)).status_code == 200
    finished = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert finished.status_code == 200, finished.text
    return dict(finished.json())


def _values(row: Json, reps: int = 10) -> Json:
    return {"seconds": row["seconds"]} if row["seconds"] else {"reps": reps}


async def test_a_new_week_lists_everything_and_marks_the_next_workout(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    muscles = (await client.get(MUSCLES, headers=guest)).json()
    workout = (await client.get(NEXT, headers=guest)).json()

    assert [g["group"] for g in muscles["groups"]] == [g.value for g in MuscleGroup]
    assert len(_head_sets(muscles)) == len(MuscleHead)
    assert set(_group_sets(muscles).values()) == {0}
    assert muscles["next_workout"] == workout["title"]

    expected: set[str] = set()
    for row in _main(workout) + [r for r in workout.get("finisher", []) if not r["swapped_out"]]:
        expected |= set(await _targets(db_session, row["exercise"]["id"]))
    marked = {h["head"] for g in muscles["groups"] for h in g["heads"] if h["next_up"]}
    assert marked == expected
    groups_marked = {g["group"] for g in muscles["groups"] if g["next_up"]}
    assert groups_marked == {HEAD_GROUP[MuscleHead(h)].value for h in expected}


async def test_ticked_sets_light_up_their_heads_and_groups(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    workout = (await client.get(NEXT, headers=guest)).json()
    first = _main(workout)[0]
    targets = await _targets(db_session, first["exercise"]["id"])

    await _do(client, guest, [(first, _values(first))])

    muscles = (await client.get(MUSCLES, headers=guest)).json()
    heads = _head_sets(muscles)
    assert {h for h, n in heads.items() if n} == set(targets)
    assert all(heads[h] == 1 for h in targets)
    groups = _group_sets(muscles)
    assert {g for g, n in groups.items() if n} == {HEAD_GROUP[MuscleHead(h)].value for h in targets}
    assert set(groups.values()) == {0, 1}  # one set counts once per group


async def test_warm_ups_dont_count(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    workout = (await client.get(NEXT, headers=guest)).json()
    warm_up = workout["warm_up"][0]
    # Make the warm-up a move with targets (a warm-up set of the main lift).
    await db_session.execute(
        update(PlannedWorkoutExercise)
        .where(PlannedWorkoutExercise.id == warm_up["id"])
        .values(exercise_id=_main(workout)[0]["exercise"]["id"])
    )
    await db_session.flush()
    await _do(client, guest, [(warm_up, {"reps": 10})])

    assert set(_group_sets((await client.get(MUSCLES, headers=guest)).json()).values()) == {0}


async def test_last_week_doesnt_count(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    workout = (await client.get(NEXT, headers=guest)).json()
    main = _main(workout)[0]
    await _do(client, guest, [(main, _values(main))])
    assert sum(_group_sets((await client.get(MUSCLES, headers=guest)).json()).values()) > 0

    week = timedelta(days=7)
    await db_session.execute(
        update(WorkoutSession).values(
            started_at=WorkoutSession.started_at - week,
            finished_at=WorkoutSession.finished_at - week,
        )
    )
    await db_session.flush()

    assert set(_group_sets((await client.get(MUSCLES, headers=guest)).json()).values()) == {0}


async def test_an_open_workout_doesnt_count_until_finished(
    client: AsyncClient, guest: Headers
) -> None:
    workout = (await client.get(NEXT, headers=guest)).json()
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=guest)
    row = _main(workout)[0]
    url = f"{SESSIONS}/{started.json()['id']}/sets/{row['id']}/1"
    assert (await client.put(url, json=_values(row), headers=guest)).status_code == 200

    assert set(_group_sets((await client.get(MUSCLES, headers=guest)).json()).values()) == {0}


async def test_a_swapped_out_exercise_isnt_next(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    """ "This hurts, swap it" leaves the old row in the workout, marked swapped out."""
    workout = (await client.get(NEXT, headers=guest)).json()
    await db_session.execute(
        update(PlannedWorkoutExercise)
        .where(PlannedWorkoutExercise.planned_workout_id == workout["id"])
        .values(swapped_out=True)
    )
    await db_session.flush()

    muscles = (await client.get(MUSCLES, headers=guest)).json()
    assert muscles["next_workout"] == workout["title"]
    assert not any(g["next_up"] for g in muscles["groups"])


async def test_no_plan_means_nothing_next(client: AsyncClient) -> None:
    headers = await _guest(client)
    muscles = (await client.get(MUSCLES, headers=headers)).json()
    assert muscles["next_workout"] is None
    assert not any(g["next_up"] for g in muscles["groups"])


async def test_bests_count_what_the_finish_screens_showed(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    assert (await client.get(BESTS, headers=guest)).json() == {"total": 0}

    shown = 0
    done_before: Json | None = None
    for reps in (8, 8, 11, 10, 12):
        workout = (await client.get(NEXT, headers=guest)).json()
        row = _main(workout)[0]
        if done_before is None:
            done_before = row
        else:  # the same move every time, so each workout can beat the last
            await db_session.execute(
                update(PlannedWorkoutExercise)
                .where(PlannedWorkoutExercise.id == row["id"])
                .values(exercise_id=done_before["exercise"]["id"])
            )
            await db_session.flush()
        # A warm-up set of the same move, with more reps than ever: never a best.
        warm_up = workout["warm_up"][0]
        await db_session.execute(
            update(PlannedWorkoutExercise)
            .where(PlannedWorkoutExercise.id == warm_up["id"])
            .values(exercise_id=done_before["exercise"]["id"])
        )
        await db_session.flush()
        result = await _do(client, guest, [(warm_up, {"reps": 50}), (row, {"reps": reps})])
        shown += len(result["new_bests"])

    assert shown == 2  # 11 beat 8, 12 beat 11
    assert (await client.get(BESTS, headers=guest)).json() == {"total": shown}


@pytest.mark.parametrize("path", [MUSCLES, BESTS])
async def test_they_need_a_token(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 401
