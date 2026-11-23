"""Interval progression through the API (ADR 0023): HIIT and finishers share one step per
user, served as work and rest; two good workouts step up, two short ones step down; a
finisher left out counts as nothing; feedback pairs; recovery weeks, comebacks, level
changes and the level-up text. Real library.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Comeback, IntervalStep, SetLog, User, WorkoutSession
from lock_in_mode_api.models.enums import FitnessLevel
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
# Full body, HIIT, full body, steady cardio: one HIIT day a week, no finishers.
HIIT_USER: dict[str, Any] = {
    "goal": "lose_fat",
    "level": "some_experience",
    "location": "home",
    "days_per_week": 4,
    "minutes_per_session": 30,
}
# Three full body days, each with a finisher.
FINISHER_USER = HIIT_USER | {"level": "beginner", "days_per_week": 3}
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


async def _plan(
    client: AsyncClient, headers: Headers, answers: Json, safety: Json = ALL_NO
) -> None:
    assert (await client.put("/api/v1/me/profile", json=answers, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=safety, headers=headers)).is_success
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text


@pytest.fixture
async def hiit(client: AsyncClient, guest: Headers) -> Headers:
    await _plan(client, guest, HIIT_USER)
    return guest


@pytest.fixture
async def finishers(client: AsyncClient, guest: Headers) -> Headers:
    await _plan(client, guest, FINISHER_USER)
    return guest


async def _current(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(CURRENT, headers=headers)).json())


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


def _values(row: Json) -> Json:
    values: Json = (
        {"seconds": row["seconds"]}
        if row["seconds"]
        else {"reps": row["reps_max"] or row["reps_min"] or 10}
    )
    if is_weighted(LIBRARY[row["exercise"]["slug"]]):
        values["weight_kg"] = row["weight_kg"] or 10
    return values


def _intervals(workout: Json) -> list[Json]:
    """The rows that use the interval step: HIIT's main block, and every finisher."""
    main = workout["main"] if workout["format"] == "intervals" else []
    return [r for r in [*main, *workout["finisher"]] if not r["swapped_out"]]


def _timing(workout: Json) -> set[tuple[int, int]]:
    return {(r["seconds"], r["rest_seconds"]) for r in _intervals(workout)}


async def _skip_to(client: AsyncClient, headers: Headers, kind: str) -> Json:
    """Skip workouts until the next one is of this kind (skips change no progress)."""
    for _ in range(30):
        workout = await _next(client, headers)
        if workout["kind"] == kind:
            return workout
        response = await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
        assert response.status_code == 200, response.text
    raise AssertionError(f"no {kind} workout")


async def _do(
    client: AsyncClient,
    headers: Headers,
    *,
    rounds: str = "all",
    feedback: str | None = None,
    strength: bool = True,
) -> tuple[Json, Json]:
    """Do the next workout. `rounds`: "all" interval rounds, "one_short" (the last round
    of the last move left out) or "none". `strength`: tick every set of strength work.
    Returns (served, result)."""
    workout = await _next(client, headers)
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert response.status_code in (200, 201), response.text
    session_id = response.json()["id"]
    interval_rows = _intervals(workout)
    ticks: list[tuple[Json, int]] = []
    if strength:
        for row in workout["main"]:
            if row not in interval_rows and not row["swapped_out"]:
                ticks += [(row, n) for n in range(1, row["sets"] + 1)]
    if rounds != "none":
        for row in interval_rows:
            ticks += [(row, n) for n in range(1, row["sets"] + 1)]
        if rounds == "one_short":
            assert interval_rows, "no intervals to leave a round out of"
            ticks.remove((interval_rows[-1], interval_rows[-1]["sets"]))
    for row, n in ticks:
        url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{n}"
        assert (await client.put(url, json=_values(row), headers=headers)).status_code == 200
    body = {} if feedback is None else {"feedback": feedback}
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)
    assert result.status_code == 200, result.text
    return workout, dict(result.json())


