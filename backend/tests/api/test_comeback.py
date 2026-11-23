"""Coming back after a break through the API (ADR 0021): the bands, eased numbers, saving on
start, the ease-in running out, skips, opting out, the recovery week the break replaces,
a new break, and progress staying untouched. Real library.

A break is faked by moving the user's history back in time (`_away`).
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Comeback,
    ExerciseTarget,
    PlannedWorkout,
    SetLog,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import ComebackEndReason, WorkoutStatus
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training import comeback as rules
from lock_in_mode_api.training.plan_types import is_weighted
from lock_in_mode_api.training.progression import weight_step

SESSIONS = "/api/v1/sessions"
PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
COMEBACK = "/api/v1/me/comeback"
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
GYM = HOME | {"location": "gym", "level": "some_experience", "minutes_per_session": 45}
LIBRARY = {e.slug: e for e in load_library().exercises}
WEIGHT = 20.0

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
    assert (await client.put("/api/v1/me/profile", json=answers, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=ALL_NO, headers=headers)).is_success
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _current(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(CURRENT, headers=headers)).json())


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


def _strength(workout: Json) -> list[Json]:
    return [e for e in workout["main"] if e["reps_in_reserve"] is not None and not e["is_test"]]


def _values(row: Json) -> Json:
    """A set of this row: its top (open test sets: 10 reps), with a weight where one fits."""
    values: Json = (
        {"seconds": row["seconds"]}
        if row["seconds"]
        else {"reps": row["reps_max"] or row["reps_min"] or 10}
    )
    if is_weighted(LIBRARY[row["exercise"]["slug"]]):
        values["weight_kg"] = row["weight_kg"] or WEIGHT
    return values


async def _start(client: AsyncClient, headers: Headers, workout: Json) -> str:
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


async def _tick(client: AsyncClient, headers: Headers, session_id: str, row: Json, n: int) -> None:
    url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{n}"
    assert (await client.put(url, json=_values(row), headers=headers)).status_code == 200


async def _train(
    client: AsyncClient, headers: Headers, feedback: str | None = None, *, top: bool = True
) -> tuple[Json, Json]:
    """Do the next workout, ticking every set of its main block. Returns (served, result)."""
    workout = await _next(client, headers)
    session_id = await _start(client, headers, workout)
    for row in workout["main"]:
        if row["swapped_out"]:
            continue
        for n in range(1, (row["sets"] if top else 1) + 1):
            await _tick(client, headers, session_id, row, n)
    body = {} if feedback is None else {"feedback": feedback}
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)
    assert result.status_code == 200, result.text
    return workout, dict(result.json())


async def _away(db: AsyncSession, days: int) -> None:
    """Pretend everything trained so far (and any comeback) happened `days` days earlier."""
    shift = timedelta(days=days)
    await db.execute(update(SetLog).values(logged_at=SetLog.logged_at - shift))
    await db.execute(
        update(WorkoutSession).values(
            started_at=WorkoutSession.started_at - shift,
            finished_at=WorkoutSession.finished_at - shift,
        )
    )
    await db.execute(
        update(Comeback).values(
            trained_until=Comeback.trained_until - shift,
            started_at=Comeback.started_at - shift,
            ended_at=Comeback.ended_at - shift,
        )
    )
    await db.flush()
    db.expire_all()


async def _comebacks(db: AsyncSession) -> list[Comeback]:
    return list(
        (
            await db.scalars(
                select(Comeback)
                .order_by(Comeback.started_at)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


@pytest.fixture
async def gym(client: AsyncClient, guest: Headers) -> Headers:
    """A gym user who did the strength test and one more workout with weights."""
    await _plan(client, guest, GYM)
    await _train(client, guest)
    await _train(client, guest)
    return guest


@pytest.fixture
async def home(client: AsyncClient, guest: Headers) -> Headers:
    await _plan(client, guest)
    await _train(client, guest)
    await _train(client, guest)
    return guest


def _by_id(workout: Json) -> dict[str, Json]:
    return {e["id"]: e for e in workout["main"]}


def _eased_like(before: Json, after: Json, ease: rules.Ease) -> None:
    """`after` is `before` with this week's easing, row by row."""
    eased = _by_id(after)
    for row in _strength(before):
        now = eased[row["id"]]
        assert now["sets"] == rules.eased_sets(row["sets"], ease), row["exercise"]["slug"]
        exercise = LIBRARY[row["exercise"]["slug"]]
        if row["weight_kg"] is not None:
            step = weight_step(exercise.equipment, exercise.also_needs, exercise.movement_slot)
            assert now["weight_kg"] == rules.eased_weight(row["weight_kg"], ease, step)
        if row["seconds"] is not None and exercise.is_timed:
            assert now["seconds"] == rules.eased_seconds(row["seconds"], ease)


# --- noticing a break -------------------------------------------------------------------


