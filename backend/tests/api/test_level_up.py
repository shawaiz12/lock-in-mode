"""Moving up a level through the API (ADR 0022): offered only at block complete, by the
three marks or 12 good weeks, only to beginners, not during a comeback; yes moves the
level up for the next block, "not yet" asks again next block. Real library.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Comeback,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    SetLog,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import SessionKind, WorkoutPart
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

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
GYM = HOME | {"location": "gym", "days_per_week": 2, "minutes_per_session": 45}
MARKS = {"push-up": {"reps": 15}, "bodyweight-squat": {"reps": 25}, "plank": {"seconds": 45}}

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
    client: AsyncClient, headers: Headers, answers: Json = HOME, safety: Json = ALL_NO
) -> Json:
    assert (await client.put("/api/v1/me/profile", json=answers, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=safety, headers=headers)).is_success
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _current(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(CURRENT, headers=headers)).json())


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


async def _level(client: AsyncClient, headers: Headers) -> str:
    return str((await client.get("/api/v1/me/profile", headers=headers)).json()["level"])


async def _do(client: AsyncClient, headers: Headers, sets: dict[str, Json] | None = None) -> Json:
    """Do the next workout. `sets`: one set per exercise slug with these values; without
    it, one easy set (10 reps or 20 s) of the first main exercise."""
    workout = await _next(client, headers)
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    session_id = response.json()["id"]
    rows = [r for r in workout["main"] if not r["swapped_out"]]
    if sets is None:
        first = rows[0]
        ticks = [(first, {"seconds": 20} if first["seconds"] else {"reps": 10})]
    else:
        ticks = [(r, sets[r["exercise"]["slug"]]) for r in rows if r["exercise"]["slug"] in sets]
        assert len(ticks) == len(sets), [r["exercise"]["slug"] for r in rows]
    for row, values in ticks:
        url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
        assert (await client.put(url, json=values, headers=headers)).status_code == 200
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert result.status_code == 200, result.text
    return workout


async def _finish_block(client: AsyncClient, headers: Headers) -> Json:
    for workout in (await _current(client, headers))["workouts"]:
        if workout["status"] == "pending":
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
    plan = await _current(client, headers)
    assert plan["block_complete"] is True
    return plan


async def _train(client: AsyncClient, headers: Headers, workouts: int) -> None:
    """Train this many workouts, starting a new block (same level) whenever one ends."""
    for _ in range(workouts):
        if (await _current(client, headers))["block_complete"]:
            assert (await client.post(PLANS, headers=headers)).status_code == 201
        await _do(client, headers)


async def _spread(db: AsyncSession, per_week: int = 2) -> None:
    """Move the trained workouts into the past, `per_week` in each 7-day stretch."""
    sessions = (
        await db.scalars(
            select(WorkoutSession)
            .where(WorkoutSession.finished_at.is_not(None))
            .order_by(WorkoutSession.finished_at)
        )
    ).all()
    start = datetime.now(UTC) - timedelta(days=400)
    for n, s in enumerate(sessions):
        finished = start + timedelta(days=7 * (n // per_week), hours=n % per_week)
        await db.execute(
            update(WorkoutSession)
            .where(WorkoutSession.id == s.id)
            .values(started_at=finished - timedelta(hours=1), finished_at=finished)
        )
    await db.flush()
    db.expire_all()


@pytest.fixture
async def strong(client: AsyncClient, guest: Headers) -> Headers:
    """A home beginner who hit all three marks in the strength test, block complete."""
    await _plan(client, guest)
    await _do(client, guest, MARKS)
    return guest


# --- when it's offered ------------------------------------------------------------------


async def test_the_marks_are_offered_at_block_complete_not_before(
    client: AsyncClient, strong: Headers
) -> None:
    assert (await _current(client, strong))["level_up"] is None  # block still going

    plan = await _finish_block(client, strong)

    offer = plan["level_up"]
    assert offer["to"] == "some_experience" and offer["reason"] == "strength_marks"
    assert offer["check_with_doctor"] is False
    assert offer["what_changes"][-1].startswith("Your progress stays")
    assert not any(line.startswith("Your safety limits") for line in offer["what_changes"])


async def test_one_mark_short_is_no_offer(client: AsyncClient, guest: Headers) -> None:
    await _plan(client, guest)
    await _do(client, guest, MARKS | {"plank": {"seconds": 40}})

    assert (await _finish_block(client, guest))["level_up"] is None


@pytest.mark.parametrize(("workouts", "offered"), [(22, False), (24, True)])
async def test_twelve_good_weeks(
    client: AsyncClient, guest: Headers, db_session: AsyncSession, workouts: int, offered: bool
) -> None:
    await _plan(client, guest, GYM)
    await _train(client, guest, workouts)
    await _spread(db_session)

    offer = (await _finish_block(client, guest))["level_up"]

    if not offered:
        assert offer is None
        return
    assert (offer["reason"], offer["good_weeks"]) == ("good_weeks", 12)


async def test_one_workout_a_week_doesnt_count(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _plan(client, guest, GYM)
    await _train(client, guest, 24)
    await _spread(db_session, per_week=1)

    assert (await _finish_block(client, guest))["level_up"] is None


async def test_only_beginners_are_offered(client: AsyncClient, guest: Headers) -> None:
    await _plan(client, guest, HOME | {"level": "some_experience"})
    await _do(client, guest, MARKS)

    assert (await _finish_block(client, guest))["level_up"] is None


async def test_no_offer_during_a_comeback(
    client: AsyncClient, strong: Headers, db_session: AsyncSession
) -> None:
    await _finish_block(client, strong)
    shift = timedelta(days=20)
    await db_session.execute(update(SetLog).values(logged_at=SetLog.logged_at - shift))
    await db_session.flush()

    plan = await _current(client, strong)

    assert plan["comeback"] is not None and plan["level_up"] is None
    response = await client.post(PLANS, json={"level_up": True}, headers=strong)
    assert response.status_code == 409
    assert response.json()["code"] == "level_up_not_offered"
    assert await db_session.scalar(select(Comeback.id)) is None  # nothing saved


# --- yes and not yet --------------------------------------------------------------------


async def test_yes_builds_the_next_block_at_the_new_level(
    client: AsyncClient, strong: Headers, db_session: AsyncSession
) -> None:
    await _finish_block(client, strong)

    response = await client.post(PLANS, json={"level_up": True}, headers=strong)

    assert response.status_code == 201, response.text
    assert response.json()["level_up"] is None
    assert await _level(client, strong) == "some_experience"
    plans = (await db_session.scalars(select(Plan).order_by(Plan.block_number))).all()
    assert [p.generated_from["level"] for p in plans] == ["beginner", "some_experience"]
    assert [p.end_reason.value if p.end_reason else None for p in plans] == ["finished", None]


async def test_not_yet_keeps_the_level_and_asks_again_next_block(
    client: AsyncClient, strong: Headers
) -> None:
    await _finish_block(client, strong)

    assert (await client.post(PLANS, headers=strong)).status_code == 201

    assert await _level(client, strong) == "beginner"
    assert (await _current(client, strong))["level_up"] is None  # the new block is going
    assert (await _finish_block(client, strong))["level_up"]["reason"] == "strength_marks"


async def test_low_intensity_users_are_offered_and_keep_their_limits(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _plan(client, guest, safety=ALL_NO | {"heart_condition": True})
    await _do(client, guest, MARKS)

    offer = (await _finish_block(client, guest))["level_up"]
    assert offer["check_with_doctor"] is True
    assert any(line.startswith("Your safety limits stay") for line in offer["what_changes"])
    plan = (await client.post(PLANS, json={"level_up": True}, headers=guest)).json()

    profile = (await client.get("/api/v1/me/profile", headers=guest)).json()
    assert (profile["level"], profile["needs_low_intensity"]) == ("some_experience", True)
    kinds = (
        await db_session.scalars(
            select(PlannedWorkout.kind).where(PlannedWorkout.plan_id == plan["id"])
        )
    ).all()
    assert SessionKind.HIIT not in kinds
    finishers = await db_session.scalar(
        select(PlannedWorkoutExercise.id)
        .join(PlannedWorkout)
        .where(
            PlannedWorkout.plan_id == plan["id"],
            PlannedWorkoutExercise.part == WorkoutPart.FINISHER,
        )
    )
    assert finishers is None


# --- refusals ---------------------------------------------------------------------------


async def test_yes_without_an_offer_is_refused(client: AsyncClient, guest: Headers) -> None:
    assert (await client.put("/api/v1/me/profile", json=HOME, headers=guest)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=ALL_NO, headers=guest)).is_success

    first = await client.post(PLANS, json={"level_up": True}, headers=guest)
    assert (first.status_code, first.json()["code"]) == (409, "level_up_not_offered")

    assert (await client.post(PLANS, headers=guest)).status_code == 201
    busy = await client.post(PLANS, json={"level_up": True}, headers=guest)
    assert (busy.status_code, busy.json()["code"]) == (409, "plan_in_progress")

    await _finish_block(client, guest)  # nothing trained: not earned
    unearned = await client.post(PLANS, json={"level_up": True}, headers=guest)
    assert (unearned.status_code, unearned.json()["code"]) == (409, "level_up_not_offered")
    assert await _level(client, guest) == "beginner"


async def test_an_unknown_field_is_a_validation_error(client: AsyncClient, strong: Headers) -> None:
    await _finish_block(client, strong)
    response = await client.post(PLANS, json={"levelup": True}, headers=strong)
    assert response.status_code == 422