async def _hiit(client: AsyncClient, headers: Headers, **kwargs: Any) -> tuple[Json, Json]:
    await _skip_to(client, headers, "hiit")
    return await _do(client, headers, **kwargs)


async def _saved(db: AsyncSession) -> tuple[FitnessLevel, int, int, int] | None:
    row = (
        await db.execute(
            select(
                IntervalStep.level,
                IntervalStep.step,
                IntervalStep.good_runs,
                IntervalStep.short_runs,
            )
        )
    ).first()
    return None if row is None else (row[0], row[1], row[2], row[3])


async def _set_step(db: AsyncSession, level: FitnessLevel, step: int) -> None:
    user_id = await db.scalar(select(User.id).order_by(User.created_at.desc()).limit(1))
    values = {"level": level, "step": step, "good_runs": 0, "short_runs": 0}
    await db.execute(
        insert(IntervalStep)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=[IntervalStep.user_id], set_=values)
    )
    await db.flush()


# --- serving ----------------------------------------------------------------------------


async def test_hiit_is_served_at_the_levels_start(client: AsyncClient, hiit: Headers) -> None:
    workout = await _skip_to(client, hiit, "hiit")
    assert _timing(workout) == {(30, 30)}


async def test_finishers_are_served_at_the_levels_start(
    client: AsyncClient, finishers: Headers
) -> None:
    workout = await _next(client, finishers)
    assert workout["finisher"] and _timing(workout) == {(20, 40)}


async def test_warm_ups_and_steady_cardio_keep_their_numbers(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    before = await _skip_to(client, hiit, "steady_cardio")
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 4)

    after = await _next(client, hiit)

    assert after["main"] == before["main"] and after["warm_up"] == before["warm_up"]


# --- two in a row -----------------------------------------------------------------------