@pytest.mark.parametrize(("days", "weeks"), [(13, None), (14, 1), (28, 1), (29, 3)])
async def test_the_bands(
    client: AsyncClient, gym: Headers, db_session: AsyncSession, days: int, weeks: int | None
) -> None:
    before = await _next(client, gym)
    await _away(db_session, days)

    plan = await _current(client, gym)
    after = await _next(client, gym)

    if weeks is None:
        assert plan["comeback"] is None
        assert after == before
        return
    assert plan["comeback"] == {
        "away_days": days,
        "weeks": weeks,
        "week": 1,
        "workouts_left": weeks * 3,
        "started": False,
    }
    assert after["comeback_week"] == 1
    _eased_like(before, after, rules.ease_for(weeks, 1))


async def test_never_trained_is_no_break(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _plan(client, guest)
    workout = await _next(client, guest)
    await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=guest)
    await _away(db_session, 60)

    assert (await _current(client, guest))["comeback"] is None


async def test_home_bodyweight_keeps_the_move_and_aims_low(
    client: AsyncClient, home: Headers, db_session: AsyncSession
) -> None:
    before = await _next(client, home)
    await _away(db_session, 40)

    after = await _next(client, home)

    assert [e["exercise"]["id"] for e in after["main"]] == [
        e["exercise"]["id"] for e in before["main"]
    ]
    _eased_like(before, after, rules.RAMP[0])
    for row in _strength(before):
        now = _by_id(after)[row["id"]]
        if row["reps_min"] is not None:
            assert now["reps_min"] <= row["reps_min"]
    assert [e for e in after["warm_up"]] == [e for e in before["warm_up"]]
    assert [e for e in after["cool_down"]] == [e for e in before["cool_down"]]


# --- saving and counting ------------------------------------------------------------------


async def test_nothing_is_saved_until_the_first_workout_back_starts(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 20)
    await _current(client, gym)
    await _next(client, gym)
    assert await _comebacks(db_session) == []

    workout = await _next(client, gym)
    await _start(client, gym, workout)

    [comeback] = await _comebacks(db_session)
    assert (comeback.away_days, comeback.weeks, comeback.workouts_per_week) == (20, 1, 3)
    assert comeback.ended_at is None
    linked = await db_session.scalar(
        select(WorkoutSession).where(WorkoutSession.finished_at.is_(None))
    )
    assert linked is not None
    assert (linked.comeback_id, linked.comeback_week) == (comeback.id, 1)
    plan = await _current(client, gym)
    assert plan["comeback"]["started"] is True
    assert (await _next(client, gym))["comeback_week"] == 1  # a started one stays eased


async def test_the_easy_week_ends_after_a_weeks_workouts(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 20)
    for left in (3, 2, 1):
        assert (await _current(client, gym))["comeback"]["workouts_left"] == left
        served, _ = await _train(client, gym)
        assert served["comeback_week"] == 1

    assert (await _current(client, gym))["comeback"] is None
    assert (await _next(client, gym))["comeback_week"] is None
    [comeback] = await _comebacks(db_session)
    assert comeback.end_reason == ComebackEndReason.DONE


async def test_the_ramp_goes_week_by_week_and_skips_dont_count(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 40)
    plan = await _current(client, gym)
    queued = [
        w["comeback_week"]
        for w in plan["workouts"]
        if w["status"] == "pending" and not w["recovery"]
    ]
    assert queued[:9] == [1, 1, 1, 2, 2, 2, 3, 3, 3][: len(queued)]

    first = await _next(client, gym)
    await client.post(f"/api/v1/workouts/{first['id']}/skip", headers=gym)

    plan = await _current(client, gym)
    assert plan["comeback"]["workouts_left"] == 9
    assert (await _next(client, gym))["comeback_week"] == 1


