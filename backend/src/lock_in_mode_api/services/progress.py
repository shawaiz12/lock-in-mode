"""Progression after a workout (ADR 0019): step exercises up or back, the feedback
streaks, the early recovery week, and the interval step (ADR 0023). The rules are pure
(training/progression.py, training/intervals.py); this module feeds them the logged sets
and saves what they return.

Nothing here commits: the sessions service calls it while finishing a workout, so the
finish and the progress it causes are saved together or not at all.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lock_in_mode_api.models import (
    Exercise,
    ExerciseTarget,
    IntervalStep,
    MovementRung,
    Plan,
    PlannedWorkout,
    PlannedWorkoutExercise,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import (
    Feedback,
    FitnessLevel,
    Location,
    ProgressChange,
    WorkoutFormat,
    WorkoutPart,
    WorkoutStatus,
)
from lock_in_mode_api.schemas.exercise import ExerciseRef
from lock_in_mode_api.schemas.session import IntervalProgress, Progress
from lock_in_mode_api.services import plans as plan_service
from lock_in_mode_api.training import intervals as interval_rules
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import PlanAnswers, is_weighted
from lock_in_mode_api.training.progression import (
    Logged,
    Move,
    Served,
    Step,
    Target,
    after_workout,
    earns_recovery,
    neighbour_rungs,
    step_back,
    step_up,
    streak_fires,
    weight_step,
)

C = ProgressChange
UP = frozenset({C.HEAVIER, C.EXTRA_SET, C.LONGER_HOLD, C.HARDER_MOVE})
BACK = frozenset({C.LIGHTER, C.FEWER_SETS, C.SHORTER_HOLD, C.EASIER_MOVE})
STREAK_LOOKBACK = 20  # feedback taps read to find the current run


@dataclass
class Outcome:
    """What a finished workout changed. `rungs_changed`: the caller rebuilds the block."""

    progress: list[Progress] = field(default_factory=list)
    rungs_changed: bool = False
    intervals: IntervalProgress | None = None


@dataclass(frozen=True)
class _Item:
    """One exercise to step, with everything the rules need."""

    exercise: Exercise
    move: Move
    served: Served
    target: Target | None
    weight: float | None  # for whole-plan steps: what they last lifted
    logged: dict[int, Logged]


class _Ladders:
    """This user's bodyweight ladder per movement (home only), to find the next rung."""

    def __init__(
        self, answers: PlanAnswers, library: Sequence[Exercise], excluded: frozenset[str]
    ) -> None:
        self.home = answers.location == Location.HOME
        self.picker = Picker(answers, library, excluded=excluded)

    def move(self, exercise: Exercise, circuit: bool) -> Move:
        easier = harder = None
        if self.home and not is_weighted(exercise):
            ladder = [
                e.difficulty
                for e in self.picker.by_movement.get(exercise.movement_slot, [])
                if not is_weighted(e)
            ]
            easier, harder = neighbour_rungs(exercise.difficulty, ladder)
        return Move(
            timed=exercise.is_timed,
            weight_step=weight_step(
                exercise.equipment, exercise.also_needs, exercise.movement_slot
            ),
            harder_rung=harder,
            easier_rung=easier,
            can_change_sets=not circuit,
        )


# --- saving ---------------------------------------------------------------------------------


async def _save_target(
    session: AsyncSession, user_id: uuid.UUID, exercise_id: uuid.UUID, target: Target
) -> None:
    values = {
        "weight_kg": target.weight_kg,
        "set_change": target.set_change,
        "seconds": target.seconds,
        "reps_bonus": target.reps_bonus,
        "short_runs": target.short_runs,
    }
    await session.execute(
        insert(ExerciseTarget)
        .values(user_id=user_id, exercise_id=exercise_id, **values)
        .on_conflict_do_update(
            index_elements=[ExerciseTarget.user_id, ExerciseTarget.exercise_id],
            set_={**values, "updated_at": func.now()},
        )
    )


