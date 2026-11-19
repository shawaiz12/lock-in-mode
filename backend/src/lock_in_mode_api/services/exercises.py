"""Reading the exercise library (ADR 0013). Read-only: nothing here commits."""

import uuid

from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    any_,
    cast,
    false,
    func,
    literal,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, Profile, exercise_alternatives
from lock_in_mode_api.models.enums import Location
from lock_in_mode_api.schemas.exercise import (
    ExerciseDetail,
    ExerciseFilters,
    ExercisePage,
    ExerciseRef,
    ExerciseSummary,
)
from lock_in_mode_api.training.exercise_rules import cautions, user_kit


class ExerciseNotFoundError(Exception):
    """No exercise with this id. Callers answer 404."""


class ProfileRequiredError(Exception):
    """`for_me` needs the user's answers. Callers answer 404 profile_not_found."""


def _available_to(profile: Profile) -> ColumnElement[bool]:
    """SQL version of training.exercise_rules.can_do (a test keeps the two in step).

    Filtering in the database, not in Python, keeps `total` and the pages correct.
    """
    kit = sorted(user_kit(profile.location, profile.equipment))
    # `<@` = "is contained by": every item the exercise needs is in the user's kit.
    has_the_kit = Exercise.equipment.contained_by(cast(kit, ARRAY(String(30))))
    not_a_home_trick = Exercise.home_only == false() if profile.location == Location.GYM else true()
    return and_(has_the_kit, not_a_home_trick)


def _summary(exercise: Exercise, profile: Profile | None) -> ExerciseSummary:
    summary = ExerciseSummary.model_validate(exercise)
    if profile is not None:
        summary.cautions = cautions(exercise, profile)
    return summary


async def list_exercises(
    session: AsyncSession, user_id: uuid.UUID, filters: ExerciseFilters
) -> ExercisePage:
    profile = await session.get(Profile, user_id)
    if filters.for_me and profile is None:
        raise ProfileRequiredError

    conditions: list[ColumnElement[bool]] = []
    if filters.for_me and profile is not None:
        conditions.append(_available_to(profile))
    if filters.category is not None:
        conditions.append(Exercise.category == filters.category)
    if filters.movement_slot is not None:
        conditions.append(Exercise.movement_slot == filters.movement_slot)
    if filters.muscle is not None:
        conditions.append(
            or_(
                Exercise.primary_muscle == filters.muscle,
                literal(filters.muscle.value) == any_(Exercise.secondary_muscles),
            )
        )
    if filters.max_difficulty is not None:
        conditions.append(Exercise.difficulty <= filters.max_difficulty)

    total = await session.scalar(select(func.count()).select_from(Exercise).where(*conditions))
    rows = await session.scalars(
        select(Exercise)
        .where(*conditions)
        .order_by(Exercise.name, Exercise.id)  # id breaks ties, so pages never overlap
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
    )
    return ExercisePage(
        items=[_summary(exercise, profile) for exercise in rows],
        page=filters.page,
        page_size=filters.page_size,
        total=total or 0,
    )


async def get_exercise(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID
) -> ExerciseDetail:
    exercise = await session.get(Exercise, exercise_id)
    if exercise is None:
        raise ExerciseNotFoundError
    profile = await session.get(Profile, user_id)

    harder = (
        await session.get(Exercise, exercise.harder_variant_id)
        if exercise.harder_variant_id is not None
        else None
    )
    # harder_variant_id is UNIQUE, so at most one exercise steps up to this one.
    easier = await session.scalar(select(Exercise).where(Exercise.harder_variant_id == exercise.id))
    alternatives = await session.scalars(
        select(Exercise)
        .join(exercise_alternatives, exercise_alternatives.c.alternative_id == Exercise.id)
        .where(exercise_alternatives.c.exercise_id == exercise.id)
        .order_by(Exercise.name)
    )

    summary = _summary(exercise, profile)
    return ExerciseDetail.model_validate(
        {
            **summary.model_dump(),
            "exercise_type": exercise.exercise_type,
            "secondary_muscles": exercise.secondary_muscles,
            "targets": exercise.targets,
            "not_suitable_for": exercise.not_suitable_for,
            "steps": exercise.steps,
            "cues": exercise.cues,
            "common_mistake": exercise.common_mistake,
            "easier": ExerciseRef.model_validate(easier) if easier else None,
            "harder": ExerciseRef.model_validate(harder) if harder else None,
            "alternatives": [ExerciseRef.model_validate(alt) for alt in alternatives],
        }
    )
