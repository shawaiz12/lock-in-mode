"""Protect your progress (ADR 0026) through the API: guests are offered sign-in on the
finish screen of their 3rd and 10th finished workout and their first finished block, once
each; milestones without a finish screen pass; the summary matches the database; linked
accounts get nothing. Real library.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Event,
    Exercise,
    ExerciseTarget,
    MovementRung,
    SetLog,
    SwappedOutExercise,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import EventName
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

type MakeIdToken = Callable[..., str]
type Headers = dict[str, str]
type Json = dict[str, Any]

ME = "/api/v1/me"
PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
SESSIONS = "/api/v1/sessions"
ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
HOME: Json = {
    "goal": "build_muscle",
    "level": "beginner",
    "location": "home",
    "days_per_week": 3,
    "minutes_per_session": 30,
}


@pytest.fixture
async def library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


async def _guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _plan(
    client: AsyncClient, headers: Headers, answers: Json = HOME, safety: Json = ALL_NO
) -> None:
    assert (await client.put(f"{ME}/profile", json=answers, headers=headers)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=safety, headers=headers)).is_success
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text


async def _current(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(CURRENT, headers=headers)).json())


async def _start(
    client: AsyncClient, headers: Headers, workout_id: str | None = None
) -> tuple[Json, str]:
    """Start the next workout (or the given one) and tick one set of its first main
    exercise."""
    if workout_id is None:
        workout = (await client.get(f"{CURRENT}/next", headers=headers)).json()
    else:
        workout = (await client.get(f"/api/v1/workouts/{workout_id}", headers=headers)).json()
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    row = next(r for r in workout["main"] if not r["swapped_out"])
    values = {"seconds": 20} if row["seconds"] else {"reps": 10}
    url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
    assert (await client.put(url, json=values, headers=headers)).status_code == 200
    return workout, session_id


async def _do(client: AsyncClient, headers: Headers, workout_id: str | None = None) -> Json:
    """Do the next workout (or the given one) and return the finish screen."""
    _, session_id = await _start(client, headers, workout_id)
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert result.status_code == 200, result.text
    return dict(result.json())


async def _skip_all_but_last(client: AsyncClient, headers: Headers) -> None:
    pending = [w for w in (await _current(client, headers))["workouts"] if w["status"] == "pending"]
    for workout in pending[:-1]:
        response = await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
        assert response.status_code == 200, response.text


async def _offers(db: AsyncSession) -> list[Json]:
    rows = await db.scalars(
        select(Event)
        .where(Event.name == EventName.SIGN_IN_OFFERED)
        .order_by(Event.at)
        .execution_options(populate_existing=True)
    )
    return [dict(e.props) for e in rows]


def _milestones(results: list[Json]) -> dict[int, str]:
    """Finish number → milestone, for the finishes that carried an offer."""
    return {
        n: r["sign_in_offer"]["milestone"]
        for n, r in enumerate(results, start=1)
        if r["sign_in_offer"] is not None
    }


# --- when it's offered --------------------------------------------------------------------


async def test_offered_after_workouts_3_and_10_only(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    assert len((await _current(client, headers))["workouts"]) > 11  # no block end here

    results = [await _do(client, headers) for _ in range(11)]

    assert _milestones(results) == {3: "workout_3", 10: "workout_10"}
    assert results[2]["sign_in_offer"]["summary"]["workouts_finished"] == 3
    assert results[9]["sign_in_offer"]["summary"]["workouts_finished"] == 10
    assert await _offers(db_session) == [
        {"milestone": "workout_3", "number": 3},
        {"milestone": "workout_10", "number": 10},
    ]


async def test_offered_at_the_first_finished_block_but_not_the_second(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    await _skip_all_but_last(client, headers)

    last = await _do(client, headers)  # their 2nd finished workout ends block 1

    assert last["block_complete"] is True
    assert last["sign_in_offer"]["milestone"] == "first_block"
    assert last["sign_in_offer"]["summary"]["workouts_finished"] == 2

    assert (await client.post(PLANS, headers=headers)).status_code == 201
    await _skip_all_but_last(client, headers)
    block_2_end = await _do(client, headers)  # their 3rd: workout 3 is still offered

    assert block_2_end["block_complete"] is True
    assert block_2_end["sign_in_offer"]["milestone"] == "workout_3"
    assert [o["milestone"] for o in await _offers(db_session)] == ["first_block", "workout_3"]


async def test_two_milestones_on_one_finish_are_one_offer(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    for _ in range(9):
        await _do(client, headers)
    await _skip_all_but_last(client, headers)

    tenth = await _do(client, headers)

    assert tenth["block_complete"] is True
    assert tenth["sign_in_offer"]["milestone"] == "first_block"
    assert (await _offers(db_session))[-1] == {"milestone": "first_block", "number": 10}
    assert len(await _offers(db_session)) == 2  # workout 3, then this one


async def test_workout_3_closed_automatically_passes_without_an_offer(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    await _do(client, headers)
    third, _ = await _start(client, headers)  # never finished on screen
    pending = [w for w in (await _current(client, headers))["workouts"] if w["status"] == "pending"]
    following = pending[[w["id"] for w in pending].index(third["id"]) + 1]

    fourth = await _do(client, headers, following["id"])  # starting it closes workout 3

    assert fourth["sign_in_offer"] is None
    assert await _offers(db_session) == []
    summary = (await client.get(ME, headers=headers)).json()["progress_summary"]
    assert summary["workouts_finished"] == 4  # the card still shows it all


async def test_a_first_block_ended_by_a_skip_passes_and_the_next_block_isnt_first(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _skip_all_but_last(client, headers)
    last = (await _current(client, headers))["workouts"][-1]
    response = await client.post(f"/api/v1/workouts/{last['id']}/skip", headers=headers)
    assert response.json()["block_complete"] is True

    assert (await client.post(PLANS, headers=headers)).status_code == 201
    await _skip_all_but_last(client, headers)
    end = await _do(client, headers)

    assert end["block_complete"] is True
    assert end["sign_in_offer"] is None
    assert await _offers(db_session) == []


async def test_a_complete_block_replaced_by_new_answers_is_not_offered_twice(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _skip_all_but_last(client, headers)
    assert (await _do(client, headers))["sign_in_offer"]["milestone"] == "first_block"

    changed = {**HOME, "days_per_week": 2}
    assert (await client.put(f"{ME}/profile", json=changed, headers=headers)).is_success
    await _skip_all_but_last(client, headers)
    end = await _do(client, headers)

    assert end["block_complete"] is True
    assert end["sign_in_offer"] is None
    assert len(await _offers(db_session)) == 1


async def test_a_block_replaced_half_way_doesnt_count_as_finished(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    changed = {**HOME, "days_per_week": 2}
    assert (await client.put(f"{ME}/profile", json=changed, headers=headers)).is_success
    await _skip_all_but_last(client, headers)

    end = await _do(client, headers)

    assert end["block_complete"] is True
    assert end["sign_in_offer"]["milestone"] == "first_block"


async def test_low_intensity_guests_are_offered_too(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers, safety={**ALL_NO, "heart_condition": True})

    results = [await _do(client, headers) for _ in range(3)]

    assert _milestones(results) == {3: "workout_3"}


async def test_linked_accounts_are_never_offered(
    client: AsyncClient, db_session: AsyncSession, library: None, google_id_token: MakeIdToken
) -> None:
    guest = await _guest(client)
    await _plan(client, guest)
    await _do(client, guest)
    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g")}, headers=guest
    )
    assert link.status_code == 200
    assert link.json()["progress_summary"] is None

    results = [await _do(client, guest) for _ in range(3)]

    assert _milestones(results) == {}
    assert await _offers(db_session) == []
    assert (await client.get(ME, headers=guest)).json()["progress_summary"] is None

    tokens = (
        await client.post("/api/v1/auth/google", json={"id_token": google_id_token("new")})
    ).json()
    google = {"Authorization": f"Bearer {tokens['access_token']}"}
    await _plan(client, google)
    assert _milestones([await _do(client, google) for _ in range(3)]) == {}


async def test_the_offer_is_shown_with_usage_data_off_but_not_recorded(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await client.patch(ME, json={"share_usage_data": False}, headers=headers)
    await _plan(client, headers)

    results = [await _do(client, headers) for _ in range(3)]

    assert _milestones(results) == {3: "workout_3"}
    assert await _offers(db_session) == []


# --- the summary --------------------------------------------------------------------------


async def test_a_new_guest_has_an_empty_summary(client: AsyncClient) -> None:
    headers = await _guest(client)

    summary = (await client.get(ME, headers=headers)).json()["progress_summary"]

    assert summary == {
        "workouts_finished": 0,
        "sets_logged": 0,
        "exercises_with_own_numbers": 0,
        "exercises_left_out": 0,
        "strength_test_moves": 0,
        "lines": [],
    }


async def test_the_summary_matches_the_database(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    other = await _guest(client)  # someone else's training doesn't count
    await _plan(client, other)
    await _do(client, other)

    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    await _do(client, headers)
    workout, _ = await _start(client, headers)  # an open session's sets count too
    row = next(r for r in workout["main"][1:] if not r["swapped_out"])
    swap = await client.post(
        f"/api/v1/workouts/{workout['id']}/exercises/{row['id']}/swap",
        json={"exercise_id": row["exercise"]["id"], "reason": "hurts"},
        headers=headers,
    )
    assert swap.status_code == 200, swap.text
    user_id = (await client.get(ME, headers=headers)).json()["id"]
    # Saved numbers: one tuned, one that only counts a missed session (not "own numbers").
    tuned, short_only = (
        await db_session.scalars(
            select(Exercise.id)
            .where(~Exercise.id.in_(select(ExerciseTarget.exercise_id)))
            .order_by(Exercise.slug)
            .limit(2)
        )
    ).all()
    db_session.add(ExerciseTarget(user_id=user_id, exercise_id=tuned, reps_bonus=1))
    db_session.add(ExerciseTarget(user_id=user_id, exercise_id=short_only, short_runs=1))
    await db_session.flush()
    me = (await client.get(ME, headers=headers)).json()

    async def count(model: Any, *where: Any) -> int:
        return await db_session.scalar(select(func.count()).select_from(model).where(*where)) or 0

    expected = {
        "workouts_finished": await count(
            WorkoutSession,
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
        ),
        "sets_logged": await db_session.scalar(
            select(func.count())
            .select_from(SetLog)
            .join(WorkoutSession)
            .where(WorkoutSession.user_id == user_id)
        )
        or 0,
        "exercises_with_own_numbers": sum(
            1
            for t in await db_session.scalars(
                select(ExerciseTarget).where(ExerciseTarget.user_id == user_id)
            )
            if (t.weight_kg, t.set_change, t.seconds, t.reps_bonus) != (None, 0, None, 0)
        ),
        "exercises_left_out": await count(
            SwappedOutExercise, SwappedOutExercise.user_id == user_id
        ),
        "strength_test_moves": await count(MovementRung, MovementRung.user_id == user_id),
    }
    summary = me["progress_summary"]
    assert {k: v for k, v in summary.items() if k != "lines"} == expected
    assert expected["workouts_finished"] == 2
    assert expected["sets_logged"] == 3
    assert expected["exercises_left_out"] == 1
    assert expected["exercises_with_own_numbers"] >= 1
    rows = await count(ExerciseTarget, ExerciseTarget.user_id == user_id)
    assert expected["exercises_with_own_numbers"] < rows  # the short-runs row isn't counted
    assert all(n > 0 for n in expected.values()), expected
    assert summary["lines"][:2] == ["2 workouts finished", "3 sets logged"]
    assert summary["lines"][3] == "1 exercise left out because it hurt"
    assert len(summary["lines"]) == 5

    patched = await client.patch(ME, json={"display_name": "Sam"}, headers=headers)
    assert patched.json()["progress_summary"] == summary
