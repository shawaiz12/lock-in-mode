"""Saving and serving plans: training blocks and the "next workout" queue (ADR 0017).

The plan generator (`training/`) is pure. This module feeds it the user's answers and
the exercise library rows, saves what it returns, and walks the queue.

Functions that change data own the transaction and commit, except
`replace_if_answers_changed`, which joins the caller's (the profile service's), so the
new answers and the new plan are saved together or not at all.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Exercise,
    ExerciseTarget,
    MovementRung,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    Profile,
    SetLog,
    SwappedOutExercise,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import (
    MovementSlot,
    PlanEndReason,
    WorkoutFormat,
    WorkoutPart,
    WorkoutStatus,
)
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.plan import (
    LastResult,
    PlannedExerciseRead,
    PlanRead,
    WorkoutDetail,
    WorkoutSummary,
)
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import (
    BUILD_WEEKS,
    PlanAnswers,
    PlannedExercise,
    Workout,
)
from lock_in_mode_api.training.progression import Planned, Served, Target, serve
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import as_test_workout, build_block
from lock_in_mode_api.training.templates import STRENGTH_KINDS


class ProfileRequiredError(Exception):
    """No onboarding answers yet. Callers answer 404 profile_not_found."""


class SafetyScreenRequiredError(Exception):
    """The safety screen comes before any plan (ADR 0012). Callers answer 409."""


class PlanNotFoundError(Exception):
    """No current plan. Callers answer 404 plan_not_found."""


class PlanInProgressError(Exception):
    """The current block still has pending workouts. Callers answer 409."""


class BlockCompleteError(Exception):
    """No pending workout left in the block. Callers answer 404 block_complete."""


class WorkoutNotFoundError(Exception):
    """No workout with this id for this user. Callers answer 404."""


class NotNextWorkoutError(Exception):
    """Only the next workout can be skipped or started. Callers answer 409."""


class SessionInProgressError(Exception):
    """The workout has an open session: finish it instead (half counts). Callers answer 409."""


# --- reading ----------------------------------------------------------------------------


async def current_plan(session: AsyncSession, user_id: uuid.UUID) -> Plan | None:
    """The current plan with its queue. `populate_existing` reloads rows this session
    already holds, so values the database filled in (created_at) are always there.
    """
    return await session.scalar(
        select(Plan)
        .where(Plan.user_id == user_id, Plan.ended_at.is_(None))
        .options(selectinload(Plan.workouts))
        .execution_options(populate_existing=True)
    )


def next_workout(plan: Plan) -> PlannedWorkout | None:
    return next((w for w in plan.workouts if w.status == WorkoutStatus.PENDING), None)


def _plan_read(plan: Plan) -> PlanRead:
    upcoming = next_workout(plan)
    return PlanRead(
        id=plan.id,
        block_number=plan.block_number,
        routine_kind=plan.routine_kind,
        reasons=plan.reasons,
        weekdays=plan.weekdays,
        uses_push_pull_legs=plan.uses_push_pull_legs,
        weeks=plan.weeks,
        created_at=plan.created_at,
        next_workout_id=upcoming.id if upcoming else None,
        block_complete=upcoming is None,
        workouts=[_summary(w) for w in plan.workouts],
    )


def _summary(workout: PlannedWorkout) -> WorkoutSummary:
    return WorkoutSummary(
        id=workout.id,
        position=workout.position,
        week=workout.week,
        kind=workout.kind,
        title=workout.title,
        format=workout.format,
        recovery=workout.recovery,
        total_minutes=workout.total_minutes,
        status=workout.status,
    )


def progresses(row: PlannedWorkoutExercise) -> bool:
    """Main-block strength work moves with the user's progress (ADR 0019). Warm-ups,
    cardio, open test sets and rows swapped out mid-workout (ADR 0020) keep their numbers."""
    return (
        row.part == WorkoutPart.MAIN
        and row.reps_in_reserve is not None
        and not row.is_test
        and not row.swapped_out
    )


def served(row: PlannedWorkoutExercise, workout: PlannedWorkout, target: Target | None) -> Served:
    """What this row asks for now. The recovery week keeps its lighter numbers and only
    takes the suggested weight ("same weight, stop 4 reps short")."""
    planned = Planned(row.sets, row.reps_min, row.reps_max, row.seconds)
    if target is not None and workout.recovery:
        target = Target(weight_kg=target.weight_kg)
    return serve(planned, target, circuit=workout.format == WorkoutFormat.CIRCUIT)


def _exercise_read(
    row: PlannedWorkoutExercise,
    workout: PlannedWorkout,
    last: dict[uuid.UUID, LastResult],
    targets: dict[uuid.UUID, Target],
) -> PlannedExerciseRead:
    """Pending workouts show today's targets; done and skipped ones show what was saved."""
    now = Served(row.sets, row.reps_min, row.reps_max, row.seconds, None)
    if workout.status == WorkoutStatus.PENDING and progresses(row):
        now = served(row, workout, targets.get(row.exercise_id))
    previous = last.get(row.exercise_id)
    weight = now.weight_kg
    if weight is None and previous is not None and row.reps_in_reserve is not None:
        weight = previous.weight_kg
    return PlannedExerciseRead(
        id=row.id,
        exercise=ExerciseRef.model_validate(row.exercise),
        sets=now.sets,
        reps_min=now.reps_min,
        reps_max=now.reps_max,
        seconds=now.seconds,
        rest_seconds=row.rest_seconds,
        reps_in_reserve=row.reps_in_reserve,
        effort=row.effort,
        group=row.group_number,
        practice_sets=row.practice_sets,
        is_test=row.is_test,
        swapped_out=row.swapped_out,
        weight_kg=weight,
        last=previous,
    )


