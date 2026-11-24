"""Protect your progress (ADR 0026): what a guest would lose, and when to offer sign-in.

A guest's account lives behind one refresh token on one phone. After their 3rd and 10th
finished workout and at their first finished block, the finish screen offers Google/Apple
sign-in with a summary of what they've built. `GET /me` carries the same summary for
every guest. Nothing remembers "Not now": each milestone can only happen once, and a
guest who links stops being a guest.

Reads only, apart from the `sign_in_offered` event; the caller commits.
"""

import uuid
from typing import Literal

from sqlalchemy import ColumnElement, ScalarSelect, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    ExerciseTarget,
    MovementRung,
    Plan,
    PlannedWorkout,
    SetLog,
    SwappedOutExercise,
    User,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import PlanEndReason, WorkoutStatus
from lock_in_mode_api.schemas.user import ProgressSummary, SignInMilestone, SignInOffer
from lock_in_mode_api.services import events

WORKOUT_MILESTONES: dict[int, Literal["workout_3", "workout_10"]] = {
    3: "workout_3",
    10: "workout_10",
}


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary_lines(
    *,
    workouts_finished: int,
    sets_logged: int,
    exercises_with_own_numbers: int,
    exercises_left_out: int,
    strength_test_moves: int,
) -> list[str]:
    """The summary's lines, in a fixed order. A count of 0 has no line: never "0 sets"."""
    lines = []
    if workouts_finished:
        lines.append(f"{_count(workouts_finished, 'workout', 'workouts')} finished")
    if sets_logged:
        lines.append(f"{_count(sets_logged, 'set', 'sets')} logged")
    if exercises_with_own_numbers:
        saved = _count(exercises_with_own_numbers, "exercise", "exercises")
        lines.append(f"Your own numbers saved for {saved}")
    if exercises_left_out:
        left_out = _count(exercises_left_out, "exercise", "exercises")
        why = "it hurt" if exercises_left_out == 1 else "they hurt"
        lines.append(f"{left_out} left out because {why}")
    if strength_test_moves:
        moves = _count(strength_test_moves, "move", "moves")
        lines.append(f"Strength test: starting points for {moves}")
    return lines


def _tuned() -> ColumnElement[bool]:
    """A progress row with a number of its own (ADR 0019): a weight, a set more or less, a
    hold or extra reps. A row that only counts missed sessions (`short_runs`) still serves
    the plan's numbers, so it doesn't count: the summary never overstates."""
    return (
        ExerciseTarget.weight_kg.is_not(None)
        | (ExerciseTarget.set_change != 0)
        | ExerciseTarget.seconds.is_not(None)
        | (ExerciseTarget.reps_bonus > 0)
    )


def _count_where(*where: ColumnElement[bool]) -> ScalarSelect[int]:
    return select(func.count()).where(*where).scalar_subquery()


async def summarize(session: AsyncSession, user_id: uuid.UUID) -> ProgressSummary:
    """Five counts in one query, from what's already stored."""
    count = _count_where
    row = (
        await session.execute(
            select(
                count(WorkoutSession.user_id == user_id, WorkoutSession.finished_at.is_not(None)),
                select(func.count())
                .select_from(SetLog)
                .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
                .where(WorkoutSession.user_id == user_id)
                .scalar_subquery(),
                count(ExerciseTarget.user_id == user_id, _tuned()),
                count(SwappedOutExercise.user_id == user_id),
                count(MovementRung.user_id == user_id),
            )
        )
    ).one()
    workouts, sets, own_numbers, left_out, test_moves = (int(n) for n in row)
    return ProgressSummary(
        workouts_finished=workouts,
        sets_logged=sets,
        exercises_with_own_numbers=own_numbers,
        exercises_left_out=left_out,
        strength_test_moves=test_moves,
        lines=summary_lines(
            workouts_finished=workouts,
            sets_logged=sets,
            exercises_with_own_numbers=own_numbers,
            exercises_left_out=left_out,
            strength_test_moves=test_moves,
        ),
    )


async def _completed_a_block_before(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """An earlier plan was complete: it ended as finished (the next block was started), or
    it was replaced by changed answers with no workout left pending. Without the second
    case, a complete block 1 replaced by new answers would make the next block "first"
    again and repeat the offer."""
    pending = exists().where(
        PlannedWorkout.plan_id == Plan.id, PlannedWorkout.status == WorkoutStatus.PENDING
    )
    found = await session.scalar(
        select(
            exists().where(
                Plan.user_id == user_id,
                Plan.ended_at.is_not(None),
                (Plan.end_reason == PlanEndReason.FINISHED) | ~pending,
            )
        )
    )
    return bool(found)


async def _milestone(
    session: AsyncSession, user_id: uuid.UUID, finished: int, *, block_complete: bool
) -> SignInMilestone | None:
    """Which milestone this finish hits, if any. One finish = at most one offer, named by
    the first match: first block, then workout 10, then workout 3."""
    if block_complete and not await _completed_a_block_before(session, user_id):
        return "first_block"
    return WORKOUT_MILESTONES.get(finished)


async def offer_after_finish(
    session: AsyncSession, user_id: uuid.UUID, *, block_complete: bool
) -> SignInOffer | None:
    """Call after the finish is flushed, with whether it completed the block. For a guest
    at a milestone: records `sign_in_offered` and returns the offer. Otherwise None.

    Workouts closed automatically (the next one was started) and blocks ended by a skip
    have no finish screen, so their milestone passes without an offer (ADR 0026)."""
    is_guest = await session.scalar(select(User.is_guest).where(User.id == user_id))
    if not is_guest:
        return None
    finished = (
        await session.scalar(
            select(func.count()).where(
                WorkoutSession.user_id == user_id, WorkoutSession.finished_at.is_not(None)
            )
        )
        or 0
    )
    milestone = await _milestone(session, user_id, finished, block_complete=block_complete)
    if milestone is None:
        return None
    await events.sign_in_offered(session, user_id, milestone=milestone, number=finished)
    return SignInOffer(milestone=milestone, summary=await summarize(session, user_id))