async def test_two_good_hiit_workouts_step_up(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    _, first = await _hiit(client, hiit)
    assert first["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 2, 1, 0)

    _, second = await _hiit(client, hiit)

    assert second["intervals"] == {"direction": "up", "work_seconds": 35, "rest_seconds": 25}
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 3, 0, 0)
    served = await _skip_to(client, hiit, "hiit")
    assert _timing(served) == {(35, 25)}
    # Rounds and effort stay as built: the round is still a minute, the workout no longer.
    assert {(r["sets"], r["effort"]) for r in served["main"]} == {(3, 8)}


async def test_rounds_missed_twice_step_down_and_the_floor_holds(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _hiit(client, hiit, rounds="one_short")
    _, result = await _hiit(client, hiit, rounds="one_short")
    assert result["intervals"] == {"direction": "down", "work_seconds": 25, "rest_seconds": 35}

    await _hiit(client, hiit, rounds="one_short")
    _, at_floor = await _hiit(client, hiit, rounds="one_short")

    assert at_floor["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 1, 0, 0)


async def test_too_hard_twice_is_one_step_down_not_two(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _hiit(client, hiit, feedback="too_hard")
    _, result = await _hiit(client, hiit, feedback="too_hard")

    assert result["intervals"] == {"direction": "down", "work_seconds": 25, "rest_seconds": 35}
    assert (await _saved(db_session))[1] == 1  # type: ignore[index]


async def test_an_extra_round_doesnt_make_up_for_a_missing_one(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    for _ in range(2):
        workout = await _skip_to(client, hiit, "hiit")
        rows = _intervals(workout)
        response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=hiit)
        session_id = response.json()["id"]
        ticks = [(r, n) for r in rows for n in range(1, r["sets"] + 1)]
        ticks.remove((rows[-1], rows[-1]["sets"]))  # the last round of the last move: missed
        ticks.append((rows[0], rows[0]["sets"] + 1))  # one extra of the first move instead
        for row, n in ticks:
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{n}"
            assert (await client.put(url, json=_values(row), headers=hiit)).status_code == 200
        await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=hiit)

    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 1, 0, 0)


async def test_finisher_rounds_move_the_same_step(
    client: AsyncClient, finishers: Headers, db_session: AsyncSession
) -> None:
    await _do(client, finishers)
    _, result = await _do(client, finishers)

    assert result["intervals"] == {"direction": "up", "work_seconds": 25, "rest_seconds": 35}
    assert _timing(await _next(client, finishers)) == {(25, 35)}


async def test_a_finisher_left_out_counts_as_nothing(
    client: AsyncClient, finishers: Headers, db_session: AsyncSession
) -> None:
    for _ in range(3):
        _, result = await _do(client, finishers, rounds="none")
        assert result["intervals"] is None

    assert await _saved(db_session) is None


async def test_a_left_out_finisher_doesnt_break_a_run(
    client: AsyncClient, finishers: Headers, db_session: AsyncSession
) -> None:
    await _do(client, finishers)
    await _do(client, finishers, rounds="none")
    _, result = await _do(client, finishers)

    assert result["intervals"] is not None and result["intervals"]["direction"] == "up"


# --- feedback pairs -----------------------------------------------------------------------


async def test_a_pair_moves_intervals_only_after_doing_them(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    # Two strength workouts, "too easy" twice, before any HIIT: nothing to step from.
    await _skip_to(client, hiit, "full_body")
    await _do(client, hiit, feedback="too_easy")
    await _skip_to(client, hiit, "full_body")
    _, never = await _do(client, hiit, feedback="too_easy")
    assert never["intervals"] is None and await _saved(db_session) is None

    await _hiit(client, hiit, feedback="just_right")  # one good: the runs start
    await _skip_to(client, hiit, "full_body")
    await _do(client, hiit, feedback="too_easy")
    await _skip_to(client, hiit, "full_body")
    _, pair = await _do(client, hiit, feedback="too_easy")

    assert pair["intervals"] == {"direction": "up", "work_seconds": 35, "rest_seconds": 25}
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 3, 0, 0)


async def test_a_pair_leaves_intervals_alone_when_the_plan_has_none(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 2)
    profile = HIIT_USER | {"goal": "build_muscle", "days_per_week": 3}
    assert (await client.put("/api/v1/me/profile", json=profile, headers=hiit)).is_success

    await _do(client, hiit, feedback="too_easy")
    _, pair = await _do(client, hiit, feedback="too_easy")

    assert pair["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 2, 0, 0)


async def test_low_intensity_has_no_intervals_and_saves_nothing(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _plan(client, guest, HIIT_USER, ALL_NO | {"heart_condition": True})
    for workout in (await _current(client, guest))["workouts"]:
        detail = (await client.get(f"/api/v1/workouts/{workout['id']}", headers=guest)).json()
        assert not _intervals(detail)

    for _ in range(3):
        _, result = await _do(client, guest, feedback="too_easy")
        assert result["intervals"] is None
    assert await _saved(db_session) is None


# --- recovery weeks, comebacks, level changes ---------------------------------------------


async def test_the_recovery_week_keeps_the_step_and_changes_nothing(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 3)
    for _ in range(30):
        workout = await _next(client, hiit)
        if workout["recovery"] and workout["kind"] == "hiit":
            break
        await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=hiit)

    served, result = await _do(client, hiit, feedback="too_easy")

    assert _timing(served) == {(35, 25)}
    assert {r["sets"] for r in served["main"]} == {2}  # half of 3 rounds, rounded up
    assert result["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 3, 0, 0)


async def _away(db: AsyncSession, days: int) -> None:
    shift = timedelta(days=days)
    await db.execute(update(SetLog).values(logged_at=SetLog.logged_at - shift))
    await db.execute(
        update(WorkoutSession).values(
            started_at=WorkoutSession.started_at - shift,
            finished_at=WorkoutSession.finished_at - shift,
        )
    )
    await db.flush()
    db.expire_all()


async def test_a_comeback_serves_one_step_easier_and_changes_nothing(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _do(client, hiit)  # trained once, then a break
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 3)
    await _away(db_session, 20)  # 2-4 weeks: one easy week

    served, result = await _hiit(client, hiit)

    assert served["comeback_week"] == 1
    assert _timing(served) == {(30, 30)}
    assert result["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.SOME_EXPERIENCE, 3, 0, 0)
    assert await db_session.scalar(select(func.count()).select_from(Comeback)) == 1


async def test_the_last_ramp_week_serves_the_saved_step(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _do(client, hiit)
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 3)
    await _away(db_session, 40)  # over 4 weeks: a 3-week ramp, week 3 eases no effort

    plan = await _current(client, hiit)
    week3 = [w for w in plan["workouts"] if w["comeback_week"] == 3 and w["kind"] == "hiit"]
    week1 = [w for w in plan["workouts"] if w["comeback_week"] == 1 and w["kind"] == "hiit"]
    assert week3 and week1
    detail3 = (await client.get(f"/api/v1/workouts/{week3[0]['id']}", headers=hiit)).json()
    detail1 = (await client.get(f"/api/v1/workouts/{week1[0]['id']}", headers=hiit)).json()

    assert _timing(detail3) == {(35, 25)}
    assert _timing(detail1) == {(30, 30)}


async def test_a_new_level_starts_at_its_own_timing(
    client: AsyncClient, hiit: Headers, db_session: AsyncSession
) -> None:
    await _set_step(db_session, FitnessLevel.SOME_EXPERIENCE, 1)
    profile = HIIT_USER | {"level": "experienced"}
    assert (await client.put("/api/v1/me/profile", json=profile, headers=hiit)).is_success

    assert _timing(await _skip_to(client, hiit, "hiit")) == {(40, 20)}
    _, result = await _hiit(client, hiit)  # counts at the new level, from its start
    assert result["intervals"] is None
    assert await _saved(db_session) == (FitnessLevel.EXPERIENCED, 4, 1, 0)


# --- the level-up text (ADR 0022) ---------------------------------------------------------

MARKS = {"push-up": {"reps": 15}, "bodyweight-squat": {"reps": 25}, "plank": {"seconds": 45}}


async def _strong_at_block_complete(client: AsyncClient, headers: Headers) -> Json:
    """The strength test with all three marks, the rest of the block skipped."""
    workout = await _next(client, headers)
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    session_id = response.json()["id"]
    for row in workout["main"]:
        if row["exercise"]["slug"] in MARKS:
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
            values = MARKS[row["exercise"]["slug"]]
            assert (await client.put(url, json=values, headers=headers)).status_code == 200
    await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    for workout in (await _current(client, headers))["workouts"]:
        if workout["status"] == "pending":
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
    return await _current(client, headers)


@pytest.mark.parametrize(
    ("step", "line"),
    [
        (None, "Intervals: 20 s on / 40 s off → 30 s on / 30 s off."),
        (1, "Intervals: 25 s on / 35 s off → 30 s on / 30 s off."),
        (2, None),  # already on 30/30
    ],
)
async def test_level_up_says_how_intervals_change(
    client: AsyncClient,
    finishers: Headers,
    db_session: AsyncSession,
    step: int | None,
    line: str | None,
) -> None:
    if step is not None:
        await _set_step(db_session, FitnessLevel.BEGINNER, step)

    plan = await _strong_at_block_complete(client, finishers)

    lines = plan["level_up"]["what_changes"]
    intervals = [x for x in lines if x.startswith("Intervals")]
    assert intervals == ([] if line is None else [line])
    assert (await client.post(PLANS, json={"level_up": True}, headers=finishers)).is_success
    assert _timing(await _next(client, finishers)) == {(30, 30)}
