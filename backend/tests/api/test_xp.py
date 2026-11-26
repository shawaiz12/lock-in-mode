"""XP and the Lock In level through the API (ADR 0035).

The Locked-in bonus is off in every test (conftest `_no_lucky_bonus`) unless a test turns
it on with the `lucky` fixture, so totals are exact.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api import xp_backfill
from lock_in_mode_api.models import (
    Comeback,
    Event,
    PlannedWorkoutExercise,
    SetLog,
    WorkoutSession,
    XpEvent,
)
from lock_in_mode_api.models.enums import EventName
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training import xp as xp_rules

ME = "/api/v1/me"
XP = "/api/v1/me/xp"
SESSIONS = "/api/v1/sessions"
NEXT = "/api/v1/plans/current/next"
PARTS = ("warm_up", "main", "finisher", "cool_down")
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
    assert (await client.put(f"{ME}/profile", json=HOME, headers=headers)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post("/api/v1/plans", headers=headers)).status_code == 201
    return headers


@pytest.fixture
def lucky(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every roll of the Locked-in bonus comes up."""
    monkeypatch.setattr(xp_rules, "lucky", lambda _session_id: True)


def _rows(workout: Json) -> list[Json]:
    return [row for part in PARTS for row in workout[part] if not row["swapped_out"]]


def _values(row: Json) -> Json:
    return {"seconds": row["seconds"]} if row["seconds"] else {"reps": 10}


async def _start(client: AsyncClient, headers: Headers) -> tuple[Json, str]:
    workout = dict((await client.get(NEXT, headers=headers)).json())
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert started.status_code in (200, 201), started.text
    return workout, str(started.json()["id"])


async def _tick_sets(
    client: AsyncClient, headers: Headers, session_id: str, rows: list[Json], n: int
) -> None:
    """Tick the first `n` sets, row by row."""
    for row in rows:
        for number in range(1, row["sets"] + 1):
            if n <= 0:
                return
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{number}"
            assert (await client.put(url, json=_values(row), headers=headers)).status_code == 200
            n -= 1


async def _finish(client: AsyncClient, headers: Headers, session_id: str) -> Json:
    response = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _train(client: AsyncClient, headers: Headers, share: float = 1.0) -> Json:
    """Do the next workout, ticking `share` of all its sets. Returns the finish result."""
    workout, session_id = await _start(client, headers)
    rows = _rows(workout)
    total = sum(row["sets"] for row in rows)
    await _tick_sets(client, headers, session_id, rows, round(total * share))
    return await _finish(client, headers, session_id)


def _items(result: Json) -> list[tuple[str, int]]:
    return [(item["source"], item["amount"]) for item in result["xp"]["items"]]


async def _xp(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(XP, headers=headers)).json())


# --- earning ---------------------------------------------------------------------------


async def test_workout_1_earns_100_and_reaches_level_2(client: AsyncClient, guest: Headers) -> None:
    assert await _xp(client, guest) == {"total": 0, "level": 1, "xp_into": 0, "xp_needed": 100}

    result = await _train(client, guest)

    assert _items(result) == [("workout", 100)]
    xp = result["xp"]
    assert (xp["gained"], xp["bonus"], xp["capped"]) == (100, False, False)
    assert (xp["before"]["level"], xp["after"]["level"]) == (1, 2)
    assert await _xp(client, guest) == {"total": 100, "level": 2, "xp_into": 0, "xp_needed": 200}


async def test_half_a_workout_earns_half(client: AsyncClient, guest: Headers) -> None:
    result = await _train(client, guest, share=0.5)
    [(source, amount)] = _items(result)
    assert source == "workout"
    assert 45 <= amount <= 55  # half the sets, rounded to whole sets


async def test_nothing_ticked_earns_nothing(client: AsyncClient, guest: Headers) -> None:
    _, session_id = await _start(client, guest)
    result = await _finish(client, guest, session_id)
    assert result["xp"] is None
    assert (await _xp(client, guest))["total"] == 0


async def test_a_kept_week_pays_once(client: AsyncClient, guest: Headers) -> None:
    await _train(client, guest)
    second = await _train(client, guest)
    third = await _train(client, guest)

    assert _items(second) == [("workout", 100), ("week", 150)]
    assert _items(third) == [("workout", 100)]
    assert (await _xp(client, guest))["total"] == 450