async def _save_rung(
    session: AsyncSession, user_id: uuid.UUID, exercise: Exercise, rung: int, result: int
) -> None:
    """Move the movement's rung: the rebuilt block then picks the move at that difficulty.
    `result` is kept from the strength test if there was one."""
    await session.execute(
        insert(MovementRung)
        .values(user_id=user_id, movement=exercise.movement_slot, difficulty=rung, result=result)
        .on_conflict_do_update(
            index_elements=[MovementRung.user_id, MovementRung.movement],
            set_={"difficulty": rung, "updated_at": func.now()},
        )
    )


def _progress(exercise: Exercise, step: Step) -> Progress:
    assert step.change is not None
    return Progress(
        exercise=ExerciseRef.model_validate(exercise),
        change=step.change,
        weight_kg=step.target.weight_kg,
        seconds=step.target.seconds,
        set_change=step.target.set_change,
    )


async def _apply(
    session: AsyncSession, user_id: uuid.UUID, item: _Item, step: Step, outcome: Outcome
) -> None:
    """Save what changed. An unchanged target writes nothing: no row means "as planned"."""
    if step.target != (item.target or Target()):
        await _save_target(session, user_id, item.exercise.id, step.target)
    if step.rung is not None:
        best = max(
            (s.reps if s.reps is not None else s.seconds or 0 for s in item.logged.values()),
            default=0,
        )
        await _save_rung(session, user_id, item.exercise, step.rung, best)
        outcome.rungs_changed = True
    if step.change is not None:
        outcome.progress.append(_progress(item.exercise, step))


# --- reading --------------------------------------------------------------------------------


async def _answers_streak(
    session: AsyncSession, workout_session: WorkoutSession
) -> Feedback | None:
    """Does this tap complete a pair of identical taps? Recovery weeks and comeback
    workouts (ADR 0021) don't count."""
    if workout_session.feedback is None:
        return None
    earlier = await session.scalars(
        select(WorkoutSession.feedback)
        .join(PlannedWorkout, PlannedWorkout.id == WorkoutSession.planned_workout_id)
        .where(
            WorkoutSession.user_id == workout_session.user_id,
            WorkoutSession.id != workout_session.id,
            WorkoutSession.finished_at.is_not(None),
            WorkoutSession.feedback.is_not(None),
            WorkoutSession.comeback_id.is_(None),
            PlannedWorkout.recovery.is_(False),
        )
        .order_by(WorkoutSession.finished_at.desc())
        .limit(STREAK_LOOKBACK)
    )
    return streak_fires([workout_session.feedback, *(f for f in earlier if f is not None)])


async def _rest_of_plan(
    session: AsyncSession, plan_id: uuid.UUID
) -> list[tuple[PlannedWorkoutExercise, PlannedWorkout]]:
    """Strength rows still to come in this block's build-up weeks, in queue order."""
    rows = await session.execute(
        select(PlannedWorkoutExercise, PlannedWorkout)
        .join(PlannedWorkout, PlannedWorkout.id == PlannedWorkoutExercise.planned_workout_id)
        .where(
            PlannedWorkout.plan_id == plan_id,
            PlannedWorkout.status == WorkoutStatus.PENDING,
            PlannedWorkout.recovery.is_(False),
            PlannedWorkoutExercise.part == WorkoutPart.MAIN,
            PlannedWorkoutExercise.reps_in_reserve.is_not(None),
            PlannedWorkoutExercise.is_test.is_(False),
        )
        .options(selectinload(PlannedWorkoutExercise.exercise))
        .order_by(PlannedWorkout.position, PlannedWorkoutExercise.position)
    )
    return [(row, workout) for row, workout in rows]


# --- the steps ------------------------------------------------------------------------------


