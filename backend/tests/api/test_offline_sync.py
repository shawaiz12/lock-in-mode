"""A workout done offline and sent later (ADR 0033): the phone's times are kept, in order.

The app records when each thing happened on the phone (start, every set, finish) and
sends those times when it syncs. The server keeps them, moved into order where a phone
clock is wrong: never before the plan existed or the last finished workout, a set never
before its workout started, a finish never before its last set, nothing after now.
A break (ADR 0021) is judged by when they really trained.

A test runs in one transaction, so the database's now() is the same all through it.
History is moved back in time (`_back`) to leave room for times in the past.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Plan, SetLog, WorkoutSession
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

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
LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)

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


async def _now(db: AsyncSession) -> datetime:
    now: datetime | None = await db.scalar(select(func.now()))
    assert now is not None
    return now


async def _back(db: AsyncSession, days: int) -> None:
    """Pretend the plan and everything trained so far happened `days` days earlier."""
    shift = timedelta(days=days)
    await db.execute(update(Plan).values(created_at=Plan.created_at - shift))
    await db.execute(update(SetLog).values(logged_at=SetLog.logged_at - shift))
    await db.execute(
        update(WorkoutSession).values(
            started_at=WorkoutSession.started_at - shift,
            finished_at=WorkoutSession.finished_at - shift,
        )
    )
    await db.flush()
    db.expire_all()


def _iso(at: datetime) -> str:
    return at.isoformat()


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(NEXT, headers=headers)).json())


def _first_row(workout: Json) -> Json:
    return next(row for row in workout["main"] if not row["swapped_out"])


def _values(row: Json) -> Json:
    return {"seconds": row["seconds"]} if row["seconds"] else {"reps": 10}


async def _start(client: AsyncClient, headers: Headers, workout: Json, at: datetime) -> Json:
    body = {"workout_id": workout["id"], "started_at": _iso(at)}
    response = await client.post(SESSIONS, json=body, headers=headers)
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


async def _tick(
    client: AsyncClient, headers: Headers, session_id: str, row: Json, n: int, at: datetime
) -> None:
    url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{n}"
    body = _values(row) | {"logged_at": _iso(at)}
    assert (await client.put(url, json=body, headers=headers)).status_code == 200


async def _finish(client: AsyncClient, headers: Headers, session_id: str, at: datetime) -> Json:
    body = {"feedback": "just_right", "finished_at": _iso(at)}
    response = await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _logged(db: AsyncSession, session_id: str) -> list[datetime]:
    rows = await db.scalars(
        select(SetLog.logged_at)
        .where(SetLog.session_id == session_id)
        .order_by(SetLog.set_number)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _train_online(client: AsyncClient, headers: Headers) -> None:
    """Do the next workout the way the app does online: no times sent."""
    workout = await _next(client, headers)
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    session_id = started.json()["id"]
    for row in workout["main"]:
        if not row["swapped_out"]:
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
            assert (await client.put(url, json=_values(row), headers=headers)).is_success
    finished = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert finished.is_success


# --- the phone's times are kept -----------------------------------------------------------


async def test_a_workout_done_offline_keeps_the_phones_times(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _back(db_session, 3)
    start = await _now(db_session) - timedelta(days=2)
    workout = await _next(client, guest)
    row = _first_row(workout)

    session = await _start(client, guest, workout, start)
    await _tick(client, guest, session["id"], row, 1, start + timedelta(minutes=5))
    await _tick(client, guest, session["id"], row, 2, start + timedelta(minutes=8))
    result = await _finish(client, guest, session["id"], start + timedelta(minutes=40))

    assert _at(session["started_at"]) == start
    assert await _logged(db_session, session["id"]) == [
        start + timedelta(minutes=5),
        start + timedelta(minutes=8),
    ]
    assert _at(result["finished_at"]) == start + timedelta(minutes=40)
    assert result["next_workout_id"] != workout["id"]  # the queue moved on as usual


async def test_ticking_a_set_again_takes_the_new_time(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _back(db_session, 3)
    start = await _now(db_session) - timedelta(days=2)
    workout = await _next(client, guest)
    row = _first_row(workout)
    session = await _start(client, guest, workout, start)

    await _tick(client, guest, session["id"], row, 1, start + timedelta(minutes=5))
    await _tick(client, guest, session["id"], row, 1, start + timedelta(minutes=9))

    assert await _logged(db_session, session["id"]) == [start + timedelta(minutes=9)]


# --- a wrong clock can't put things out of order ------------------------------------------


async def test_nothing_is_kept_in_the_future(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    now = await _now(db_session)
    later = now + timedelta(days=1)
    workout = await _next(client, guest)

    session = await _start(client, guest, workout, later)
    await _tick(client, guest, session["id"], _first_row(workout), 1, later)
    result = await _finish(client, guest, session["id"], later)

    assert _at(session["started_at"]) == now
    assert await _logged(db_session, session["id"]) == [now]
    assert _at(result["finished_at"]) == now


async def test_a_start_is_never_before_the_plan_existed(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _back(db_session, 3)
    made = await db_session.scalar(select(Plan.created_at))

    session = await _start(client, guest, await _next(client, guest), LONG_AGO)

    assert _at(session["started_at"]) == made


async def test_a_start_is_never_before_the_last_finished_workout(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train_online(client, guest)
    await _back(db_session, 3)
    last_finish = await db_session.scalar(select(func.max(WorkoutSession.finished_at)))

    session = await _start(client, guest, await _next(client, guest), LONG_AGO)

    assert _at(session["started_at"]) == last_finish


async def test_a_set_is_never_before_its_start_and_a_finish_never_before_its_last_set(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _back(db_session, 3)
    start = await _now(db_session) - timedelta(days=2)
    workout = await _next(client, guest)
    row = _first_row(workout)
    session = await _start(client, guest, workout, start)

    await _tick(client, guest, session["id"], row, 1, LONG_AGO)
    await _tick(client, guest, session["id"], row, 2, start + timedelta(minutes=10))
    result = await _finish(client, guest, session["id"], start + timedelta(minutes=5))

    assert await _logged(db_session, session["id"]) == [start, start + timedelta(minutes=10)]
    assert _at(result["finished_at"]) == start + timedelta(minutes=10)


async def test_continuing_keeps_the_first_start(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _back(db_session, 3)
    start = await _now(db_session) - timedelta(days=2)
    workout = await _next(client, guest)

    first = await _start(client, guest, workout, start)
    again = await _start(client, guest, workout, start + timedelta(hours=5))

    assert again["id"] == first["id"]
    assert _at(again["started_at"]) == start


async def test_times_without_a_time_zone_are_refused(client: AsyncClient, guest: Headers) -> None:
    workout = await _next(client, guest)
    naive = "2026-11-25T10:00:00"

    started = await client.post(
        SESSIONS, json={"workout_id": workout["id"], "started_at": naive}, headers=guest
    )
    session = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=guest)
    url = f"{SESSIONS}/{session.json()['id']}/sets/{_first_row(workout)['id']}/1"
    ticked = await client.put(url, json={"reps": 10, "logged_at": naive}, headers=guest)
    finished = await client.post(
        f"{SESSIONS}/{session.json()['id']}/finish", json={"finished_at": naive}, headers=guest
    )

    assert [started.status_code, ticked.status_code, finished.status_code] == [422, 422, 422]


# --- a break is judged by when they trained (ADR 0021) ------------------------------------


async def test_an_offline_workout_soon_after_the_last_one_is_not_a_comeback(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    """Trained 20 days ago, then offline 18 days ago, synced today: 2 days away, not 20."""
    await _train_online(client, guest)
    await _train_online(client, guest)
    await _back(db_session, 20)
    start = await _now(db_session) - timedelta(days=18)

    session = await _start(client, guest, await _next(client, guest), start)

    saved = await db_session.get(WorkoutSession, session["id"], populate_existing=True)
    assert saved is not None and saved.comeback_id is None


async def test_an_offline_workout_after_a_long_break_starts_the_comeback(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train_online(client, guest)
    await _train_online(client, guest)
    await _back(db_session, 20)
    start = await _now(db_session) - timedelta(days=1)

    session = await _start(client, guest, await _next(client, guest), start)

    saved = await db_session.get(WorkoutSession, session["id"], populate_existing=True)
    assert saved is not None and saved.comeback_id is not None and saved.comeback_week == 1