async def targets_of(
    session: AsyncSession, user_id: uuid.UUID, exercise_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Target]:
    """This user's progress on these exercises (ADR 0019). Missing = as planned."""
    if not exercise_ids:
        return {}
    rows = await session.scalars(
        select(ExerciseTarget).where(
            ExerciseTarget.user_id == user_id, ExerciseTarget.exercise_id.in_(exercise_ids)
        )
    )
    return {row.exercise_id: row.as_target() for row in rows}


async def last_results(
    session: AsyncSession, user_id: uuid.UUID, exercise_ids: set[uuid.UUID]
) -> dict[uuid.UUID, LastResult]:
    """The most recent logged set of each exercise, from any workout: the app pre-fills
    the next set with it ("last time: 20 kg x 10"). One query: DISTINCT ON keeps the
    first row per exercise in the ORDER BY, i.e. the newest.
    """
    if not exercise_ids:
        return {}
    rows = await session.execute(
        select(
            PlannedWorkoutExercise.exercise_id,
            SetLog.reps,
            SetLog.weight_kg,
            SetLog.seconds,
            SetLog.logged_at,
        )
        .join(SetLog, SetLog.planned_exercise_id == PlannedWorkoutExercise.id)
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            PlannedWorkoutExercise.exercise_id.in_(exercise_ids),
        )
        .ext(distinct_on(PlannedWorkoutExercise.exercise_id))
        .order_by(
            PlannedWorkoutExercise.exercise_id, SetLog.logged_at.desc(), SetLog.set_number.desc()
        )
    )
    return {
        row.exercise_id: LastResult(
            reps=row.reps, weight_kg=row.weight_kg, seconds=row.seconds, logged_at=row.logged_at
        )
        for row in rows
    }


async def _detail(session: AsyncSession, workout: PlannedWorkout) -> WorkoutDetail:
    plan_user = await session.scalar(select(Plan.user_id).where(Plan.id == workout.plan_id))
    assert plan_user is not None
    exercise_ids = {row.exercise_id for row in workout.exercises}
    last = await last_results(session, plan_user, exercise_ids)
    targets = await targets_of(session, plan_user, exercise_ids)
    parts: dict[WorkoutPart, list[PlannedExerciseRead]] = {part: [] for part in WorkoutPart}
    for row in workout.exercises:  # already in position order
        parts[row.part].append(_exercise_read(row, workout, last, targets))
    return WorkoutDetail(
        **_summary(workout).model_dump(),
        plan_id=workout.plan_id,
        main_minutes=workout.main_minutes,
        warm_up=parts[WorkoutPart.WARM_UP],
        main=parts[WorkoutPart.MAIN],
        finisher=parts[WorkoutPart.FINISHER],
        cool_down=parts[WorkoutPart.COOL_DOWN],
    )