async def after_finish(
    session: AsyncSession,
    workout_session: WorkoutSession,
    workout: PlannedWorkout,
    main: Sequence[PlannedWorkoutExercise],
) -> Outcome:
    """Step this workout's exercises (double progression, one tap, falling short), then
    the whole plan if this tap makes a pair. The recovery week changes nothing, and
    neither does a comeback workout after a break (ADR 0021): it was served lighter.

    `main`: the workout's main-block rows, read before anything rebuilds the block.
    """
    outcome = Outcome()
    if workout.recovery or workout_session.comeback_id is not None:
        return outcome
    user_id = workout_session.user_id
    generated_from = await session.scalar(
        select(Plan.generated_from).where(Plan.id == workout.plan_id)
    )
    assert generated_from is not None
    answers = PlanAnswers.from_json(generated_from)
    ladders = _Ladders(
        answers,
        await plan_service.exercise_library(session),
        await plan_service.excluded_of(session, user_id),
    )
    circuit = workout.format == WorkoutFormat.CIRCUIT
    rows = [row for row in main if plan_service.progresses(row)]
    targets = await plan_service.targets_of(session, user_id, {r.exercise_id for r in rows})

    by_row: dict[uuid.UUID, dict[int, Logged]] = {}
    for logged in workout_session.sets:
        by_row.setdefault(logged.planned_exercise_id, {})[logged.set_number] = Logged(
            logged.reps, logged.weight_kg, logged.seconds
        )

    streak = await _answers_streak(session, workout_session)
    feedback = workout_session.feedback
    stepped: set[uuid.UUID] = set()
    for row in rows:
        if row.exercise_id in stepped:
            continue
        target = targets.get(row.exercise_id)
        item = _Item(
            exercise=row.exercise,
            move=ladders.move(row.exercise, circuit),
            served=plan_service.served(row, workout, target),
            target=target,
            weight=None,
            logged=by_row.get(row.id, {}),
        )
        step = after_workout(item.move, target, item.served, item.logged, feedback)
        step = _with_streak(item, step, streak)
        await _apply(session, user_id, item, step, outcome)
        stepped.add(row.exercise_id)

    if streak is not None:
        await _step_the_rest(session, user_id, workout.plan_id, ladders, streak, stepped, outcome)
    outcome.intervals = await _step_intervals(
        session, workout_session, workout, answers.level, streak
    )
    return outcome


def _with_streak(item: _Item, step: Step, streak: Feedback | None) -> Step:
    """A pair of taps moves every exercise one notch, unless it already moved that way."""
    logged_weights = [s.weight_kg for s in item.logged.values() if s.weight_kg]
    weight = None if item.move.timed else (min(logged_weights) if logged_weights else None)
    if weight is None and not item.move.timed:
        weight = step.target.weight_kg
    if step.change in BACK:
        return step  # falling short wins: it's what they actually did
    if streak == Feedback.TOO_EASY and step.change not in UP:
        return step_up(item.move, step.target, item.served, weight)
    if streak == Feedback.TOO_HARD and step.change not in BACK:
        return step_back(item.move, step.target, item.served, weight)
    return step


async def _step_the_rest(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    ladders: _Ladders,
    streak: Feedback,
    stepped: set[uuid.UUID],
    outcome: Outcome,
) -> None:
    """The other exercises still in this block, if they've been done before: one notch."""
    upcoming = [
        (r, w) for r, w in await _rest_of_plan(session, plan_id) if r.exercise_id not in stepped
    ]
    ids = {row.exercise_id for row, _ in upcoming}
    targets = await plan_service.targets_of(session, user_id, ids)
    last = await plan_service.last_results(session, user_id, ids)
    for row, workout in upcoming:
        if row.exercise_id in stepped or (
            row.exercise_id not in targets and row.exercise_id not in last
        ):
            continue  # never done: nothing to step from
        stepped.add(row.exercise_id)
        target = targets.get(row.exercise_id)
        move = ladders.move(row.exercise, workout.format == WorkoutFormat.CIRCUIT)
        served = plan_service.served(row, workout, target)
        weight = None
        if not move.timed:
            weight = target.weight_kg if target is not None else None
            previous = last.get(row.exercise_id)
            if weight is None and previous is not None:
                weight = previous.weight_kg
        rule = step_up if streak == Feedback.TOO_EASY else step_back
        step = rule(move, target or Target(), served, weight)
        item = _Item(row.exercise, move, served, target, weight, {})
        await _apply(session, user_id, item, step, outcome)


