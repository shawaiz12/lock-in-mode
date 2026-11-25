"""Saving and serving plans: training blocks and the "next workout" queue (ADR 0017).

The plan generator (`training/`) is pure. This module feeds it the user's answers and
the exercise library rows, saves what it returns, and walks the queue.

Functions that change data own the transaction and commit, except
`replace_if_answers_changed`, which joins the caller's (the profile service's), so the
new answers and the new plan are saved together or not at all.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Comeback,
    Exercise,
    ExerciseTarget,
    IntervalStep,
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
    FitnessLevel,
    MovementSlot,
    PlanEndReason,
    WorkoutFormat,
    WorkoutPart,
    WorkoutStatus,
)
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.plan import (
    ComebackRead,
    LastResult,
    LevelUpRead,
    PlannedExerciseRead,
    PlanRead,
    WorkoutDetail,
    WorkoutSummary,
)
from lock_in_mode_api.services import comeback as comeback_service
from lock_in_mode_api.services import events
from lock_in_mode_api.services import level_up as level_up_service
from lock_in_mode_api.training import comeback as comeback_rules
from lock_in_mode_api.training import intervals as interval_rules
from lock_in_mode_api.training import level_up as level_up_rules
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import (
    BUILD_WEEKS,
    PlanAnswers,
    PlannedExercise,
    Workout,
)
from lock_in_mode_api.training.progression import Planned, Served, Target, serve, weight_step
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


class LevelUpNotOfferedError(Exception):
    """ "level_up": true, but no move up is on offer now (ADR 0022). Callers answer 409."""


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


def next_workout(
    plan: Plan, *, recovery_dropped: bool = False, started: Collection[uuid.UUID] = ()
) -> PlannedWorkout | None:
    """The first pending workout. `recovery_dropped`: a break replaces the waiting recovery
    week (ADR 0021), so recovery workouts nobody has started are passed over."""
    for workout in plan.workouts:
        if workout.status != WorkoutStatus.PENDING:
            continue
        if recovery_dropped and workout.recovery and workout.id not in started:
            continue
        return workout
    return None


@dataclass(frozen=True)
class Queue:
    """The queue as the user sees it now (ADR 0017, 0021): the next workout, the comeback
    that applies, and the comeback week each eased workout is in.

    `weeks`: per eased workout, (how many weeks its comeback lasts, its week).
    `recovery_dropped`: back after 14+ days with only the recovery week left, so the
    block counts as complete and the recovery week is dropped when they move on.
    `started`: workouts with an open session.
    """

    upcoming: PlannedWorkout | None
    comeback: comeback_service.Now | None
    weeks: dict[uuid.UUID, tuple[int, int]]
    recovery_dropped: bool
    started: frozenset[uuid.UUID]


async def queue_of(session: AsyncSession, plan: Plan, *, now: datetime | None = None) -> Queue:
    """Work out the queue. Reads only; call after loading the plan, before loading any
    workout (reloading the plan would drop a workout's exercises).

    `now`: the moment to work it out for. A workout started offline and synced later
    (ADR 0033) asks as of when it was started, so a break is judged by when they trained.
    """
    comeback = await comeback_service.find(session, plan.user_id, now=now)
    rows = await session.execute(
        select(WorkoutSession, Comeback.weeks)
        .outerjoin(Comeback, Comeback.id == WorkoutSession.comeback_id)
        .where(WorkoutSession.planned_workout_id.in_([w.id for w in plan.workouts]))
    )
    sessions: dict[uuid.UUID, tuple[WorkoutSession, int | None]] = {
        s.planned_workout_id: (s, comeback_weeks) for s, comeback_weeks in rows
    }
    started = frozenset(wid for wid, (s, _) in sessions.items() if s.finished_at is None)
    pending = [w for w in plan.workouts if w.status == WorkoutStatus.PENDING]
    due = comeback is not None and comeback.due
    recovery_dropped = due and all(w.recovery for w in pending)

    weeks: dict[uuid.UUID, tuple[int, int]] = {}
    for workout_id, (s, comeback_weeks) in sessions.items():
        # Done, or started: it keeps the numbers it started with (eased or not).
        if s.comeback_week is not None and comeback_weeks is not None:
            weeks[workout_id] = (comeback_weeks, s.comeback_week)
    index = 0  # how many comeback workouts come before this one
    for workout in pending:
        if recovery_dropped and workout.recovery and workout.id not in started:
            continue
        found = sessions.get(workout.id)
        if found is not None and not due:
            if comeback is not None and found[0].comeback_id == comeback.saved_id:
                index += 1  # started in this comeback: it takes the next place
            continue
        weeks.pop(workout.id, None)  # due: a stale open workout joins the new comeback
        if comeback is None or workout.recovery:
            continue  # the recovery week is light already: not eased again, not counted
        week = comeback.week_of(index)
        if week is None:
            break
        weeks[workout.id] = (comeback.weeks, week)
        index += 1
    upcoming = next_workout(plan, recovery_dropped=recovery_dropped, started=started)
    return Queue(upcoming, comeback, weeks, recovery_dropped, started)


def drop_recovery(plan: Plan, queue: Queue) -> None:
    """The break was the rest: the waiting recovery week goes (ADR 0021). Not a skip."""
    if not queue.recovery_dropped:
        return
    now = datetime.now(UTC)
    for workout in plan.workouts:
        if (
            workout.status == WorkoutStatus.PENDING
            and workout.recovery
            and workout.id not in queue.started
        ):
            workout.status = WorkoutStatus.REPLACED_BY_BREAK
            workout.status_changed_at = now


def _comeback_read(queue: Queue) -> ComebackRead | None:
    comeback = queue.comeback
    if comeback is None:
        return None
    eased = queue.weeks.get(queue.upcoming.id) if queue.upcoming else None
    return ComebackRead(
        away_days=comeback.away_days,
        weeks=comeback.weeks,
        week=eased[1] if eased else (comeback.week_of(0) or comeback.weeks),
        workouts_left=comeback.workouts_left,
        started=not comeback.due,
    )


async def level_up_offer(
    session: AsyncSession, user_id: uuid.UUID, queue: Queue, *, describe: bool = True
) -> level_up_service.Offer | None:
    """ "Ready for more?" is asked only at block complete, and never during a comeback
    (ADR 0022). `describe`: fill in what changes, by building the next week both ways."""
    if queue.upcoming is not None or queue.comeback is not None:
        return None
    offer = await level_up_service.offer_for(session, user_id)
    if offer is None or not describe:
        return offer
    profile = await session.get(Profile, user_id)
    assert profile is not None
    library = await exercise_library(session)
    rungs = await rungs_of(session, user_id)
    excluded = await excluded_of(session, user_id)
    number = await _next_block_number(session, user_id)
    first_block = await _test_still_needed(session, user_id)

    def shape(level: FitnessLevel) -> level_up_rules.WeekShape:
        # Built exactly as POST /plans would build the next block (see _add_plan).
        answers = replace(PlanAnswers.of(profile), level=level)
        block = build_block(
            answers,
            choose_routine(answers),
            library,
            BUILD_WEEKS,
            first_block=first_block,
            block_number=number,
            rungs=rungs,
            excluded=excluded,
        )
        return level_up_rules.week_shape(block[0])

    lines = level_up_rules.what_changes(
        shape(profile.level),
        shape(offer.to),
        minutes=profile.minutes_per_session,
        low_intensity=profile.needs_low_intensity,
        intervals=(
            await interval_timing(session, user_id, profile.level, comeback_eased=False),
            interval_rules.start_timing(offer.to),
        ),
    )
    return replace(offer, what_changes=tuple(lines))


def _level_up_read(offer: level_up_service.Offer | None) -> LevelUpRead | None:
    if offer is None:
        return None
    return LevelUpRead(
        to=offer.to,
        reason=offer.reason,
        good_weeks=offer.good_weeks,
        what_changes=list(offer.what_changes),
        check_with_doctor=offer.check_with_doctor,
    )


def _plan_read(plan: Plan, queue: Queue, offer: level_up_service.Offer | None = None) -> PlanRead:
    upcoming = queue.upcoming
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
        comeback=_comeback_read(queue),
        level_up=_level_up_read(offer),
        workouts=[_summary(w, queue.weeks.get(w.id, (0, None))[1]) for w in plan.workouts],
    )


def _summary(workout: PlannedWorkout, comeback_week: int | None) -> WorkoutSummary:
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
        comeback_week=comeback_week,
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


def is_interval(row: PlannedWorkoutExercise, workout: PlannedWorkout) -> bool:
    """HIIT and finisher rounds (ADR 0023): the main block of an intervals workout, and
    every finisher. Rows swapped out mid-workout keep their numbers."""
    if row.swapped_out or row.is_test or row.seconds is None or row.reps_in_reserve is not None:
        return False
    return row.part == WorkoutPart.FINISHER or (
        row.part == WorkoutPart.MAIN and workout.format == WorkoutFormat.INTERVALS
    )


async def saved_interval_step(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[FitnessLevel, interval_rules.State] | None:
    """The user's saved interval step and runs, and the level they belong to."""
    row = (
        await session.execute(
            select(
                IntervalStep.level,
                IntervalStep.step,
                IntervalStep.good_runs,
                IntervalStep.short_runs,
            ).where(IntervalStep.user_id == user_id)
        )
    ).first()
    if row is None:
        return None
    return row.level, interval_rules.State(row.step, row.good_runs, row.short_runs)


async def interval_timing(
    session: AsyncSession, user_id: uuid.UUID, level: FitnessLevel, *, comeback_eased: bool
) -> interval_rules.Timing:
    """Work and rest for this user's next intervals at this level (ADR 0023)."""
    state = interval_rules.state_for(level, await saved_interval_step(session, user_id))
    return interval_rules.timing(
        interval_rules.served_step(state.step, comeback_eased=comeback_eased)
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
    ease: comeback_rules.Ease | None = None,
    timing: interval_rules.Timing | None = None,
) -> PlannedExerciseRead:
    """Pending workouts show today's targets; done and skipped ones show what was saved.

    `ease`: the workout is a comeback workout (ADR 0021). Strength work is served lighter
    (the saved progress stays as it is), intervals and finishers a little easier.
    `timing`: the user's interval work and rest (ADR 0023), for HIIT and finisher rows.
    """
    pending = workout.status == WorkoutStatus.PENDING
    now = Served(row.sets, row.reps_min, row.reps_max, row.seconds, None)
    rest = row.rest_seconds
    if pending and timing is not None and is_interval(row, workout):
        now = replace(now, seconds=timing.work)
        rest = timing.rest
    if pending and progresses(row):
        now = served(row, workout, targets.get(row.exercise_id))
    previous = last.get(row.exercise_id)
    weight = now.weight_kg
    if weight is None and previous is not None and row.reps_in_reserve is not None:
        weight = previous.weight_kg
    effort = row.effort
    if pending and ease is not None and progresses(row):
        exercise = row.exercise
        now = comeback_rules.ease(
            replace(now, weight_kg=weight),
            ease,
            planned_reps_min=row.reps_min,
            timed=exercise.is_timed,
            weight_step=weight_step(
                exercise.equipment, exercise.also_needs, exercise.movement_slot
            ),
        )
        weight = now.weight_kg
    elif (
        pending
        and ease is not None
        and effort is not None
        and row.part in (WorkoutPart.MAIN, WorkoutPart.FINISHER)
        and not row.is_test
        and not row.swapped_out
    ):
        effort = comeback_rules.eased_effort(effort, ease)
    return PlannedExerciseRead(
        id=row.id,
        exercise=ExerciseRef.model_validate(row.exercise),
        sets=now.sets,
        reps_min=now.reps_min,
        reps_max=now.reps_max,
        seconds=now.seconds,
        rest_seconds=rest,
        reps_in_reserve=row.reps_in_reserve,
        effort=effort,
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


async def _detail(
    session: AsyncSession,
    workout: PlannedWorkout,
    comeback: tuple[int, int] | None = None,
) -> WorkoutDetail:
    """`comeback`: (how many weeks its comeback lasts, its week) for a comeback workout."""
    found = (
        await session.execute(
            select(Plan.user_id, Plan.generated_from).where(Plan.id == workout.plan_id)
        )
    ).one()
    plan_user = found.user_id
    exercise_ids = {row.exercise_id for row in workout.exercises}
    last = await last_results(session, plan_user, exercise_ids)
    targets = await targets_of(session, plan_user, exercise_ids)
    ease = None
    if comeback is not None and workout.status == WorkoutStatus.PENDING:
        ease = comeback_rules.ease_for(*comeback)
    timing = None
    if workout.status == WorkoutStatus.PENDING and any(
        is_interval(row, workout) for row in workout.exercises
    ):
        timing = await interval_timing(
            session,
            plan_user,
            PlanAnswers.from_json(found.generated_from).level,
            comeback_eased=ease is not None and ease.effort_drop > 0,
        )
    parts: dict[WorkoutPart, list[PlannedExerciseRead]] = {part: [] for part in WorkoutPart}
    for row in workout.exercises:  # already in position order
        parts[row.part].append(_exercise_read(row, workout, last, targets, ease, timing))
    return WorkoutDetail(
        **_summary(workout, comeback[1] if comeback else None).model_dump(),
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
    queue = await queue_of(session, plan)
    return _plan_read(plan, queue, await level_up_offer(session, user_id, queue))


async def get_next_workout(session: AsyncSession, user_id: uuid.UUID) -> WorkoutDetail:
    plan = await current_plan(session, user_id)
    if plan is None:
        raise PlanNotFoundError
    queue = await queue_of(session, plan)
    if queue.upcoming is None:
        raise BlockCompleteError
    workout = await load_workout(session, user_id, queue.upcoming.id)
    return await _detail(session, workout, queue.weeks.get(workout.id))


async def get_workout(
    session: AsyncSession, user_id: uuid.UUID, workout_id: uuid.UUID
) -> WorkoutDetail:
    # Plan first: reloading it would drop the exercises loaded with the workout.
    plan = await current_plan(session, user_id)
    queue = await queue_of(session, plan) if plan is not None else None
    workout = await load_workout(session, user_id, workout_id)
    comeback = None
    if queue is not None and plan is not None and workout.plan_id == plan.id:
        comeback = queue.weeks.get(workout.id)
    else:  # an older block: history only, nothing is eased any more
        found = (
            await session.execute(
                select(Comeback.weeks, WorkoutSession.comeback_week)
                .join(Comeback, Comeback.id == WorkoutSession.comeback_id)
                .where(WorkoutSession.planned_workout_id == workout.id)
            )
        ).first()
        if found is not None and found[1] is not None:
            comeback = (found[0], found[1])
    return await _detail(session, workout, comeback)


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


async def start_plan(
    session: AsyncSession, user_id: uuid.UUID, *, level_up: bool = False
) -> PlanRead:
    """The first block after onboarding, or the next block once this one is finished.

    `level_up`: "Ready for more?" answered yes (ADR 0022). The profile moves up to the
    offered level and the new block is built from it, in the same transaction.
    """
    profile = await session.get(Profile, user_id)
    if profile is None:
        raise ProfileRequiredError
    if profile.safety_screened_at is None:
        raise SafetyScreenRequiredError

    current = await current_plan(session, user_id)
    if current is None and level_up:
        raise LevelUpNotOfferedError  # nothing is offered before the first block
    if current is not None:
        queue = await queue_of(session, current)
        if queue.upcoming is not None:
            raise PlanInProgressError
        # Usually recorded already by the last finish or skip. Not when a break replaced
        # the recovery week that was left (ADR 0021): then the block ended by time alone.
        # Before the level changes below, so the offer is read as the user saw it.
        await _record_block_complete(session, user_id, current, queue)
        if level_up:
            offer = await level_up_offer(session, user_id, queue, describe=False)
            if offer is None:
                raise LevelUpNotOfferedError
            from_level = profile.level
            profile.level = FitnessLevel(offer.to)
            await events.level_up_accepted(
                session, user_id, from_level=from_level, to=profile.level
            )
        drop_recovery(current, queue)  # back after a break: the break was the rest
        _end(current, PlanEndReason.FINISHED)
        # Send the UPDATE first: the new current plan can't exist alongside this one.
        await session.flush()
    try:
        plan = await _add_plan(session, user_id, PlanAnswers.of(profile))
        await events.plan_started(
            session,
            user_id,
            block=plan.block_number,
            level=profile.level,
            reason="first" if current is None else "next_block",
        )
        await session.commit()
    except IntegrityError as exc:
        # Two requests at once (a double tap): the one-current-plan index stopped the
        # second, so the first one's plan stands.
        await session.rollback()
        raise PlanInProgressError from exc
    return await get_current_plan(session, user_id)


async def note_block_complete(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """After a workout is finished or skipped: if that was the block's last one, record
    `block_complete` (once per block, ADR 0025), with whether "Ready for more?" will be
    asked. Returns whether the block is complete now (the finish screen's
    `block_complete`). Call after flushing the change; the caller commits."""
    plan = await current_plan(session, user_id)
    if plan is None:
        return False
    queue = await queue_of(session, plan)
    await _record_block_complete(session, user_id, plan, queue)
    return queue.upcoming is None


async def _record_block_complete(
    session: AsyncSession, user_id: uuid.UUID, plan: Plan, queue: Queue
) -> None:
    if queue.upcoming is not None:
        return
    offer = await level_up_offer(session, user_id, queue, describe=False)
    await events.block_complete(
        session, user_id, block=plan.block_number, level_up_offered=offer is not None
    )


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
    untouched = await _untouched(session, current)
    if untouched:
        await session.delete(current)
    else:
        _end(current, PlanEndReason.ANSWERS_CHANGED)
    await session.flush()
    plan = await _add_plan(session, profile.user_id, answers)
    if not untouched:  # an untouched plan rebuilt keeps its block: not a new start
        await events.plan_started(
            session,
            profile.user_id,
            block=plan.block_number,
            level=profile.level,
            reason="answers_changed",
        )
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
    upcoming = None if plan is None else (await queue_of(session, plan)).upcoming
    workout = await load_workout(session, user_id, workout_id, lock=True)
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
    await session.flush()
    await note_block_complete(session, user_id)
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