async def test_comeback_workouts_change_no_progress(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    targets_before = {
        (t.exercise_id, t.weight_kg, t.set_change, t.reps_bonus)
        for t in await db_session.scalars(select(ExerciseTarget))
    }
    await _away(db_session, 40)

    for _ in range(3):
        _, result = await _train(client, gym, "too_easy")
        assert result["progress"] == [] and result["recovery_earned"] is False

    db_session.expire_all()
    targets_after = {
        (t.exercise_id, t.weight_kg, t.set_change, t.reps_bonus)
        for t in await db_session.scalars(select(ExerciseTarget))
    }
    assert targets_after == targets_before


async def test_comeback_taps_dont_make_a_pair_afterwards(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 20)
    for _ in range(3):
        await _train(client, gym, "too_hard")
    assert (await _current(client, gym))["comeback"] is None

    _, result = await _train(client, gym, "too_hard")

    # One "too hard" after the comeback: repeat the numbers. With the comeback's taps it
    # would make a pair and step everything back.
    assert result["progress"] == []
    assert result["recovery_earned"] is False


# --- opting out -----------------------------------------------------------------------------


async def test_opting_out_before_the_first_workout_back(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    before = await _next(client, gym)
    await _away(db_session, 40)

    response = await client.delete(COMEBACK, headers=gym)

    assert response.status_code == 204
    assert (await _current(client, gym))["comeback"] is None
    after = await _next(client, gym)
    assert after["comeback_week"] is None
    assert [e["sets"] for e in after["main"]] == [e["sets"] for e in before["main"]]
    [comeback] = await _comebacks(db_session)
    assert comeback.end_reason == ComebackEndReason.OPTED_OUT
    assert (await client.delete(COMEBACK, headers=gym)).status_code == 404


async def test_opting_out_mid_comeback_keeps_the_started_workout(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 40)
    await _train(client, gym)
    started = await _next(client, gym)
    await _start(client, gym, started)

    assert (await client.delete(COMEBACK, headers=gym)).status_code == 204

    again = await _next(client, gym)
    assert again["id"] == started["id"]
    assert again["comeback_week"] == 1 and again["main"] == started["main"]
    plan = await _current(client, gym)
    later = [w for w in plan["workouts"] if w["status"] == "pending" and w["id"] != started["id"]]
    assert all(w["comeback_week"] is None for w in later)


async def test_no_break_no_opt_out(client: AsyncClient, gym: Headers) -> None:
    response = await client.delete(COMEBACK, headers=gym)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- the recovery week ----------------------------------------------------------------------


async def _skip_build_ups(client: AsyncClient, headers: Headers) -> None:
    for workout in (await _current(client, headers))["workouts"]:
        if workout["status"] == "pending" and not workout["recovery"]:
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)


async def test_a_break_replaces_a_waiting_recovery_week(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _skip_build_ups(client, gym)
    assert (await _next(client, gym))["recovery"] is True
    await _away(db_session, 20)

    plan = await _current(client, gym)
    assert plan["block_complete"] is True and plan["next_workout_id"] is None
    assert (await client.get(f"{CURRENT}/next", headers=gym)).status_code == 404

    second = (await client.post(PLANS, headers=gym)).json()

    old = await db_session.scalars(
        select(PlannedWorkout.status).where(
            PlannedWorkout.plan_id == plan["id"], PlannedWorkout.recovery.is_(True)
        )
    )
    assert set(old) == {WorkoutStatus.REPLACED_BY_BREAK}
    assert second["comeback"]["weeks"] == 1
    assert (await _next(client, gym))["comeback_week"] == 1


async def test_a_break_keeps_the_recovery_week_when_build_ups_are_left(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 20)
    await _train(client, gym)

    plan = await _current(client, gym)
    recovery = {w["status"] for w in plan["workouts"] if w["recovery"]}
    assert recovery == {"pending"}
    assert all(w["comeback_week"] is None for w in plan["workouts"] if w["recovery"])


async def test_opting_out_keeps_the_recovery_week(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _skip_build_ups(client, gym)
    await _away(db_session, 20)
    assert (await _current(client, gym))["block_complete"] is True

    assert (await client.delete(COMEBACK, headers=gym)).status_code == 204

    assert (await _next(client, gym))["recovery"] is True


# --- breaks and open workouts ---------------------------------------------------------------


async def test_a_new_break_starts_a_new_comeback(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    await _away(db_session, 20)
    await _train(client, gym)
    await _away(db_session, 40)

    plan = await _current(client, gym)
    assert plan["comeback"]["weeks"] == 3 and plan["comeback"]["started"] is False
    await _start(client, gym, await _next(client, gym))

    first, second = await _comebacks(db_session)
    assert first.end_reason == ComebackEndReason.NEW_BREAK
    assert (second.weeks, second.ended_at) == (3, None)


async def test_a_workout_left_open_joins_the_comeback(
    client: AsyncClient, gym: Headers, db_session: AsyncSession
) -> None:
    workout = await _next(client, gym)
    session_id = await _start(client, gym, workout)
    await _tick(client, gym, session_id, _strength(workout)[0], 1)
    await _away(db_session, 20)

    eased = await _next(client, gym)
    assert eased["id"] == workout["id"] and eased["comeback_week"] == 1
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=gym)

    assert response.status_code == 200 and response.json()["id"] == session_id
    linked = await db_session.scalar(
        select(WorkoutSession)
        .where(WorkoutSession.finished_at.is_(None))
        .execution_options(populate_existing=True)
    )
    assert linked is not None and linked.comeback_week == 1
    assert (await _current(client, gym))["comeback"]["started"] is True


async def test_a_waiting_strength_test_is_not_eased(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _plan(client, guest)
    workout = await _next(client, guest)
    assert any(e["is_test"] for e in workout["main"])
    session_id = await _start(client, guest, workout)
    await _tick(client, guest, session_id, workout["warm_up"][0], 1)
    await _away(db_session, 40)

    eased = await _next(client, guest)

    assert eased["comeback_week"] == 1
    tests = [e for e in eased["main"] if e["is_test"]]
    assert tests == [e for e in workout["main"] if e["is_test"]]
