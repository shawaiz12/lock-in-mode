"""This week, the streak, new bests and the reminder through the API (ADR 0034)."""

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Event, PlannedWorkoutExercise, WorkoutSession
from lock_in_mode_api.models.enums import EventName
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

ME = "/api/v1/me"
WEEK = "/api/v1/me/week"
SESSIONS = "/api/v1/sessions"
NEXT = "/api/v1/plans/current/next"
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

type Headers = dict[str, str]
type Json = dict[str, Any]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert (await client.put("/api/v1/me/profile", json=HOME, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post("/api/v1/plans", headers=headers)).status_code == 201
    return headers


def _main(workout: Json) -> Json:
    return next(row for row in workout["main"] if not row["swapped_out"])


async def _start(client: AsyncClient, headers: Headers) -> tuple[Json, str]:
    workout = dict((await client.get(NEXT, headers=headers)).json())
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert started.status_code in (200, 201), started.text
    return workout, str(started.json()["id"])


async def _tick(
    client: AsyncClient, headers: Headers, session_id: str, row: Json, **v: Any
) -> None:
    body = v or ({"seconds": row["seconds"]} if row["seconds"] else {"reps": 10})
    url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
    assert (await client.put(url, json=body, headers=headers)).status_code == 200


async def _finish(client: AsyncClient, headers: Headers, session_id: str) -> Json:
    response = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _train(client: AsyncClient, headers: Headers) -> Json:
    workout, session_id = await _start(client, headers)
    await _tick(client, headers, session_id, _main(workout))
    return await _finish(client, headers, session_id)


# --- this week --------------------------------------------------------------------------


async def test_a_new_week(client: AsyncClient, guest: Headers) -> None:
    week = (await client.get(WEEK, headers=guest)).json()
    assert week["done"] == 0
    assert week["planned"] == 3
    assert week["keep_at"] == 2
    assert (week["kept"], week["streak"], week["freezes"], week["last_week"]) == (False, 0, 0, None)


async def test_two_workouts_keep_the_week(client: AsyncClient, guest: Headers) -> None:
    first = await _train(client, guest)
    second = await _train(client, guest)

    assert (first["week"]["done"], first["week"]["kept"]) == (1, False)
    assert (second["week"]["done"], second["week"]["kept"], second["week"]["streak"]) == (
        2,
        True,
        1,
    )
    assert (await client.get(WEEK, headers=guest)).json() == second["week"]


async def test_a_finish_with_nothing_ticked_doesnt_count(
    client: AsyncClient, guest: Headers
) -> None:
    _, session_id = await _start(client, guest)
    result = await _finish(client, guest, session_id)
    assert result["week"]["done"] == 0
    assert result["offer_reminder"] is False


async def test_weeks_follow_the_phones_time_zone(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    """00:30 on Monday in Karachi is still Sunday evening in UTC: this week in Karachi,
    last week in UTC."""
    await _train(client, guest)
    now = await db_session.scalar(select(func.now()))
    assert now is not None
    karachi = ZoneInfo("Asia/Karachi")
    today = now.astimezone(karachi).date()
    monday = today - timedelta(days=today.weekday())
    just_after_midnight = datetime.combine(monday, time(0, 0, 30), tzinfo=karachi)
    await db_session.execute(
        update(WorkoutSession).values(
            started_at=just_after_midnight - timedelta(minutes=40), finished_at=just_after_midnight
        )
    )
    await db_session.flush()

    await client.patch(ME, json={"time_zone": "Asia/Karachi"}, headers=guest)
    there = (await client.get(WEEK, headers=guest)).json()
    await client.patch(ME, json={"time_zone": "UTC"}, headers=guest)
    utc = (await client.get(WEEK, headers=guest)).json()

    assert (there["week_start"], there["done"]) == (monday.isoformat(), 1)
    assert utc["done"] == 0


# --- the time zone and the reminder (PATCH /me) --------------------------------------------


async def test_the_time_zone_is_kept(client: AsyncClient, guest: Headers) -> None:
    saved = await client.patch(ME, json={"time_zone": "Asia/Karachi"}, headers=guest)
    assert saved.json()["time_zone"] == "Asia/Karachi"
    for wrong in ("Mars/Olympus", None, "../etc"):
        response = await client.patch(ME, json={"time_zone": wrong}, headers=guest)
        assert response.status_code == 422, wrong


async def test_a_reminder_is_set_changed_and_turned_off(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    plan_before = (await client.get("/api/v1/plans/current", headers=guest)).json()["id"]

    on = await client.patch(
        ME, json={"reminder": {"at": "18:30:45", "days": [4, 0, 2]}}, headers=guest
    )
    assert on.json()["reminder"] == {"at": "18:30:00", "days": [0, 2, 4]}
    assert (await client.get(ME, headers=guest)).json()["reminder"] == on.json()["reminder"]
    off = await client.patch(ME, json={"reminder": None}, headers=guest)
    assert off.json()["reminder"] is None
    again = await client.patch(ME, json={"reminder": None}, headers=guest)  # already off
    assert again.status_code == 200

    names = list(await db_session.scalars(select(Event.name).order_by(Event.at)))
    assert names.count(EventName.REMINDER_SET) == 1
    assert names.count(EventName.REMINDER_OFF) == 1  # turning off twice records it once
    props = await db_session.scalar(select(Event.props).where(Event.name == EventName.REMINDER_SET))
    assert props == {"days": 3, "hour": 18}
    # A setting, not an answer: the plan stays the same.
    assert (await client.get("/api/v1/plans/current", headers=guest)).json()["id"] == plan_before


@pytest.mark.parametrize("days", [[], [7], [-1], [1, 1], list(range(8))])
async def test_reminder_days_are_checked(
    client: AsyncClient, guest: Headers, days: list[int]
) -> None:
    response = await client.patch(
        ME, json={"reminder": {"at": "07:00", "days": days}}, headers=guest
    )
    assert response.status_code == 422


async def test_the_first_trained_workout_offers_a_reminder_once(
    client: AsyncClient, guest: Headers
) -> None:
    first = await _train(client, guest)
    second = await _train(client, guest)
    assert (first["offer_reminder"], second["offer_reminder"]) == (True, False)


async def test_no_reminder_offer_when_one_is_set(client: AsyncClient, guest: Headers) -> None:
    await client.patch(ME, json={"reminder": {"at": "07:00", "days": [1]}}, headers=guest)
    assert (await _train(client, guest))["offer_reminder"] is False


# --- new bests ---------------------------------------------------------------------------


async def _same_move_next(db: AsyncSession, row: Json, as_row: Json) -> None:
    """Make `row` (in the next workout) the same move as `as_row` (done before)."""
    await db.execute(
        update(PlannedWorkoutExercise)
        .where(PlannedWorkoutExercise.id == row["id"])
        .values(exercise_id=as_row["exercise"]["id"])
    )
    await db.flush()


async def test_more_reps_than_ever_before_is_a_new_best(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    first, first_id = await _start(client, guest)
    done_before = _main(first)
    await _tick(client, guest, first_id, done_before, reps=8)
    assert (await _finish(client, guest, first_id))["new_bests"] == []  # first time ever

    second, second_id = await _start(client, guest)
    again = _main(second)
    await _same_move_next(db_session, again, done_before)
    # A warm-up set of the same move doesn't count, however many reps.
    warm_up = second["warm_up"][0]
    await _same_move_next(db_session, warm_up, done_before)
    await _tick(client, guest, second_id, warm_up, reps=50)
    await _tick(client, guest, second_id, again, reps=11)
    result = await _finish(client, guest, second_id)

    [best] = result["new_bests"]
    assert best["exercise"]["id"] == done_before["exercise"]["id"]
    assert (best["kind"], best["value"], best["previous"]) == ("reps", 11, 8)


async def test_the_same_as_before_is_not_a_new_best(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    first, first_id = await _start(client, guest)
    done_before = _main(first)
    await _tick(client, guest, first_id, done_before, reps=8)
    await _finish(client, guest, first_id)

    second, second_id = await _start(client, guest)
    again = _main(second)
    await _same_move_next(db_session, again, done_before)
    await _tick(client, guest, second_id, again, reps=8)
    assert (await _finish(client, guest, second_id))["new_bests"] == []


async def test_a_heavier_weight_is_a_new_best(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    first, first_id = await _start(client, guest)
    done_before = _main(first)
    await _tick(client, guest, first_id, done_before, reps=8, weight_kg=10)
    await _finish(client, guest, first_id)

    second, second_id = await _start(client, guest)
    again = _main(second)
    await _same_move_next(db_session, again, done_before)
    await _tick(client, guest, second_id, again, reps=6, weight_kg=12.5)

    [best] = (await _finish(client, guest, second_id))["new_bests"]
    assert (best["kind"], best["value"], best["previous"]) == ("weight", 12.5, 10)
