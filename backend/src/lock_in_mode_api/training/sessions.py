"""Stage 2 of the plan generator: build every workout of a block (ADR 0015, 0016, 0017).

routine (stage 1) + exercise library -> workouts with warm-up, main block, finisher and
cool-down, fitted to the user's minutes. Pure: no database. Rules: KB sections 2 (first
workout test), 3 (training variables), 5 (templates), 7 (HIIT and cardio), 8 (warm-up and
cool-down), 9 (fitting the session length) and 10 (the recovery week); rotation: ADR 0014.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from lock_in_mode_api.models.enums import (
    ExerciseType,
    FitnessLevel,
    Goal,
    MovementSlot,
    MuscleGroup,
    SessionKind,
    WorkoutFormat,
)
from lock_in_mode_api.training import conditioning
from lock_in_mode_api.training.picker import Picker
from lock_in_mode_api.training.plan_types import (
    MAIN_BLOCK_MINUTES,
    NO_LIMIT_SPLIT,
    RECOVERY_EFFORT_DROP,
    RECOVERY_MIN_EFFORT,
    RECOVERY_REPS_IN_RESERVE,
    SESSION_SPLIT,
    TITLES,
    BuildInputs,
    ExerciseInfo,
    PlannedExercise,
    Workout,
    is_weighted,
)
from lock_in_mode_api.training.routine import PlannedSession, Routine
from lock_in_mode_api.training.templates import STRENGTH_KINDS, Slot, template

__all__ = ["MAIN_BLOCK_MINUTES", "PlannedExercise", "Workout", "as_test_workout", "build_block"]

S = SessionKind
M = MovementSlot

SET_WORK_SECONDS = 40  # one set is about 40 s of work (KB section 9)
SUPERSET_TIME_FACTOR = 0.6  # a superset pair shares its rest: about 40% faster
CIRCUIT_ROUND_REST = 60
MIN_SETS = 2
PROTECTED_SLOTS = 3  # never drop the first three slots: they are the session
HARD_BODYWEIGHT = 4  # difficulty from which a bodyweight move counts as heavy

# First workout: the KB section 2 test moves. Bodyweight users do these exact moves with
# an open target; the results place them on each ladder. Weighted lifts: pick a weight.
TEST_MOVES = {
    M.HORIZONTAL_PUSH: "push-up",
    M.SQUAT: "bodyweight-squat",
    M.BRACE: "plank",
    M.VERTICAL_PULL: "pull-up",
}
CARDIO_FORMATS = {
    S.HIIT: WorkoutFormat.INTERVALS,
    S.STEADY_CARDIO: WorkoutFormat.CONTINUOUS,
    S.LONG_CARDIO: WorkoutFormat.CONTINUOUS,
    S.EASY_CARDIO: WorkoutFormat.CONTINUOUS,
    S.MOBILITY: WorkoutFormat.FLOW,
}


# --- sets, reps, rest and effort (KB section 3) --------------------------------------


@dataclass(frozen=True)
class _Numbers:
    sets: int
    reps: tuple[int, int]
    rest: int
    rest_floor: int
    rir: int


def _numbers(answers: BuildInputs, slot: Slot, exercise: ExerciseInfo, lead: bool) -> _Numbers:
    goal, level = answers.goal, answers.level
    beginner = level == FitnessLevel.BEGINNER
    small = exercise.exercise_type == ExerciseType.ISOLATION or not slot.main
    weighted = is_weighted(exercise)

    if answers.needs_low_intensity or goal == Goal.STAY_ACTIVE or slot.light or beginner:
        sets = MIN_SETS
    elif goal in (Goal.LOSE_FAT, Goal.STAMINA):
        sets = 2 if small else 3
    elif goal == Goal.STRENGTH:
        sets = 3 if small else 4
    elif small:
        sets = 3 if level == FitnessLevel.EXPERIENCED else 2
    else:
        sets = 4 if lead and level == FitnessLevel.EXPERIENCED else 3

    match goal:
        case Goal.STRENGTH if lead and weighted:
            numbers = _Numbers(sets, (5, 8) if beginner else (3, 6), 150, 120, 2)
        case Goal.STRENGTH:
            numbers = _Numbers(sets, (8, 12) if weighted else (6, 12), 75, 60, 2)
        case Goal.LOSE_FAT:
            numbers = _Numbers(sets, (8, 15) if weighted else (10, 20), 60, 45, 2)
        case Goal.STAMINA:
            numbers = _Numbers(sets, (12, 20), 30, 15, 3)
        case Goal.STAY_ACTIVE:
            numbers = _Numbers(sets, (8, 12), 60, 45, 3)
        case _ if not weighted and exercise.difficulty >= HARD_BODYWEIGHT:
            numbers = _Numbers(sets, (6, 12), 90, 60, 2)  # pull-ups, pistols: hard already
        case _ if not weighted:  # build muscle with bodyweight or bands: more reps
            numbers = _Numbers(sets, (15, 25) if small else (10, 20), 60 if small else 90, 45, 2)
        case _:
            reps = (6, 10) if lead else (10, 15) if small else (8, 12)
            numbers = _Numbers(sets, reps, 60 if small else 90, 45 if small else 60, 2)

    rir = numbers.rir
    if beginner:
        rir = 3  # learn the form before pushing (KB section 3)
    if answers.needs_low_intensity:
        rir = 4
    return replace(numbers, rir=rir)


def _timed_seconds(answers: BuildInputs) -> int:
    if answers.goal == Goal.STAMINA:
        return 40
    return {
        FitnessLevel.BEGINNER: 25,
        FitnessLevel.SOME_EXPERIENCE: 40,
        FitnessLevel.EXPERIENCED: 50,
    }[answers.level]


def _plan_exercise(
    answers: BuildInputs, slot: Slot, exercise: ExerciseInfo, lead: bool
) -> PlannedExercise:
    numbers = _numbers(answers, slot, exercise, lead)
    timed = exercise.is_timed
    return PlannedExercise(
        slug=exercise.slug,
        name=exercise.name,
        movement=exercise.movement_slot,
        sets=numbers.sets,
        reps_min=None if timed else numbers.reps[0],
        reps_max=None if timed else numbers.reps[1],
        seconds=_timed_seconds(answers) if timed else None,
        rest_seconds=numbers.rest,
        reps_in_reserve=numbers.rir,
        rest_floor=numbers.rest_floor,
    )


# --- format and time (KB section 9) --------------------------------------------------


def workout_format(kind: SessionKind, minutes: int | None) -> WorkoutFormat:
    if kind == S.CIRCUIT or minutes == 10:
        return WorkoutFormat.CIRCUIT
    if minutes == 20:
        return WorkoutFormat.SUPERSETS
    if minutes == 30:
        return WorkoutFormat.FIRST_STRAIGHT_THEN_SUPERSETS
    return WorkoutFormat.STRAIGHT_SETS


def _group(exercises: list[PlannedExercise], fmt: WorkoutFormat) -> list[PlannedExercise]:
    """Number the groups: alone, in pairs (supersets) or all together (circuit)."""
    grouped = []
    for index, exercise in enumerate(exercises):
        match fmt:
            case WorkoutFormat.CIRCUIT:
                group = 0
            case WorkoutFormat.SUPERSETS:
                group = index // 2
            case WorkoutFormat.FIRST_STRAIGHT_THEN_SUPERSETS:
                group = 0 if index == 0 else 1 + (index - 1) // 2
            case _:
                group = index
        grouped.append(replace(exercise, group=group))
    return grouped


def _work_seconds(exercise: PlannedExercise) -> int:
    return exercise.seconds if exercise.seconds is not None else SET_WORK_SECONDS


def timed_seconds(moves: Sequence[PlannedExercise]) -> float:
    """Intervals, continuous cardio, flows, warm-ups and cool-downs: work plus rest, per set."""
    return float(sum(m.sets * ((m.seconds or SET_WORK_SECONDS) + m.rest_seconds) for m in moves))


def estimate_seconds(exercises: Sequence[PlannedExercise], fmt: WorkoutFormat) -> float:
    """Main-block time: a set is ~40 s of work plus its rest; a pair shares its rest."""
    if not exercises:
        return 0.0
    if fmt in (WorkoutFormat.INTERVALS, WorkoutFormat.CONTINUOUS, WorkoutFormat.FLOW):
        return timed_seconds(exercises)
    if fmt == WorkoutFormat.CIRCUIT:
        rounds = exercises[0].sets
        per_round = sum(_work_seconds(e) + e.rest_seconds for e in exercises)
        return rounds * per_round + (rounds - 1) * CIRCUIT_ROUND_REST
    total = 0.0
    for group in sorted({e.group for e in exercises}):
        members = [e for e in exercises if e.group == group]
        seconds = sum(e.sets * (_work_seconds(e) + e.rest_seconds) for e in members)
        total += seconds * (SUPERSET_TIME_FACTOR if len(members) > 1 else 1)
    return total


# --- building one session ------------------------------------------------------------


def _circuit_settings(answers: BuildInputs, kind: SessionKind) -> tuple[int, int]:
    """(rounds, rest between exercises). 10-minute circuits run without rest."""
    rounds = 2 if answers.level == FitnessLevel.BEGINNER or answers.needs_low_intensity else 3
    rest = 30 if kind == S.CIRCUIT and answers.minutes_per_session != 10 else 0
    return rounds, rest


def _fit(
    exercises: list[tuple[int, PlannedExercise]],
    fmt: WorkoutFormat,
    budget_seconds: float | None,
) -> list[PlannedExercise]:
    """KB section 9, in order: drop slots (lowest priority first), cut sets (never below
    2), shorten rests to the low end. The three top-priority slots are never dropped.

    `exercises` holds (keep, exercise) pairs: lower `keep` is kept longer.
    """
    protected = sorted(keep for keep, _ in exercises)[:PROTECTED_SLOTS]

    def over(items: list[PlannedExercise]) -> bool:
        if budget_seconds is None:
            return False
        return estimate_seconds(_group(items, fmt), fmt) > budget_seconds

    kept = list(exercises)
    while over([e for _, e in kept]) and len(kept) > PROTECTED_SLOTS:
        worst = max(range(len(kept)), key=lambda i: (kept[i][0] not in protected, kept[i][0]))
        del kept[worst]
    items = [e for _, e in kept]
    for index in reversed(range(len(items))):
        while over(items) and items[index].sets > MIN_SETS:
            fewer = items[index].sets - 1
            if fmt == WorkoutFormat.CIRCUIT:  # rounds are shared by the whole circuit
                items = [replace(e, sets=fewer) for e in items]
            else:
                items[index] = replace(items[index], sets=fewer)
    for index in range(len(items)):
        if over(items):
            items[index] = replace(items[index], rest_seconds=items[index].rest_floor)
    return items


def _strength_main(
    answers: BuildInputs,
    kind: SessionKind,
    letter: str,
    picker: Picker,
    budget_seconds: float | None,
) -> list[PlannedExercise]:
    """The main block of a strength session: slots → picks → numbers → fitted."""
    fmt = workout_format(kind, answers.minutes_per_session)
    slots = template(kind, letter, answers.shoulder_day)

    used: set[str] = set()
    required: list[tuple[int, PlannedExercise]] = []
    optional: list[tuple[Slot, ExerciseInfo]] = []
    for position, slot in enumerate(slots):
        exercise = picker.pick(slot, used)
        if exercise is None:
            continue  # nothing fits (e.g. no kit for this isolation move): skip the slot
        used.add(exercise.slug)
        if slot.optional:
            optional.append((slot, exercise))
            continue
        lead = not required if answers.goal != Goal.STRENGTH else slot.main and len(required) < 2
        keep = position if slot.keep is None else slot.keep
        required.append((keep, _plan_exercise(answers, slot, exercise, lead)))

    if fmt == WorkoutFormat.CIRCUIT:
        rounds, rest = _circuit_settings(answers, kind)
        required = [
            (keep, replace(e, sets=rounds, rest_seconds=rest, rest_floor=rest))
            for keep, e in required
        ]

    exercises = _fit(required, fmt, budget_seconds)
    for slot, exercise in optional:  # "(if time)" slots: always with no limit, else if they fit
        extra = _plan_exercise(answers, slot, exercise, lead=False)
        if fmt == WorkoutFormat.CIRCUIT:
            extra = replace(extra, sets=exercises[0].sets, rest_seconds=exercises[0].rest_seconds)
        candidate = [*exercises, extra]
        if (
            budget_seconds is None
            or estimate_seconds(_group(candidate, fmt), fmt) <= budget_seconds
        ):
            exercises = candidate
    return _group(exercises, fmt)


def _as_test(exercise: PlannedExercise, picker: Picker) -> PlannedExercise:
    """First workout: an open target that places the user on the ladder (KB section 2).

    Bodyweight: swap in the standard test move (push-up, squat, plank, pull-up) if it is
    safe for them, with no rep target: "as many as you can with good form, stop with 2
    left". Weighted lifts keep their reps: "pick a weight you can lift with 3 left".
    """
    chosen = picker.by_slug.get(exercise.slug)
    if chosen is not None and is_weighted(chosen):
        return replace(exercise, test=True)
    test_move = picker.by_slug.get(TEST_MOVES[exercise.movement])
    if test_move is not None:
        exercise = replace(exercise, slug=test_move.slug, name=test_move.name)
    return replace(exercise, reps_min=None, reps_max=None, seconds=None, test=True)


def _mark_tests(main: list[PlannedExercise], picker: Picker) -> list[PlannedExercise]:
    """Test each movement once; never swap in a move the workout already has."""
    tested: set[MovementSlot] = set()
    slugs = {e.slug for e in main}
    marked = []
    for exercise in main:
        if exercise.movement in TEST_MOVES and exercise.movement not in tested:
            test = _as_test(exercise, picker)
            if test.slug == exercise.slug or test.slug not in slugs:
                tested.add(exercise.movement)
                slugs.add(test.slug)
                exercise = test
        marked.append(exercise)
    return marked


def as_test_workout(main: Sequence[PlannedExercise], picker: Picker) -> list[PlannedExercise]:
    """Turn a saved main block into the strength test (ADR 0017: a skipped test moves on).

    The same marking as building it there: open targets need no practice sets.
    """
    marked = _mark_tests(list(main), picker)
    return [
        replace(e, practice_sets=0) if e.test and e.reps_min is None and e.seconds is None else e
        for e in marked
    ]


# --- the recovery week (KB section 10) -------------------------------------------------


def _lighter(exercise: PlannedExercise, steady: bool) -> PlannedExercise:
    """Half the sets (rounded up), and easier: strength stops 4 reps short, intervals
    drop 2 effort points. Walks, steady cardio and mobility are easy already: unchanged.
    """
    if exercise.reps_in_reserve is not None:  # strength
        return replace(
            exercise,
            sets=math.ceil(exercise.sets / 2),
            reps_in_reserve=max(exercise.reps_in_reserve, RECOVERY_REPS_IN_RESERVE),
        )
    if steady:
        return exercise
    effort = exercise.effort
    if effort is not None:
        effort = max(RECOVERY_MIN_EFFORT, effort - RECOVERY_EFFORT_DROP)
    return replace(exercise, sets=math.ceil(exercise.sets / 2), effort=effort)


def _with_practice_sets(
    main: list[PlannedExercise], picker: Picker, room_seconds: float
) -> list[PlannedExercise]:
    """1 to 2 lighter sets of the first lift, if the warm-up has room (KB section 8)."""
    if not main or main[0].seconds is not None or main[0].reps_min is None:
        return main  # holds and open test sets need no practice
    if room_seconds < conditioning.PRACTICE_SET_SECONDS:
        return main
    first = picker.by_slug.get(main[0].slug)
    wanted = 2 if first is not None and is_weighted(first) else 1
    sets = min(wanted, int(room_seconds // conditioning.PRACTICE_SET_SECONDS))
    return [replace(main[0], practice_sets=sets), *main[1:]]


def _muscles(main: Sequence[PlannedExercise], picker: Picker) -> list[MuscleGroup | None]:
    return [
        picker.by_slug[e.slug].primary_muscle if e.slug in picker.by_slug else None for e in main
    ]


def build_session(
    answers: BuildInputs,
    session: PlannedSession,
    letter: str,
    picker: Picker,
    first_workout: bool = False,
    recovery: bool = False,
) -> Workout:
    """One complete workout: warm-up, main block, finisher, cool-down, fitted to the minutes.

    `recovery`: the block's lighter week. Same exercises, lighter numbers.
    """
    minutes = answers.minutes_per_session
    warm_min, main_min, cool_min = NO_LIMIT_SPLIT if minutes is None else SESSION_SPLIT[minutes]
    kind = session.kind
    finisher_min = conditioning.finisher_minutes(minutes) if session.finisher else 0
    main_budget = None if main_min is None else (main_min - finisher_min) * 60
    title = TITLES[kind] + (f" {letter}" if letter else "")

    if kind in STRENGTH_KINDS:
        fmt = workout_format(kind, minutes)
        main = _strength_main(answers, kind, letter, picker, main_budget)
        if first_workout:
            main = _mark_tests(main, picker)
    elif kind == S.HIIT:
        fmt, main = WorkoutFormat.INTERVALS, conditioning.hiit(picker, main_budget)
    elif kind == S.MOBILITY:
        fmt, main = WorkoutFormat.FLOW, conditioning.mobility(picker, main_budget)
    else:
        fmt, main = CARDIO_FORMATS[kind], conditioning.steady(picker, kind, main_budget)

    finisher = conditioning.finisher(picker, finisher_min) if finisher_min else []
    if recovery:
        steady = fmt in (WorkoutFormat.CONTINUOUS, WorkoutFormat.FLOW)
        main = [_lighter(e, steady) for e in main]
        finisher = [_lighter(e, steady=False) for e in finisher]
    # Easy walks and mobility are gentle already: no warm-up or cool-down around them.
    gentle = kind in (S.EASY_CARDIO, S.MOBILITY)
    muscles = _muscles(main, picker)
    if kind in (S.HIIT, S.STEADY_CARDIO, S.LONG_CARDIO):
        muscles = [MuscleGroup.QUADS, MuscleGroup.HAMSTRINGS, MuscleGroup.CALVES]
    warm = [] if gentle else conditioning.warm_up(picker, warm_min * 60, muscles)
    cool = [] if gentle else conditioning.cool_down(picker, cool_min * 60, muscles)
    if kind in STRENGTH_KINDS and minutes != 10:
        room = warm_min * 60 - conditioning.warm_up_seconds(warm)
        main = _with_practice_sets(main, picker, room)

    main_seconds = estimate_seconds(main, fmt) + timed_seconds(finisher)
    practice = sum(e.practice_sets for e in main) * conditioning.PRACTICE_SET_SECONDS
    total = timed_seconds(warm) + practice + main_seconds + timed_seconds(cool)
    return Workout(
        kind=kind,
        letter=letter,
        title=title,
        format=fmt,
        exercises=tuple(main),
        main_minutes=math.ceil(main_seconds / 60),
        warm_up=tuple(warm),
        finisher=tuple(finisher),
        cool_down=tuple(cool),
        total_minutes=math.ceil(total / 60),
        recovery=recovery,
    )


# --- a whole block -------------------------------------------------------------------


def _letters(kind: SessionKind, answers: BuildInputs, routine: Routine) -> str:
    """Full body rotates A/B for beginners and 2-day plans, A/B/C otherwise (KB section 4)."""
    if kind == S.FULL_BODY:
        per_week = sum(1 for s in routine.sessions if s.kind == S.FULL_BODY)
        return "AB" if answers.level == FitnessLevel.BEGINNER or per_week <= 2 else "ABC"
    if kind in (S.UPPER, S.LOWER, S.CIRCUIT):
        return "AB"
    return ""


def build_block(
    answers: BuildInputs,
    routine: Routine,
    library: Sequence[ExerciseInfo],
    weeks: int,
    first_block: bool = False,
    *,
    block_number: int = 1,
    recovery_week: bool = False,
    rungs: Mapping[MovementSlot, int] | None = None,
) -> list[list[Workout]]:
    """Every workout of a training block, week by week, with rotation applied.

    `weeks`: build-up weeks. `recovery_week`: add the lighter week after them (ADR 0017).
    `first_block`: the strength test is still to do, so the first strength workout is
    the test (ADR 0012, decision 4). `block_number` freshens the small moves (ADR 0017).
    `rungs`: where the strength test placed the user, per movement (ADR 0018).
    """
    picker = Picker(answers, library, block_number, rungs)
    letter_turns: Counter[SessionKind] = Counter()
    tested = not first_block
    block: list[list[Workout]] = []
    for week_number in range(weeks + (1 if recovery_week else 0)):
        recovery = week_number == weeks
        week: list[Workout] = []
        for session in routine.sessions:
            letters = _letters(session.kind, answers, routine)
            letter = letters[letter_turns[session.kind] % len(letters)] if letters else ""
            letter_turns[session.kind] += 1
            is_test = not tested and not recovery and session.kind in STRENGTH_KINDS
            tested = tested or is_test
            week.append(
                build_session(
                    answers, session, letter, picker, first_workout=is_test, recovery=recovery
                )
            )
        block.append(week)
    return block
