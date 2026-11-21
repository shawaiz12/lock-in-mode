"""Plans and the "next workout" queue (ADR 0017), through the API with the real library."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Plan, PlannedWorkout
from lock_in_mode_api.models.enums import PlanEndReason, WorkoutStatus
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library

PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
NEXT = "/api/v1/plans/current/next"
PROFILE = "/api/v1/me/profile"
SAFETY = "/api/v1/me/safety-screen"

ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
# Beginner, home, no kit, 3 days: 3 full-body workouts a week, 15 in a block.
ANSWERS: dict[str, Any] = {
    "goal": "build_muscle",
    "level": "beginner",
    "location": "home",
    "days_per_week": 3,
    "minutes_per_session": 30,
}
STRENGTH = {"full_body", "upper", "lower", "push", "pull", "legs", "circuit"}

type Headers = dict[str, str]


@pytest.fixture(autouse=True)
async def _library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


@pytest.fixture
async def guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _onboard(client: AsyncClient, headers: Headers, **answers: Any) -> None:
    response = await client.put(PROFILE, json=ANSWERS | answers, headers=headers)
    assert response.status_code in (200, 201), response.text
    response = await client.post(SAFETY, json=ALL_NO, headers=headers)
    assert response.status_code == 200, response.text


@pytest.fixture
async def planned(client: AsyncClient, guest: Headers) -> dict[str, Any]:
    """A guest who onboarded and started their first plan. Returns the plan."""
    await _onboard(client, guest)
    response = await client.post(PLANS, headers=guest)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _skip(client: AsyncClient, headers: Headers, workout_id: str) -> Response:
    return await client.post(f"/api/v1/workouts/{workout_id}/skip", headers=headers)


async def _skip_all(client: AsyncClient, headers: Headers) -> dict[str, Any]:
    plan = (await client.get(CURRENT, headers=headers)).json()
    while plan["next_workout_id"] is not None:
        response = await _skip(client, headers, plan["next_workout_id"])
        assert response.status_code == 200, response.text
        plan = response.json()
    return dict(plan)


def _test_workouts(plan: dict[str, Any], details: list[dict[str, Any]]) -> list[int]:
    return [d["position"] for d in details if any(e["is_test"] for e in d["main"])]


async def _details(client: AsyncClient, headers: Headers, plan: dict[str, Any]) -> list[Any]:
    return [
        (await client.get(f"/api/v1/workouts/{w['id']}", headers=headers)).json()
        for w in plan["workouts"]
    ]


# --- starting a plan --------------------------------------------------------------------


async def test_no_plan_before_onboarding(client: AsyncClient, guest: Headers) -> None:
    response = await client.post(PLANS, headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "profile_not_found"


async def test_no_plan_before_the_safety_screen(client: AsyncClient, guest: Headers) -> None:
    await client.put(PROFILE, json=ANSWERS, headers=guest)

    response = await client.post(PLANS, headers=guest)

    assert response.status_code == 409
    assert response.json()["code"] == "safety_screen_required"


async def test_current_plan_is_not_found_until_one_is_started(
    client: AsyncClient, guest: Headers
) -> None:
    await _onboard(client, guest)

    for path in (CURRENT, NEXT):
        response = await client.get(path, headers=guest)
        assert response.status_code == 404
        assert response.json()["code"] == "plan_not_found"


async def test_first_plan_is_a_five_week_block_with_the_queue_at_the_start(
    planned: dict[str, Any],
) -> None:
    assert planned["block_number"] == 1
    assert planned["routine_kind"] == "full_body"
    assert planned["weeks"] == 5
    assert planned["reasons"]
    assert len(planned["weekdays"]) == 3
    workouts = planned["workouts"]
    assert len(workouts) == 15
    assert [w["position"] for w in workouts] == list(range(1, 16))
    assert [w["week"] for w in workouts] == [n for n in range(1, 6) for _ in range(3)]
    assert [w["recovery"] for w in workouts] == [False] * 12 + [True] * 3
    assert all(w["status"] == "pending" for w in workouts)
    assert planned["next_workout_id"] == workouts[0]["id"]
    assert planned["block_complete"] is False


async def test_first_workout_is_the_strength_test(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    details = await _details(client, guest, planned)

    assert _test_workouts(planned, details) == [1]
    tests = [e for e in details[0]["main"] if e["is_test"]]
    push_up = next(e for e in tests if e["exercise"]["slug"] == "push-up")
    assert push_up["reps_min"] is None  # open target: as many as you can
    assert push_up["practice_sets"] == 0


async def test_cannot_start_another_block_while_this_one_is_in_progress(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    response = await client.post(PLANS, headers=guest)

    assert response.status_code == 409
    assert response.json()["code"] == "plan_in_progress"


# --- reading -------------------------------------------------------------------------


async def test_next_workout_has_every_part_in_order(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    response = await client.get(NEXT, headers=guest)

    assert response.status_code == 200
    workout = response.json()
    assert workout["id"] == planned["next_workout_id"]
    assert workout["plan_id"] == planned["id"]
    assert workout["warm_up"] and workout["main"] and workout["cool_down"]
    assert workout["total_minutes"] <= 30
    first = workout["main"][0]
    assert set(first["exercise"]) == {"id", "slug", "name", "difficulty"}


async def test_plan_and_workouts_answer_304_when_unchanged(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    for path in (CURRENT, NEXT, f"/api/v1/workouts/{planned['next_workout_id']}"):
        first = await client.get(path, headers=guest)
        again = await client.get(path, headers=guest | {"If-None-Match": first.headers["ETag"]})
        assert again.status_code == 304, path


async def test_another_users_workout_is_not_found(
    client: AsyncClient, planned: dict[str, Any]
) -> None:
    stranger = (await client.post("/api/v1/auth/guest")).json()["access_token"]
    headers = {"Authorization": f"Bearer {stranger}"}
    workout_id = planned["next_workout_id"]

    for response in (
        await client.get(f"/api/v1/workouts/{workout_id}", headers=headers),
        await _skip(client, headers, workout_id),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


async def test_unknown_workout_is_not_found(client: AsyncClient, guest: Headers) -> None:
    response = await client.get(f"/api/v1/workouts/{uuid.uuid4()}", headers=guest)

    assert response.status_code == 404


# --- skipping ---------------------------------------------------------------------------


async def test_skipping_moves_the_queue_on(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    first, second = planned["workouts"][0], planned["workouts"][1]

    response = await _skip(client, guest, first["id"])

    assert response.status_code == 200
    plan = response.json()
    assert plan["workouts"][0]["status"] == "skipped"
    assert plan["next_workout_id"] == second["id"]


async def test_only_the_next_workout_can_be_skipped(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    first, third = planned["workouts"][0], planned["workouts"][2]
    await _skip(client, guest, first["id"])

    for workout_id in (third["id"], first["id"]):  # further down, and already skipped
        response = await _skip(client, guest, workout_id)
        assert response.status_code == 409
        assert response.json()["code"] == "not_next_workout"


async def test_skipping_the_strength_test_moves_it_to_the_next_strength_workout(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    await _skip(client, guest, planned["workouts"][0]["id"])

    # Beginners alternate Full body A and B. B has no test movements, so the test goes to
    # the next A (position 3). Workout 1 keeps its marks as history.
    details = await _details(client, guest, planned)
    assert _test_workouts(planned, details) == [1, 3]
    moved = [e for e in details[2]["main"] if e["is_test"]]
    assert {e["exercise"]["slug"] for e in moved} >= {"push-up", "bodyweight-squat"}


async def test_the_test_never_moves_into_the_recovery_week(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    for workout in planned["workouts"][:12]:  # every build-up workout, test included
        await _skip(client, guest, workout["id"])

    details = await _details(client, guest, planned)
    assert not any(_test_workouts(planned, details[12:]))


# --- the end of a block -------------------------------------------------------------------


async def test_finished_block_says_so_and_the_next_one_starts_on_request(
    client: AsyncClient, guest: Headers, planned: dict[str, Any], db_session: AsyncSession
) -> None:
    plan = await _skip_all(client, guest)
    assert plan["block_complete"] is True

    response = await client.get(NEXT, headers=guest)
    assert response.status_code == 404
    assert response.json()["code"] == "block_complete"

    response = await client.post(PLANS, headers=guest)
    assert response.status_code == 201
    second = response.json()
    assert second["block_number"] == 2
    assert second["id"] != planned["id"]
    old = await db_session.get(Plan, uuid.UUID(planned["id"]), populate_existing=True)
    assert old is not None and old.ended_at is not None
    assert old.end_reason == PlanEndReason.FINISHED


async def test_the_test_stays_until_a_test_workout_is_done(
    client: AsyncClient, guest: Headers, planned: dict[str, Any], db_session: AsyncSession
) -> None:
    # Skipped tests don't count: the next block has the test again.
    await _skip_all(client, guest)
    second = (await client.post(PLANS, headers=guest)).json()
    assert _test_workouts(second, await _details(client, guest, second)) == [1]

    # Finishing it (the sessions stage will do this) means no more tests.
    await db_session.execute(
        update(PlannedWorkout)
        .where(PlannedWorkout.id == uuid.UUID(second["workouts"][0]["id"]))
        .values(status=WorkoutStatus.DONE)
    )
    await _skip_all(client, guest)
    third = (await client.post(PLANS, headers=guest)).json()
    assert _test_workouts(third, await _details(client, guest, third)) == []


# --- changing the answers ----------------------------------------------------------------


async def test_changing_the_answers_starts_a_new_block_at_once(
    client: AsyncClient, guest: Headers, planned: dict[str, Any], db_session: AsyncSession
) -> None:
    await _skip(client, guest, planned["workouts"][0]["id"])

    response = await client.put(PROFILE, json=ANSWERS | {"days_per_week": 4}, headers=guest)
    assert response.status_code == 200

    plan = (await client.get(CURRENT, headers=guest)).json()
    assert plan["id"] != planned["id"]
    assert plan["block_number"] == 2
    assert plan["routine_kind"] == "full_body"
    assert len(plan["weekdays"]) == 4
    assert all(w["status"] == "pending" for w in plan["workouts"])
    old = await db_session.get(Plan, uuid.UUID(planned["id"]), populate_existing=True)
    assert old is not None and old.end_reason == PlanEndReason.ANSWERS_CHANGED


async def test_an_untouched_plan_is_rebuilt_in_place(
    client: AsyncClient, guest: Headers, planned: dict[str, Any], db_session: AsyncSession
) -> None:
    # Onboarding screen 13: "Shoulders with push day or leg day?" comes after the plan.
    await client.put(PROFILE, json=ANSWERS | {"shoulder_day": "legs"}, headers=guest)

    plan = (await client.get(CURRENT, headers=guest)).json()
    assert plan["id"] != planned["id"]
    assert plan["block_number"] == 1  # still the first block: nothing was trained
    assert await db_session.get(Plan, uuid.UUID(planned["id"])) is None


async def test_answers_the_plan_does_not_use_keep_the_plan(
    client: AsyncClient, guest: Headers, planned: dict[str, Any]
) -> None:
    await client.put(PROFILE, json=ANSWERS | {"obstacles": ["no_time"]}, headers=guest)
    await client.put(PROFILE, json=ANSWERS, headers=guest)  # the same answers again

    plan = (await client.get(CURRENT, headers=guest)).json()
    assert plan["id"] == planned["id"]


async def test_a_yes_on_the_safety_screen_makes_the_plan_gentle_at_once(
    client: AsyncClient, guest: Headers
) -> None:
    await _onboard(client, guest, goal="lose_fat", days_per_week=3)
    planned = (await client.post(PLANS, headers=guest)).json()
    before = await _details(client, guest, planned)
    assert any(d["finisher"] for d in before)  # lose fat, 3 days: finishers

    await client.post(SAFETY, json=ALL_NO | {"heart_condition": True}, headers=guest)

    plan = (await client.get(CURRENT, headers=guest)).json()
    assert plan["id"] != planned["id"]
    after = await _details(client, guest, plan)
    assert not any(d["finisher"] for d in after)
    reserves = [e["reps_in_reserve"] for d in after for e in d["main"]]
    assert all(r >= 4 for r in reserves if r is not None)


async def test_a_plan_is_saved_with_the_answers_it_was_built_from(
    planned: dict[str, Any], db_session: AsyncSession
) -> None:
    plan = await db_session.scalar(select(Plan).where(Plan.id == uuid.UUID(planned["id"])))

    assert plan is not None
    assert plan.generated_from["days_per_week"] == 3
    assert plan.generated_from["level"] == "beginner"
    assert "obstacles" not in plan.generated_from


async def test_strength_kinds_list_matches_the_generator() -> None:
    from lock_in_mode_api.training.templates import STRENGTH_KINDS

    assert {kind.value for kind in STRENGTH_KINDS} <= STRENGTH | {
        "bro_chest",
        "bro_back",
        "bro_legs",
        "bro_shoulders",
        "bro_arms",
    }
