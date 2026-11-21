"""Rules the database keeps for plans (ADR 0017), even if the service has a bug."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Exercise,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    User,
)
from lock_in_mode_api.models.enums import (
    ExerciseCategory,
    ExerciseType,
    MovementSlot,
    PlanEndReason,
    RoutineKind,
    SessionKind,
    WorkoutFormat,
    WorkoutPart,
)


async def _user(session: AsyncSession) -> User:
    user = User()
    session.add(user)
    await session.flush()
    return user


def _plan(user: User, block_number: int = 1, **overrides: object) -> Plan:
    fields: dict[str, object] = {
        "user_id": user.id,
        "block_number": block_number,
        "routine_kind": RoutineKind.FULL_BODY,
        "reasons": ["why"],
        "weekdays": [0, 2, 4],
        "uses_push_pull_legs": False,
        "weeks": 5,
        "generated_from": {},
    }
    fields.update(overrides)
    return Plan(**fields)


def _ended() -> dict[str, object]:
    return {"ended_at": datetime.now(UTC), "end_reason": PlanEndReason.FINISHED}


async def test_ended_plans_and_one_current_plan_can_live_together(
    db_session: AsyncSession,
) -> None:
    user = await _user(db_session)

    db_session.add_all([_plan(user, 1, **_ended()), _plan(user, 2, **_ended()), _plan(user, 3)])
    await db_session.flush()


async def test_only_one_current_plan_per_user(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(_plan(user, 1))
    await db_session.flush()

    db_session.add(_plan(user, 2))
    with pytest.raises(IntegrityError, match="uq_plans_one_current_per_user"):
        await db_session.flush()


async def test_two_users_each_have_a_current_plan(db_session: AsyncSession) -> None:
    db_session.add_all([_plan(await _user(db_session)), _plan(await _user(db_session))])
    await db_session.flush()


async def test_block_numbers_are_unique_per_user(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add_all([_plan(user, 1, **_ended()), _plan(user, 1)])

    with pytest.raises(IntegrityError, match="uq_plans_user_block_number"):
        await db_session.flush()


async def test_an_ended_plan_needs_a_reason(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(_plan(user, ended_at=datetime.now(UTC)))

    with pytest.raises(IntegrityError, match="ck_plans_ended_with_reason"):
        await db_session.flush()


async def test_an_exercise_in_a_saved_plan_cannot_be_deleted(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    exercise = Exercise(
        slug="test-move",
        name="Test move",
        category=ExerciseCategory.PUSH,
        movement_slot=MovementSlot.HORIZONTAL_PUSH,
        exercise_type=ExerciseType.COMPOUND,
        difficulty=1,
    )
    db_session.add(exercise)
    await db_session.flush()
    workout = PlannedWorkout(
        position=1,
        week=1,
        kind=SessionKind.FULL_BODY,
        title="Full body A",
        format=WorkoutFormat.STRAIGHT_SETS,
        main_minutes=20,
        total_minutes=30,
        exercises=[
            PlannedWorkoutExercise(
                part=WorkoutPart.MAIN, position=1, exercise_id=exercise.id, sets=2, rest_seconds=60
            )
        ],
    )
    db_session.add(_plan(user, workouts=[workout]))
    await db_session.flush()

    with pytest.raises(IntegrityError, match="fk_planned_exercises_exercise_id_exercises"):
        await db_session.execute(delete(Exercise).where(Exercise.id == exercise.id))
