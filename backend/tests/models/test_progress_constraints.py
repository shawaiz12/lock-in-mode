"""Rules the database keeps for saved progress (ADR 0019), even if the service has a bug."""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, ExerciseTarget, User
from lock_in_mode_api.models.enums import ExerciseCategory, ExerciseType, MovementSlot


async def _target(session: AsyncSession, **values: Any) -> ExerciseTarget:
    user = User()
    exercise = Exercise(
        slug="test-move",
        name="Test move",
        category=ExerciseCategory.PUSH,
        movement_slot=MovementSlot.HORIZONTAL_PUSH,
        exercise_type=ExerciseType.COMPOUND,
        difficulty=1,
    )
    session.add_all([user, exercise])
    await session.flush()
    target = ExerciseTarget(user_id=user.id, exercise_id=exercise.id, **values)
    session.add(target)
    return target


async def test_defaults_mean_as_planned(db_session: AsyncSession) -> None:
    target = await _target(db_session)
    await db_session.flush()
    await db_session.refresh(target)

    assert (target.weight_kg, target.set_change, target.seconds) == (None, 0, None)
    assert (target.reps_bonus, target.short_runs) == (0, 0)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"weight_kg": 0}, "ck_exercise_targets_weight_positive"),
        ({"set_change": 2}, "ck_exercise_targets_set_change_range"),
        ({"set_change": -2}, "ck_exercise_targets_set_change_range"),
        ({"seconds": 0}, "ck_exercise_targets_seconds_range"),
        ({"reps_bonus": 6}, "ck_exercise_targets_reps_bonus_range"),
        ({"short_runs": -1}, "ck_exercise_targets_short_runs_not_negative"),
    ],
)
async def test_nonsense_progress_is_refused(
    db_session: AsyncSession, values: dict[str, Any], constraint: str
) -> None:
    await _target(db_session, **values)

    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()
