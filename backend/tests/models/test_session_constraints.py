"""Rules the database keeps for sessions (ADR 0018), even if the service has a bug."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Exercise,
    MovementRung,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    SetLog,
    User,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import (
    ExerciseCategory,
    ExerciseType,
    Feedback,
    MovementSlot,
    RoutineKind,
    SessionKind,
    WorkoutFormat,
    WorkoutPart,
)


async def _workouts(session: AsyncSession, count: int = 2) -> tuple[User, list[PlannedWorkout]]:
    user = User()
    session.add(user)
    await session.flush()
    workouts = [
        PlannedWorkout(
            position=n,
            week=1,
            kind=SessionKind.FULL_BODY,
            title="Full body A",
            format=WorkoutFormat.STRAIGHT_SETS,
            main_minutes=20,
            total_minutes=30,
        )
        for n in range(1, count + 1)
    ]
    session.add(
        Plan(
            user_id=user.id,
            block_number=1,
            routine_kind=RoutineKind.FULL_BODY,
            reasons=[],
            weekdays=[0],
            uses_push_pull_legs=False,
            weeks=5,
            generated_from={},
            workouts=workouts,
        )
    )
    await session.flush()
    return user, workouts


async def test_only_one_open_session_per_user(db_session: AsyncSession) -> None:
    user, (first, second) = await _workouts(db_session)
    db_session.add(WorkoutSession(user_id=user.id, planned_workout_id=first.id))
    await db_session.flush()

    db_session.add(WorkoutSession(user_id=user.id, planned_workout_id=second.id))
    with pytest.raises(IntegrityError, match="uq_workout_sessions_one_open_per_user"):
        await db_session.flush()


async def test_finished_sessions_dont_count_as_open(db_session: AsyncSession) -> None:
    user, (first, second) = await _workouts(db_session)
    db_session.add_all(
        [
            WorkoutSession(
                user_id=user.id, planned_workout_id=first.id, finished_at=datetime.now(UTC)
            ),
            WorkoutSession(user_id=user.id, planned_workout_id=second.id),
        ]
    )
    await db_session.flush()


async def test_a_workout_has_one_session(db_session: AsyncSession) -> None:
    user, (first, _) = await _workouts(db_session)
    now = datetime.now(UTC)
    db_session.add_all(
        [
            WorkoutSession(user_id=user.id, planned_workout_id=first.id, finished_at=now),
            WorkoutSession(user_id=user.id, planned_workout_id=first.id, finished_at=now),
        ]
    )

    with pytest.raises(IntegrityError, match="uq_workout_sessions_planned_workout_id"):
        await db_session.flush()


async def test_feedback_only_on_a_finished_session(db_session: AsyncSession) -> None:
    user, (first, _) = await _workouts(db_session)
    db_session.add(
        WorkoutSession(user_id=user.id, planned_workout_id=first.id, feedback=Feedback.TOO_EASY)
    )

    with pytest.raises(IntegrityError, match="ck_workout_sessions_feedback_at_finish"):
        await db_session.flush()


async def test_a_set_needs_reps_or_seconds(db_session: AsyncSession) -> None:
    user, (first, _) = await _workouts(db_session)
    workout_session = WorkoutSession(user_id=user.id, planned_workout_id=first.id)
    db_session.add(workout_session)
    await db_session.flush()
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
    row = PlannedWorkoutExercise(
        planned_workout_id=first.id,
        part=WorkoutPart.MAIN,
        position=1,
        exercise_id=exercise.id,
        sets=2,
        rest_seconds=60,
    )
    db_session.add(row)
    await db_session.flush()

    db_session.add(SetLog(session_id=workout_session.id, planned_exercise_id=row.id, set_number=1))
    with pytest.raises(IntegrityError, match="ck_set_logs_reps_or_seconds"):
        await db_session.flush()


async def test_a_rung_is_a_difficulty_from_1_to_5(db_session: AsyncSession) -> None:
    user, _ = await _workouts(db_session, 1)
    db_session.add(
        MovementRung(user_id=user.id, movement=MovementSlot.SQUAT, difficulty=6, result=40)
    )

    with pytest.raises(IntegrityError, match="ck_movement_rungs_difficulty_range"):
        await db_session.flush()