async def load_workout(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID, *, lock: bool = False
) -> PlannedWorkout:
    """A workout of this user's, any plan (old ones are history), with its exercises."""
    query = (
        select(PlannedWorkout)
        .join(Plan)
        .where(PlannedWorkout.id == workout_id, Plan.user_id == user_id)
        .options(
            selectinload(PlannedWorkout.exercises).selectinload(PlannedWorkoutExercise.exercise)
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        # FOR UPDATE: a second request for the same row waits until we commit.
        query = query.with_for_update(of=PlannedWorkout)
    workout = await session.scalar(query)
    if workout is None:
        raise WorkoutNotFoundError
    return workout


async def get_current_plan(session: AsyncSession, user_id: uuid.UUID) -> PlanRead:
    plan = await current_plan(session, user_id)
    if plan is None:
        raise PlanNotFoundError
    return _plan_read(plan)


async def get_next_workout(session: AsyncSession, user_id: uuid.UUID) -> WorkoutDetail:
    plan = await current_plan(session, user_id)
    if plan is None:
        raise PlanNotFoundError
    upcoming = next_workout(plan)
    if upcoming is None:
        raise BlockCompleteError
    return await _detail(session, await load_workout(session, user_id, upcoming.id))


async def get_workout(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID
) -> WorkoutDetail:
    return await _detail(session, await load_workout(session, user_id, workout_id))


# --- building and saving a block ----------------------------------------------------------


async def exercise_library(session: AsyncSession) -> list[Exercise]:
    # Sorted by slug so the generator always sees the same order (it is deterministic,
    # but its tie-breaks shouldn't depend on how Postgres happens to return rows).
    return list(await session.scalars(select(Exercise).order_by(Exercise.slug)))


async def _test_still_needed(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """The strength test stays in every new block until a test workout is finished."""
    finished_a_test = await session.scalar(
        select(
            exists()
            .where(PlannedWorkoutExercise.is_test)
            .where(PlannedWorkoutExercise.planned_workout_id == PlannedWorkout.id)
            .where(PlannedWorkout.status == WorkoutStatus.DONE)
            .where(PlannedWorkout.plan_id == Plan.id)
            .where(Plan.user_id == user_id)
        )
    )
    return not finished_a_test


async def rungs_of(session: AsyncSession, user_id: uuid.UUID) -> dict[MovementSlot, int]:
    """Where the strength test placed this user, per movement (ADR 0018)."""
    rows = await session.scalars(select(MovementRung).where(MovementRung.user_id == user_id))
    return {row.movement: row.difficulty for row in rows}


async def excluded_of(session: AsyncSession, user_id: uuid.UUID) -> frozenset[str]:
    """Slugs this user swapped out because they hurt (ADR 0020): never picked again."""
    rows = await session.scalars(
        select(Exercise.slug)
        .join(SwappedOutExercise, SwappedOutExercise.exercise_id == Exercise.id)
        .where(SwappedOutExercise.user_id == user_id)
    )
    return frozenset(rows)


async def _next_block_number(session: AsyncSession, user_id: uuid.UUID) -> int:
    last = await session.scalar(select(func.max(Plan.block_number)).where(Plan.user_id == user_id))
    return (last or 0) + 1


def _exercise_rows(workout: Workout, ids: dict[str, uuid.UUID]) -> list[PlannedWorkoutExercise]:
    parts: tuple[tuple[WorkoutPart, Sequence[PlannedExercise]], ...] = (
        (WorkoutPart.WARM_UP, workout.warm_up),
        (WorkoutPart.MAIN, workout.exercises),
        (WorkoutPart.FINISHER, workout.finisher),
        (WorkoutPart.COOL_DOWN, workout.cool_down),
    )
    return [
        PlannedWorkoutExercise(
            part=part,
            position=position,
            exercise_id=ids[e.slug],
            sets=e.sets,
            reps_min=e.reps_min,
            reps_max=e.reps_max,
            seconds=e.seconds,
            rest_seconds=e.rest_seconds,
            reps_in_reserve=e.reps_in_reserve,
            effort=e.effort,
            group_number=e.group,
            practice_sets=e.practice_sets,
            is_test=e.test,
        )
        for part, items in parts
        for position, e in enumerate(items, start=1)
    ]


async def _add_plan(session: AsyncSession, user_id: uuid.UUID, answers: PlanAnswers) -> Plan:
    """Generate the next block from these answers and add it (the caller commits)."""
    library = await exercise_library(session)
    block_number = await _next_block_number(session, user_id)
    routine = choose_routine(answers)
    block = build_block(
        answers,
        routine,
        library,
        BUILD_WEEKS,
        first_block=await _test_still_needed(session, user_id),
        block_number=block_number,
        recovery_week=True,
        rungs=await rungs_of(session, user_id),
        excluded=await excluded_of(session, user_id),
    )
    ids = {exercise.slug: exercise.id for exercise in library}
    workouts = [
        PlannedWorkout(
            position=position,
            week=week_number,
            kind=workout.kind,
            letter=workout.letter,
            title=workout.title,
            format=workout.format,
            recovery=workout.recovery,
            main_minutes=workout.main_minutes,
            total_minutes=workout.total_minutes,
            exercises=_exercise_rows(workout, ids),
        )
        for position, (week_number, workout) in enumerate(
            ((n, w) for n, week in enumerate(block, start=1) for w in week), start=1
        )
    ]
    plan = Plan(
        user_id=user_id,
        block_number=block_number,
        routine_kind=routine.kind,
        reasons=list(routine.reasons),
        weekdays=list(routine.weekdays),
        uses_push_pull_legs=routine.uses_push_pull_legs,
        weeks=len(block),
        generated_from=answers.to_json(),
        workouts=workouts,
    )
    session.add(plan)
    await session.flush()
    return plan


def _end(plan: Plan, reason: PlanEndReason) -> None:
    plan.ended_at = datetime.now(UTC)
    plan.end_reason = reason


async def start_plan(session: AsyncSession, user_id: uuid.UUID) -> PlanRead:
    """The first block after onboarding, or the next block once this one is finished."""
    profile = await session.get(Profile, user_id)
    if profile is None:
        raise ProfileRequiredError
    if profile.safety_screened_at is None:
        raise SafetyScreenRequiredError

    current = await current_plan(session, user_id)
    if current is not None:
        if next_workout(current) is not None:
            raise PlanInProgressError
        _end(current, PlanEndReason.FINISHED)
        # Send the UPDATE first: the new current plan can't exist alongside this one.
        await session.flush()
    try:
        await _add_plan(session, user_id, PlanAnswers.of(profile))
        await session.commit()
    except IntegrityError as exc:
        # Two requests at once (a double tap): the one-current-plan index stopped the
        # second, so the first one's plan stands.
        await session.rollback()
        raise PlanInProgressError from exc
    return await get_current_plan(session, user_id)


async def is_out_of_date(session: AsyncSession, profile: Profile) -> bool:
    """The current plan was built from different answers than the profile has now."""
    generated_from = await session.scalar(
        select(Plan.generated_from).where(Plan.user_id == profile.user_id, Plan.ended_at.is_(None))
    )
    return generated_from is not None and generated_from != PlanAnswers.of(profile).to_json()


async def _untouched(session: AsyncSession, plan: Plan) -> bool:
    """Nothing done, skipped or started: no history would be lost by deleting it."""
    if any(w.status != WorkoutStatus.PENDING for w in plan.workouts):
        return False
    started = await session.scalar(
        select(exists().where(WorkoutSession.planned_workout_id.in_([w.id for w in plan.workouts])))
    )
    return not started


async def replace_if_answers_changed(session: AsyncSession, profile: Profile) -> bool:
    """New answers that change the plan → a fresh block right away (ADR 0017).

    Call before committing the profile, after finishing any open session (the sessions
    service does that, ADR 0018). Does nothing for users without a plan, or when
    only things the plan doesn't use changed (obstacles). Returns True if replaced.

    A plan nobody has touched yet (every workout pending) is simply rebuilt: it is
    deleted and its block number reused. That's onboarding screen 13, where the
    shoulder-day or bro-split answer comes after the first plan is shown.
    """
    current = await current_plan(session, profile.user_id)
    answers = PlanAnswers.of(profile)
    if current is None or current.generated_from == answers.to_json():
        return False
    if await _untouched(session, current):
        await session.delete(current)
    else:
        _end(current, PlanEndReason.ANSWERS_CHANGED)
    await session.flush()
    await _add_plan(session, profile.user_id, answers)
    return True


# --- the queue ------------------------------------------------------------------------


def _as_planned(row: PlannedWorkoutExercise) -> PlannedExercise:
    exercise = row.exercise
    return PlannedExercise(
        slug=exercise.slug,
        name=exercise.name,
        movement=exercise.movement_slot,
        sets=row.sets,
        reps_min=row.reps_min,
        reps_max=row.reps_max,
        seconds=row.seconds,
        rest_seconds=row.rest_seconds,
        reps_in_reserve=row.reps_in_reserve,
        group=row.group_number,
        effort=row.effort,
        practice_sets=row.practice_sets,
        test=row.is_test,
    )


async def _move_test(session: AsyncSession, plan: Plan, skipped: PlannedWorkout) -> None:
    """The skipped workout was the strength test: the next strength workout that has test
    movements (push-up, squat, plank, pull-up) becomes it. Full body B, for example, has
    none, so the test goes to the next Full body A.

    Never into the recovery week. If none is left, the next block has the test instead.
    """
    candidates = [
        w.id
        for w in plan.workouts
        if w.position > skipped.position
        and w.status == WorkoutStatus.PENDING
        and w.kind in STRENGTH_KINDS
        and not w.recovery
    ]
    if not candidates:
        return
    library = await exercise_library(session)
    picker = Picker(
        PlanAnswers.from_json(plan.generated_from),
        library,
        plan.block_number,
        await rungs_of(session, plan.user_id),
        await excluded_of(session, plan.user_id),
    )
    ids = {exercise.slug: exercise.id for exercise in library}
    for workout_id in candidates:
        target = await load_workout(session, plan.user_id, workout_id, lock=True)
        main = [row for row in target.exercises if row.part == WorkoutPart.MAIN]
        marked = as_test_workout([_as_planned(row) for row in main], picker)
        if not any(new.test for new in marked):
            continue
        for row, new in zip(main, marked, strict=True):
            row.exercise_id = ids[new.slug]
            row.reps_min, row.reps_max, row.seconds = new.reps_min, new.reps_max, new.seconds
            row.practice_sets = new.practice_sets
            row.is_test = new.test
        return


async def skip_workout(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID
) -> PlanRead:
    """The Skip button on the next workout: no penalty, the queue moves on (ADR 0017)."""
    # Plan first: reloading it refreshes its workouts and would drop the exercises
    # loaded with the workout (lazy="raise" catches that in tests).
    plan = await current_plan(session, user_id)
    workout = await load_workout(session, user_id, workout_id, lock=True)
    upcoming = None if plan is None else next_workout(plan)
    if plan is None or upcoming is None or upcoming.id != workout.id:
        raise NotNextWorkoutError
    started = await session.scalar(
        select(exists().where(WorkoutSession.planned_workout_id == workout.id))
    )
    if started:
        raise SessionInProgressError
    workout.status = WorkoutStatus.SKIPPED
    workout.status_changed_at = datetime.now(UTC)
    if any(row.is_test for row in workout.exercises):
        await _move_test(session, plan, workout)
    await session.commit()
    return await get_current_plan(session, user_id)


async def rebuild_pending(
    session: AsyncSession, user_id: uuid.UUID, keep: Collection[uuid.UUID] = ()
) -> None:
    """Rebuild the current block's pending workouts with the user's rungs and swapped-out
    exercises (ADR 0018, 0019, 0020).

    The generator is deterministic, so building the block again with the same answers
    and block number changes only the slots the new rungs or swaps affect. Done and
    skipped workouts are history and stay as they were; so do started workouts and the
    ones in `keep` (today's, being swapped by hand). A strength test still waiting (it
    was skipped and moved, ADR 0017) stays in its workout. The caller commits.
    """
    plan = await current_plan(session, user_id)
    if plan is None:
        return
    pending = [
        w.id for w in plan.workouts if w.status == WorkoutStatus.PENDING and w.id not in keep
    ]
    # A started workout keeps its rows: its logged sets point at them.
    started = set(
        await session.scalars(
            select(WorkoutSession.planned_workout_id).where(
                WorkoutSession.planned_workout_id.in_(pending)
            )
        )
    )
    pending = [workout_id for workout_id in pending if workout_id not in started]
    if not pending:
        return
    workouts = list(
        await session.scalars(
            select(PlannedWorkout)
            .where(PlannedWorkout.id.in_(pending))
            .options(selectinload(PlannedWorkout.exercises))
            .execution_options(populate_existing=True)
        )
    )
    library = await exercise_library(session)
    answers = PlanAnswers.from_json(plan.generated_from)
    rungs = await rungs_of(session, user_id)
    excluded = await excluded_of(session, user_id)
    block = build_block(
        answers,
        choose_routine(answers),
        library,
        BUILD_WEEKS,
        first_block=False,
        block_number=plan.block_number,
        recovery_week=True,
        rungs=rungs,
        excluded=excluded,
    )
    rebuilt = [workout for week in block for workout in week]
    ids = {exercise.slug: exercise.id for exercise in library}
    picker = Picker(answers, library, plan.block_number, rungs, excluded)
    for workout in workouts:
        new = rebuilt[workout.position - 1]
        if new.kind != workout.kind:  # can't happen with the same answers; never guess
            continue
        if any(row.is_test for row in workout.exercises):
            new = replace(new, exercises=tuple(as_test_workout(new.exercises, picker)))
        # Old rows go first: (workout, part, position) is unique, so inserting the new
        # rows before the DELETE would clash.
        workout.exercises = []
        await session.flush()
        workout.exercises = _exercise_rows(new, ids)
        workout.main_minutes = new.main_minutes
        workout.total_minutes = new.total_minutes