async def test_a_level_up_is_recorded(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train(client, guest)  # level 2
    await _train(client, guest)  # 350: level 3
    levels = await db_session.scalars(
        select(Event.props["level"].as_integer()).where(Event.name == EventName.LEVEL_UP)
    )
    assert sorted(levels) == [2, 3]


# --- the Locked-in bonus -------------------------------------------------------------------


async def test_the_bonus_gives_the_workouts_xp_once_more_never_twice_in_a_row(
    client: AsyncClient, guest: Headers, lucky: None
) -> None:
    first = await _train(client, guest)
    second = await _train(client, guest)

    assert _items(first) == [("workout", 100), ("bonus", 100)]
    assert first["xp"]["bonus"] is True
    assert ("bonus", 100) not in _items(second)  # lucky again, but not twice in a row


# --- safety: no XP for over-training -------------------------------------------------------


async def test_only_days_a_week_plus_one_workouts_earn_xp(
    client: AsyncClient, guest: Headers
) -> None:
    for _ in range(4):  # 3 days a week + 1
        await _train(client, guest)
    fifth = await _train(client, guest)

    assert fifth["xp"]["items"] == []
    assert (fifth["xp"]["gained"], fifth["xp"]["capped"]) == (0, True)
    assert fifth["week"]["done"] == 5  # it still counts as training


# --- new bests and comebacks --------------------------------------------------------------


async def test_new_bests_earn_25_each(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    first, first_id = await _start(client, guest)
    move = next(row for row in first["main"] if not row["swapped_out"])
    await _tick_sets(client, guest, first_id, [move], 1)
    await _finish(client, guest, first_id)

    second, second_id = await _start(client, guest)
    again = next(row for row in second["main"] if not row["swapped_out"])
    await db_session.execute(
        update(PlannedWorkoutExercise)
        .where(PlannedWorkoutExercise.id == again["id"])
        .values(exercise_id=move["exercise"]["id"])
    )
    await db_session.flush()
    url = f"{SESSIONS}/{second_id}/sets/{again['id']}/1"
    body = {"seconds": 99} if again["seconds"] else {"reps": 30}
    assert (await client.put(url, json=body, headers=guest)).status_code == 200

    result = await _finish(client, guest, second_id)
    assert len(result["new_bests"]) == 1
    assert ("best", 25) in _items(result)


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


async def test_the_first_workout_back_after_a_break_earns_100_more(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train(client, guest)
    await _train(client, guest)
    await _away(db_session, 20)

    back = await _train(client, guest)
    after = await _train(client, guest)

    assert await db_session.scalar(select(func.count()).select_from(Comeback)) == 1
    assert ("comeback", 100) in _items(back)
    assert ("comeback", 100) not in _items(after)


# --- never twice, and the backfill --------------------------------------------------------


async def _forget_xp(db: AsyncSession) -> None:
    await db.execute(delete(XpEvent))
    await db.execute(delete(Event).where(Event.name == EventName.LEVEL_UP))
    await db.flush()


async def test_the_backfill_awards_the_past_once_without_bonuses_or_events(
    client: AsyncClient, guest: Headers, db_session: AsyncSession, lucky: None
) -> None:
    await _train(client, guest)
    await _train(client, guest)
    await _forget_xp(db_session)  # as if they had trained before XP existed

    looked_at = await xp_backfill.backfill(db_session)
    again = await xp_backfill.backfill(db_session)

    assert (looked_at, again) == (2, 0)
    assert (await _xp(client, guest))["total"] == 350  # 100 + 100 + 150 for the week
    sources = list(await db_session.scalars(select(XpEvent.source)))
    assert "bonus" not in sources
    assert (
        await db_session.scalar(select(func.count()).where(Event.name == EventName.LEVEL_UP)) == 0
    )


async def test_the_backfill_never_adds_to_xp_already_awarded(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train(client, guest)
    await _train(client, guest)

    assert await xp_backfill.backfill(db_session) == 0
    assert (await _xp(client, guest))["total"] == 350


async def test_bests_in_the_backfill_compare_with_earlier_workouts_only(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    """Workout A: 11 reps. Workout B, later: 8 reps of the same move. A was the first
    time (nothing earlier to beat) and B didn't beat A: no best at all. Compared with
    the later workout too, A would wrongly count as beating B's 8."""
    first, first_id = await _start(client, guest)
    move = next(row for row in first["main"] if not row["swapped_out"] and not row["seconds"])
    url = f"{SESSIONS}/{first_id}/sets/{move['id']}/1"
    assert (await client.put(url, json={"reps": 11}, headers=guest)).status_code == 200
    await _finish(client, guest, first_id)
    second, second_id = await _start(client, guest)
    again = next(row for row in second["main"] if not row["swapped_out"])
    await db_session.execute(
        update(PlannedWorkoutExercise)
        .where(PlannedWorkoutExercise.id == again["id"])
        .values(exercise_id=move["exercise"]["id"], seconds=None)
    )
    await db_session.flush()
    url = f"{SESSIONS}/{second_id}/sets/{again['id']}/1"
    assert (await client.put(url, json={"reps": 8}, headers=guest)).status_code == 200
    await _finish(client, guest, second_id)
    await _forget_xp(db_session)

    await xp_backfill.backfill(db_session)

    bests = await db_session.scalars(select(XpEvent.session_id).where(XpEvent.source == "best"))
    assert list(bests) == []


async def test_xp_is_erased_with_the_account(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    await _train(client, guest)
    assert (await client.delete(ME, headers=guest)).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(XpEvent)) == 0