async def bring_recovery_forward(
    session: AsyncSession, workout_session: WorkoutSession, plan_id: uuid.UUID, week: int
) -> bool:
    """ "Too hard" on more than half of this week's workouts: the rest of the build-up
    weeks make way and the recovery week is next (KB section 10). Returns True if so.
    Call after any rebuild: it changes statuses of the plan's pending workouts. Comeback
    workouts' taps don't count (ADR 0021).
    """
    if workout_session.feedback != Feedback.TOO_HARD or workout_session.comeback_id is not None:
        return False
    plan = await plan_service.current_plan(session, workout_session.user_id)
    if plan is None or plan.id != plan_id:
        return False
    this_week = [w.id for w in plan.workouts if w.week == week and not w.recovery]
    too_hard = await session.scalar(
        select(func.count())
        .select_from(WorkoutSession)
        .where(
            WorkoutSession.planned_workout_id.in_(this_week),
            WorkoutSession.feedback == Feedback.TOO_HARD,
            WorkoutSession.comeback_id.is_(None),
        )
    )
    if not earns_recovery(too_hard or 0, len(this_week)):
        return False
    later = [w for w in plan.workouts if w.status == WorkoutStatus.PENDING and not w.recovery]
    if not later:
        return False
    now = datetime.now(UTC)
    for workout in later:
        workout.status = WorkoutStatus.REPLACED_BY_RECOVERY
        workout.status_changed_at = now
    await session.flush()
    return True


# --- intervals (ADR 0023) -----------------------------------------------------------------


async def _plan_has_intervals(session: AsyncSession, plan_id: uuid.UUID) -> bool:
    """Any HIIT or finisher rounds in this block (low intensity plans have none)."""
    found = await session.scalar(
        select(func.count())
        .select_from(PlannedWorkoutExercise)
        .join(PlannedWorkout, PlannedWorkout.id == PlannedWorkoutExercise.planned_workout_id)
        .where(
            PlannedWorkout.plan_id == plan_id,
            PlannedWorkoutExercise.swapped_out.is_(False),
            (PlannedWorkoutExercise.part == WorkoutPart.FINISHER)
            | (
                (PlannedWorkoutExercise.part == WorkoutPart.MAIN)
                & (PlannedWorkout.format == WorkoutFormat.INTERVALS)
            ),
        )
    )
    return bool(found)


async def _step_intervals(
    session: AsyncSession,
    workout_session: WorkoutSession,
    workout: PlannedWorkout,
    level: FitnessLevel,
    pair: Feedback | None,
) -> IntervalProgress | None:
    """Count this workout's interval rounds and move the user's step (ADR 0023). A pair
    of taps moves it only for a user who has done intervals and still has them."""
    rows = {r.id: r for r in workout.exercises if plan_service.is_interval(r, workout)}
    planned = sum(r.sets for r in rows.values())
    ticked = sum(
        1
        for s in workout_session.sets
        if s.planned_exercise_id in rows and s.set_number <= rows[s.planned_exercise_id].sets
    )
    result = interval_rules.verdict(planned, ticked, workout_session.feedback)
    user_id = workout_session.user_id
    saved = await plan_service.saved_interval_step(session, user_id)
    state = interval_rules.state_for(level, saved)
    move = interval_rules.after_workout(level, state, result)
    done_before = saved is not None or result != interval_rules.Verdict.NOTHING
    if pair is not None and done_before and await _plan_has_intervals(session, workout.plan_id):
        move = interval_rules.with_pair(level, move, result, pair)
    if result == interval_rules.Verdict.NOTHING and move.direction is None:
        return None
    values = {
        "level": level,
        "step": move.state.step,
        "good_runs": move.state.good_runs,
        "short_runs": move.state.short_runs,
    }
    await session.execute(
        insert(IntervalStep)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[IntervalStep.user_id], set_={**values, "updated_at": func.now()}
        )
    )
    if move.direction is None:
        return None
    now = interval_rules.timing(move.state.step)
    return IntervalProgress(
        direction=move.direction.value, work_seconds=now.work, rest_seconds=now.rest
    )
