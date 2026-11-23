"""Swapping exercises through the API (ADR 0020): "this hurts" (for good), "show another"
(today only), mid-workout swaps, where it hurts, bringing it back. Real library."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, SwappedOutExercise
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
SWAPPED = "/api/v1/me/swapped-out"
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
    "minutes_per_session": 45,
}
LIBRARY = {e.slug: e for e in load_library().exercises}

type Headers = dict[str, str]
type Json = dict[str, Any]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert (await client.put("/api/v1/me/profile", json=GYM, headers=headers)).is_success
    assert (await client.post("/api/v1/me/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post(PLANS, headers=headers)).status_code == 201
    return headers


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


async def _workout(client: AsyncClient, headers: Headers, workout_id: str) -> Json:
    return dict((await client.get(f"/api/v1/workouts/{workout_id}", headers=headers)).json())


def _rows(workout: Json) -> list[Json]:
    return [*workout["warm_up"], *workout["main"], *workout["finisher"], *workout["cool_down"]]


async def _swap(
    client: AsyncClient, headers: Headers, workout: Json, row: Json, reason: str = "hurts"
) -> Response:
    url = f"/api/v1/workouts/{workout['id']}/exercises/{row['id']}/swap"
    body = {"exercise_id": row["exercise"]["id"], "reason": reason}
    return await client.post(url, json=body, headers=headers)


async def _pending(client: AsyncClient, headers: Headers, but: str | None = None) -> list[Json]:
    plan = (await client.get(CURRENT, headers=headers)).json()
    return [
        await _workout(client, headers, w["id"])
        for w in plan["workouts"]
        if w["status"] == "pending" and w["id"] != but
    ]


def _exercise_ids(workouts: list[Json]) -> set[str]:
    return {r["exercise"]["id"] for w in workouts for r in _rows(w)}


async def _past_the_test(client: AsyncClient, headers: Headers) -> Json:
    """Finish the strength test (nothing logged) so the next workout is an ordinary one."""
    workout = await _next(client, headers)
    session = (await client.post("/api/v1/sessions", json={"workout_id": workout["id"]},
                                 headers=headers)).json()  # fmt: skip
    await client.post(f"/api/v1/sessions/{session['id']}/finish", json={}, headers=headers)
    return await _next(client, headers)


# --- this hurts -----------------------------------------------------------------------------


async def test_this_hurts_swaps_today_and_removes_it_for_good(
    client: AsyncClient, guest: Headers
) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["main"][0]
    painful = row["exercise"]

    response = await _swap(client, guest, workout, row)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["swapped_out"]["id"] == painful["id"] and result["left_out"] is False
    today = result["workout"]
    same_row = next(r for r in today["main"] if r["id"] == row["id"])
    assert same_row["exercise"]["id"] == result["swapped_in"]["id"] != painful["id"]
    assert (same_row["sets"], same_row["reps_min"]) == (row["sets"], row["reps_min"])
    assert result["swapped_in"]["difficulty"] <= painful["difficulty"] + 1
    assert painful["id"] not in _exercise_ids(await _pending(client, guest))
    listed = (await client.get(SWAPPED, headers=guest)).json()
    assert [s["exercise"]["id"] for s in listed] == [painful["id"]]


async def test_a_swapped_out_exercise_stays_out_of_the_next_block(
    client: AsyncClient, guest: Headers
) -> None:
    workout = await _past_the_test(client, guest)
    painful = workout["main"][0]["exercise"]
    await _swap(client, guest, workout, workout["main"][0])
    for w in await _pending(client, guest):
        await client.post(f"/api/v1/workouts/{w['id']}/skip", headers=guest)

    await client.post(PLANS, headers=guest)

    assert painful["id"] not in _exercise_ids(await _pending(client, guest))


async def test_any_part_can_be_swapped(client: AsyncClient, guest: Headers) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["warm_up"][0]

    response = await _swap(client, guest, workout, row)

    assert response.status_code == 200, response.text
    swapped_in = response.json()["swapped_in"]
    assert swapped_in is not None
    assert (
        LIBRARY[swapped_in["slug"]].movement_slot == LIBRARY[row["exercise"]["slug"]].movement_slot
    )


async def test_swapping_a_strength_test_move_gives_it_an_ordinary_target(
    client: AsyncClient, guest: Headers
) -> None:
    workout = await _next(client, guest)
    row = next(r for r in workout["main"] if r["is_test"])

    result = (await _swap(client, guest, workout, row)).json()

    swapped = next(r for r in result["workout"]["main"] if r["id"] == row["id"])
    assert swapped["is_test"] is False
    assert swapped["reps_min"] is not None or swapped["seconds"] is not None


# --- mid-workout ---------------------------------------------------------------------------------


async def test_mid_workout_the_stand_in_asks_only_for_the_sets_left(
    client: AsyncClient, guest: Headers
) -> None:
    workout = await _past_the_test(client, guest)
    row = next(r for r in workout["main"] if r["sets"] >= 3)
    session = (await client.post("/api/v1/sessions", json={"workout_id": workout["id"]},
                                 headers=guest)).json()  # fmt: skip
    for number in (1, 2):
        url = f"/api/v1/sessions/{session['id']}/sets/{row['id']}/{number}"
        await client.put(url, json={"reps": 8, "weight_kg": 20}, headers=guest)

    result = (await _swap(client, guest, workout, row)).json()

    main = result["workout"]["main"]
    at = next(i for i, r in enumerate(main) if r["id"] == row["id"])
    old, new = main[at], main[at + 1]
    assert old["swapped_out"] is True and old["sets"] == 2
    assert old["exercise"]["id"] == row["exercise"]["id"]  # its sets stay with it
    assert new["exercise"]["id"] == result["swapped_in"]["id"]
    assert new["sets"] == row["sets"] - 2 and new["swapped_out"] is False
    assert [r["id"] for r in main[:at]] == [r["id"] for r in workout["main"][:at]]
    current = (await client.get("/api/v1/sessions/current", headers=guest)).json()
    assert len(current["sets"]) == 2
    finish = await client.post(f"/api/v1/sessions/{session['id']}/finish", json={}, headers=guest)
    assert finish.status_code == 200


async def test_a_started_workout_is_never_rebuilt(client: AsyncClient, guest: Headers) -> None:
    workout = await _past_the_test(client, guest)
    await client.post("/api/v1/sessions", json={"workout_id": workout["id"]}, headers=guest)
    await _swap(client, guest, workout, workout["main"][0])
    painful = workout["main"][0]["exercise"]["id"]

    await client.delete(f"{SWAPPED}/{painful}", headers=guest)

    after = await _workout(client, guest, workout["id"])
    assert [r["id"] for r in _rows(after)] == [r["id"] for r in _rows(workout)]


async def test_a_double_tap_changes_nothing_the_second_time(
    client: AsyncClient, guest: Headers
) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["main"][0]
    await _swap(client, guest, workout, row)

    again = await _swap(client, guest, workout, row)

    assert again.status_code == 409
    assert again.json()["code"] == "exercise_changed"
    assert len((await client.get(SWAPPED, headers=guest)).json()) == 1


async def test_only_the_next_workout_can_be_swapped(client: AsyncClient, guest: Headers) -> None:
    later = (await _pending(client, guest))[2]

    response = await _swap(client, guest, later, later["main"][0])

    assert response.status_code == 409
    assert response.json()["code"] == "not_next_workout"


# --- show another --------------------------------------------------------------------------


async def test_show_another_is_for_today_only(client: AsyncClient, guest: Headers) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["main"][0]
    before = await _pending(client, guest, but=workout["id"])

    first = (await _swap(client, guest, workout, row, "another")).json()
    moved = next(r for r in first["workout"]["main"] if r["id"] == row["id"])
    second = (await _swap(client, guest, first["workout"], moved, "another")).json()

    shown = {row["exercise"]["id"], first["swapped_in"]["id"], second["swapped_in"]["id"]}
    assert len(shown) == 3  # walks on, doesn't bounce back
    assert (await client.get(SWAPPED, headers=guest)).json() == []
    after = await _pending(client, guest, but=workout["id"])
    assert _exercise_ids(after) == _exercise_ids(before)  # later workouts untouched


# --- nothing left ---------------------------------------------------------------------------


async def _ban_all_but(
    db_session: AsyncSession, client: AsyncClient, headers: Headers, keep: Json
) -> None:
    owner = uuid.UUID((await client.get("/api/v1/me", headers=headers)).json()["id"])
    movement = LIBRARY[keep["slug"]].movement_slot
    others = await db_session.scalars(
        select(Exercise.id).where(Exercise.movement_slot == movement, Exercise.slug != keep["slug"])
    )
    db_session.add_all(SwappedOutExercise(user_id=owner, exercise_id=i) for i in others)
    await db_session.flush()


async def test_nothing_safe_left_leaves_the_slot_out(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["main"][-1]
    await _ban_all_but(db_session, client, guest, row["exercise"])

    result = (await _swap(client, guest, workout, row)).json()

    assert result["left_out"] is True and result["swapped_in"] is None
    assert row["id"] not in {r["id"] for r in result["workout"]["main"]}


async def test_show_another_with_nothing_else_is_refused(
    client: AsyncClient, guest: Headers, db_session: AsyncSession
) -> None:
    workout = await _past_the_test(client, guest)
    row = workout["main"][-1]
    await _ban_all_but(db_session, client, guest, row["exercise"])

    response = await _swap(client, guest, workout, row, "another")

    assert response.status_code == 409
    assert response.json()["code"] == "no_other_exercise"


# --- where it hurts, and bringing it back ------------------------------------------------------


@pytest.mark.parametrize(("area", "suggested"), [("knees", "knees"), ("other", None)])
async def test_where_it_hurts_may_suggest_a_limit(
    client: AsyncClient, guest: Headers, area: str, suggested: str | None
) -> None:
    workout = await _past_the_test(client, guest)
    painful = workout["main"][0]["exercise"]["id"]
    await _swap(client, guest, workout, workout["main"][0])

    response = await client.patch(f"{SWAPPED}/{painful}", json={"body_area": area}, headers=guest)

    assert response.status_code == 200
    assert response.json()["body_area"] == area
    assert response.json()["suggest_limit"] == suggested


async def test_no_limit_suggested_when_it_is_already_one(
    client: AsyncClient, guest: Headers
) -> None:
    await client.put("/api/v1/me/profile", json=GYM | {"limits": ["back"]}, headers=guest)
    workout = await _past_the_test(client, guest)
    painful = workout["main"][0]["exercise"]["id"]
    await _swap(client, guest, workout, workout["main"][0])

    response = await client.patch(f"{SWAPPED}/{painful}", json={"body_area": "back"}, headers=guest)

    assert response.json()["suggest_limit"] is None


async def test_bring_it_back_restores_the_plan(client: AsyncClient, guest: Headers) -> None:
    workout = await _past_the_test(client, guest)
    before = await _pending(client, guest, but=workout["id"])
    painful = workout["main"][0]["exercise"]["id"]
    await _swap(client, guest, workout, workout["main"][0])

    response = await client.delete(f"{SWAPPED}/{painful}", headers=guest)

    assert response.status_code == 204
    assert (await client.get(SWAPPED, headers=guest)).json() == []
    after = await _pending(client, guest, but=workout["id"])
    assert [[r["exercise"]["id"] for r in _rows(w)] for w in after] == [
        [r["exercise"]["id"] for r in _rows(w)] for w in before
    ]


async def test_unknown_swaps_are_not_found(client: AsyncClient, guest: Headers) -> None:
    nobody = uuid.uuid4()

    assert (await client.delete(f"{SWAPPED}/{nobody}", headers=guest)).status_code == 404
    patch = await client.patch(f"{SWAPPED}/{nobody}", json={"body_area": "back"}, headers=guest)
    assert patch.status_code == 404
