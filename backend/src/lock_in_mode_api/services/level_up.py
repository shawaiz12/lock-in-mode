"""Moving up a level (ADR 0022): is a beginner ready for "some experience"?

Reads models only, so the plans service can use it (services: … → plans → level_up).
Nothing is stored: the offer is worked out from the user's history every time. The plans
service decides *when* it's shown (block complete, no comeback).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    Exercise,
    PlannedWorkoutExercise,
    Profile,
    SetLog,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import FitnessLevel
from lock_in_mode_api.training import level_up as rules


@dataclass(frozen=True)
class Offer:
    to: FitnessLevel
    reason: rules.LevelUpReason
    good_weeks: int
    check_with_doctor: bool
    what_changes: tuple[str, ...] = ()  # filled in by the plans service, which can build


async def good_weeks(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Good weeks so far: trained workouts are finished sessions with a ticked set."""
    finished = await session.scalars(
        select(WorkoutSession.finished_at).where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.finished_at.is_not(None),
            exists().where(SetLog.session_id == WorkoutSession.id),
        )
    )
    return rules.good_weeks(t for t in finished if t is not None)


async def _ladders(session: AsyncSession) -> tuple[dict[str, str | None], dict[str, bool]]:
    """The library's `harder` links and which moves are holds, by slug."""
    rows = (
        await session.execute(
            select(Exercise.id, Exercise.slug, Exercise.harder_variant_id, Exercise.is_timed)
        )
    ).all()
    slug_of = {row.id: row.slug for row in rows}
    harder = {row.slug: slug_of.get(row.harder_variant_id) for row in rows}
    timed = {row.slug: row.is_timed for row in rows}
    return harder, timed


async def _best(session: AsyncSession, user_id: uuid.UUID, slugs: set[str]) -> rules.Best:
    """The most reps and longest hold in one logged set, for these moves."""
    rows = await session.execute(
        select(Exercise.slug, func.max(SetLog.reps), func.max(SetLog.seconds))
        .join(PlannedWorkoutExercise, PlannedWorkoutExercise.exercise_id == Exercise.id)
        .join(SetLog, SetLog.planned_exercise_id == PlannedWorkoutExercise.id)
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .where(WorkoutSession.user_id == user_id, Exercise.slug.in_(slugs))
        .group_by(Exercise.slug)
    )
    reps: dict[str, int] = {}
    seconds: dict[str, int] = {}
    for slug, most_reps, longest in rows:
        if most_reps is not None:
            reps[slug] = most_reps
        if longest is not None:
            seconds[slug] = longest
    return rules.Best(reps, seconds)


async def offer_for(session: AsyncSession, user_id: uuid.UUID) -> Offer | None:
    """The move up this user has earned, if any. Writes nothing."""
    profile = await session.get(Profile, user_id)
    if profile is None or profile.level != FitnessLevel.BEGINNER:
        return None
    weeks = await good_weeks(session, user_id)
    harder, timed = await _ladders(session)
    slugs = {slug for mark in rules.MARKS for slug in rules.ladder(mark.slug, harder)}
    marks = rules.passes_all(await _best(session, user_id, slugs), harder, timed)
    reason = rules.offer(profile.level, weeks, marks)
    if reason is None:
        return None
    return Offer(
        to=FitnessLevel.SOME_EXPERIENCE,
        reason=reason,
        good_weeks=weeks,
        check_with_doctor=profile.needs_low_intensity,
    )
