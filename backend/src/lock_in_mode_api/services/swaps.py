"""Swapping exercises (ADR 0020, KB section 11): "this hurts, swap it", "show another",
where it hurt, and bringing an exercise back.

Functions that change data own the transaction and commit.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Exercise,
    PlannedWorkoutExercise,
    Profile,
    SetLog,
    SwappedOutExercise,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import BodyArea, BodyLimit, SwapReason
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.swap import SwappedOutRead, SwapResult, WhereResult
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import PlanAnswers
from lock_in_mode_api.training.swaps import another, replacement

# An open strength-test set ("as many as you can") swapped for another move is no longer
# a test (its count wouldn't place anyone), so it gets an ordinary target.
OPEN_TEST_REPS = (8, 12)
OPEN_TEST_SECONDS = 30
POSITION_SHIFT = 1000  # moves rows out of the way so (workout, part, position) stays unique


class PlannedExerciseNotFoundError(Exception):
    """That exercise isn't in this workout. Callers answer 404."""


class ExerciseChangedError(Exception):
    """The row holds a different exercise now (a double tap). Callers answer 409."""


class NoOtherExerciseError(Exception):
    """ "Show another": nothing else safe does this job. Callers answer 409."""


class SwapNotFoundError(Exception):
    """This exercise isn't swapped out. Callers answer 404."""


# --- swapping -------------------------------------------------------------------------------


def _take(row: PlannedWorkoutExercise, exercise: Exercise) -> None:
    """Put `exercise` in this row, keeping the slot's numbers."""
    row.exercise = exercise
    if row.is_test:
        row.is_test = False
        if row.reps_min is None and row.seconds is None:
            if exercise.is_timed:
                row.seconds = OPEN_TEST_SECONDS
            else:
                row.reps_min, row.reps_max = OPEN_TEST_REPS


async def _sets_done(
    session: AsyncSession, workout_id: uuid.UUID, row: PlannedWorkoutExercise
) -> int:
    done = await session.scalar(
        select(func.count())
        .select_from(SetLog)
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .where(
            WorkoutSession.planned_workout_id == workout_id,
            SetLog.planned_exercise_id == row.id,
        )
    )
    return done or 0


async def _insert_after(
    session: AsyncSession, row: PlannedWorkoutExercise, exercise: Exercise, sets: int
) -> None:
    """A new row right after `row` for the sets that were left. Later rows move down one:
    first far away, then back to one place further, so no two rows share a position."""
    same_part = (
        PlannedWorkoutExercise.planned_workout_id == row.planned_workout_id,
        PlannedWorkoutExercise.part == row.part,
    )
    moves = (
        (PlannedWorkoutExercise.position > row.position, POSITION_SHIFT),
        (PlannedWorkoutExercise.position > POSITION_SHIFT, 1 - POSITION_SHIFT),
    )
    for which, shift in moves:
        await session.execute(
            update(PlannedWorkoutExercise)
            .where(*same_part, which)
            .values(position=PlannedWorkoutExercise.position + shift)
            .execution_options(synchronize_session=False)
        )
    new = PlannedWorkoutExercise(
        planned_workout_id=row.planned_workout_id,
        part=row.part,
        position=row.position + 1,
        sets=sets,
        reps_min=row.reps_min,
        reps_max=row.reps_max,
        seconds=row.seconds,
        rest_seconds=row.rest_seconds,
        reps_in_reserve=row.reps_in_reserve,
        effort=row.effort,
        group_number=row.group_number,
        practice_sets=0,
        is_test=row.is_test,
    )
    _take(new, exercise)
    session.add(new)


async def swap(
    session: AsyncSession,
    user_id: uuid.UUID,
    workout_id: uuid.UUID,
    planned_exercise_id: uuid.UUID,
    exercise_id: uuid.UUID,
    reason: SwapReason,
) -> SwapResult:
    """Swap one exercise of the next workout (the one about to start, or in progress).

    hurts: the exercise is swapped out for good, today's row gets the best stand-in (same
    or easier), and the rest of the block is rebuilt without it. another: today's row
    gets the next option; later workouts are unchanged. Sets already done stay with the
    old exercise and the stand-in asks only for the sets left. Nothing safe left: the
    slot is left out today (and the rebuild leaves it out later too).
    """
    # Plan first: reloading it would drop the exercises loaded with the workout.
    plan = await plan_service.current_plan(session, user_id)
    workout = await plan_service.load_workout(session, user_id, workout_id, lock=True)
    upcoming = None if plan is None else plan_service.next_workout(plan)
    if plan is None or upcoming is None or upcoming.id != workout.id:
        raise plan_service.NotNextWorkoutError
    row = next((r for r in workout.exercises if r.id == planned_exercise_id), None)
    if row is None:
        raise PlannedExerciseNotFoundError
    if row.exercise_id != exercise_id or row.swapped_out:
        raise ExerciseChangedError
    old = row.exercise

    if reason == SwapReason.HURTS:
        await session.execute(
            insert(SwappedOutExercise)
            .values(user_id=user_id, exercise_id=old.id)
            .on_conflict_do_nothing()
        )
    library = await plan_service.exercise_library(session)
    picker = Picker(
        PlanAnswers.from_json(plan.generated_from),
        library,
        plan.block_number,
        await plan_service.rungs_of(session, user_id),
        await plan_service.excluded_of(session, user_id),
    )
    used = {r.exercise.slug for r in workout.exercises if r.id != row.id and not r.swapped_out}
    choose = replacement if reason == SwapReason.HURTS else another
    picked = choose(picker, old, used)
    if picked is None and reason == SwapReason.ANOTHER:
        raise NoOtherExerciseError
    by_slug = {exercise.slug: exercise for exercise in library}
    stand_in = None if picked is None else by_slug[picked.slug]

    done = await _sets_done(session, workout.id, row)
    left_out = stand_in is None
    if done == 0:
        if stand_in is None:
            await session.delete(row)
        else:
            _take(row, stand_in)
    else:
        sets_left = row.sets - done
        row.swapped_out = True
        row.sets = done
        if sets_left <= 0:
            stand_in, left_out = None, False  # nothing left to do today
        elif stand_in is not None:
            await _insert_after(session, row, stand_in, sets_left)
    await session.flush()

    if reason == SwapReason.HURTS:
        await plan_service.rebuild_pending(session, user_id, keep={workout.id})
    await session.commit()
    return SwapResult(
        workout=await plan_service.get_workout(session, user_id, workout.id),
        swapped_out=ExerciseRef.model_validate(old),
        swapped_in=None if stand_in is None else ExerciseRef.model_validate(stand_in),
        left_out=left_out,
    )


# --- the swapped-out list ---------------------------------------------------------------------


def _read(row: SwappedOutExercise) -> SwappedOutRead:
    return SwappedOutRead(
        exercise=ExerciseRef.model_validate(row.exercise),
        body_area=row.body_area,
        swapped_at=row.created_at,
    )


async def _find(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID
) -> SwappedOutExercise:
    found = await session.scalar(
        select(SwappedOutExercise)
        .where(SwappedOutExercise.user_id == user_id, SwappedOutExercise.exercise_id == exercise_id)
        .options(selectinload(SwappedOutExercise.exercise))
        .execution_options(populate_existing=True)
    )
    if found is None:
        raise SwapNotFoundError
    return found


async def list_swapped_out(session: AsyncSession, user_id: uuid.UUID) -> list[SwappedOutRead]:
    """Newest first: the "Exercises you swapped out" screen, each with "bring it back"."""
    rows: Sequence[SwappedOutExercise] = (
        await session.scalars(
            select(SwappedOutExercise)
            .where(SwappedOutExercise.user_id == user_id)
            .options(selectinload(SwappedOutExercise.exercise))
            .order_by(SwappedOutExercise.created_at.desc(), SwappedOutExercise.exercise_id)
        )
    ).all()
    return [_read(row) for row in rows]


async def set_where(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID, area: BodyArea
) -> WhereResult:
    """The optional "Where does it hurt?" tap. Knees, back or shoulders that aren't a limit
    yet come back as `suggest_limit`, for the app to offer after the workout."""
    row = await _find(session, user_id, exercise_id)
    row.body_area = area
    await session.commit()
    profile = await session.get(Profile, user_id)
    limit = None if area == BodyArea.OTHER else BodyLimit(area.value)
    if limit is not None and profile is not None and limit.value in profile.limits:
        limit = None
    row = await _find(session, user_id, exercise_id)
    return WhereResult(**_read(row).model_dump(), suggest_limit=limit)


async def bring_back(session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID) -> None:
    """Undo a swap: the exercise can be picked again, from the rest of this block on."""
    await _find(session, user_id, exercise_id)
    await session.execute(
        delete(SwappedOutExercise).where(
            SwappedOutExercise.user_id == user_id, SwappedOutExercise.exercise_id == exercise_id
        )
    )
    await session.flush()
    await plan_service.rebuild_pending(session, user_id)
    await session.commit()
