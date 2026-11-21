"""Stage 2a of the plan generator: fill strength sessions (ADR 0015).

routine (stage 1) + exercise library -> workouts with exercises, sets, reps, rest and a
time estimate, for a whole training block. Pure: no database. Rules: KB sections 3
(training variables), 5 (templates), 9 (fitting the session length); rotation: ADR 0014.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from lock_in_mode_api.models.enums import (
    HEAD_GROUP,
    Equipment,
    ExerciseType,
    FitnessLevel,
    Goal,
    Impact,
    MovementSlot,
    MuscleGroup,
    MuscleHead,
    SessionKind,
    WorkoutFormat,
)
from lock_in_mode_api.training.exercise_rules import ExerciseFacts, UserSetup, can_do, cautions
from lock_in_mode_api.training.routine import PlanInputs, Routine
from lock_in_mode_api.training.templates import STRENGTH_KINDS, Slot, template

S = SessionKind

# Hardest rung a level starts on (difficulty 1-5). The first workout corrects it.
LEVEL_MAX_DIFFICULTY = {
    FitnessLevel.BEGINNER: 2,
    FitnessLevel.SOME_EXPERIENCE: 4,
    FitnessLevel.EXPERIENCED: 5,
}
# Minutes for the main block, after warm-up and cool-down (KB section 9; 75 and 90 extend it).
MAIN_BLOCK_MINUTES = {10: 7, 20: 15, 30: 23, 45: 36, 60: 50, 75: 63, 90: 77}
SET_WORK_SECONDS = 40  # one set is about 40 s of work (KB section 9)
SUPERSET_TIME_FACTOR = 0.6  # a superset pair shares its rest: about 40% faster
CIRCUIT_ROUND_REST = 60
MIN_SETS = 2
PROTECTED_SLOTS = 3  # never drop the first three slots: they are the session
WEIGHTED_KIT = frozenset({Equipment.DUMBBELLS, Equipment.GYM})
HARD_BODYWEIGHT = 4  # difficulty from which a bodyweight move counts as heavy

TITLES = {
    S.FULL_BODY: "Full body",
    S.UPPER: "Upper body",
    S.LOWER: "Lower body",
    S.PUSH: "Push",
    S.PULL: "Pull",
    S.LEGS: "Legs",
    S.BRO_CHEST: "Chest",
    S.BRO_BACK: "Back",
    S.BRO_LEGS: "Legs",
    S.BRO_SHOULDERS: "Shoulders",
    S.BRO_ARMS: "Arms and core",
    S.CIRCUIT: "Circuit",
    S.HIIT: "HIIT",
    S.STEADY_CARDIO: "Steady cardio",
    S.LONG_CARDIO: "Long easy cardio",
    S.EASY_CARDIO: "Easy walk",
    S.MOBILITY: "Mobility",
}


class ExerciseInfo(ExerciseFacts, Protocol):
    """What the builder reads from an exercise. Seed entries and database rows both fit."""

    @property
    def slug(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def movement_slot(self) -> MovementSlot: ...
    @property
    def exercise_type(self) -> ExerciseType: ...
    @property
    def targets(self) -> Sequence[str]: ...
    @property
    def difficulty(self) -> int: ...
    @property
    def effectiveness(self) -> int | None: ...
    @property
    def is_timed(self) -> bool: ...
    @property
    def impact(self) -> Impact: ...
    @property
    def primary_muscle(self) -> MuscleGroup | None: ...


class BuildInputs(PlanInputs, UserSetup, Protocol):
    """Every answer the builder reads. Profile rows fit."""


@dataclass(frozen=True)
class PlannedExercise:
    slug: str
    name: str
    movement: MovementSlot
    sets: int  # rounds, for a circuit
    reps_min: int | None  # None for timed exercises
    reps_max: int | None
    seconds: int | None  # timed exercises (plank): hold this long
    rest_seconds: int  # after each set (circuit: before the next exercise)
    reps_in_reserve: int  # "stop when you could still do this many more good reps"
    group: int  # exercises with the same group are done back to back
    rest_floor: int  # shortest rest the goal allows, used when time is tight


@dataclass(frozen=True)
class Workout:
    kind: SessionKind
    letter: str  # "A", "B", "C" for rotating templates; "" otherwise
    title: str
    format: WorkoutFormat
    exercises: tuple[PlannedExercise, ...]
    main_minutes: int  # estimated main block; warm-up and cool-down come on top
    finisher: bool = False


# --- choosing the exercise for a slot ------------------------------------------------


def _rank(exercise: ExerciseInfo, slot: Slot, cap: int) -> tuple[object, ...]:
    over_cap = exercise.difficulty > cap
    return (
        over_cap,  # level-appropriate first
        exercise.difficulty if over_cap else 0,  # if nothing fits the level, the easiest
        slot.prefer is not None and slot.prefer not in exercise.targets,  # wanted emphasis
        slot.prefer is not None and exercise.primary_muscle != HEAD_GROUP[slot.prefer],
        -(exercise.effectiveness or 0),  # most effective
        exercise.difficulty,  # then the safer start
        exercise.slug,  # stable tie-break
    )


class _Picker:
    """Picks exercises with planned rotation (ADR 0014).

    Each slot has a short ranked pool: 2 picks for big lifts, 3 for small moves. The n-th
    time a slot appears in the block it gets pool[n % size], so picks alternate on a fixed
    pattern, never randomly.
    """

    def __init__(self, answers: BuildInputs, library: Sequence[ExerciseInfo]) -> None:
        self.cap = LEVEL_MAX_DIFFICULTY[answers.level]
        self.by_movement: dict[MovementSlot, list[ExerciseInfo]] = {}
        for exercise in library:
            if can_do(exercise, answers) and not cautions(exercise, answers):
                self.by_movement.setdefault(exercise.movement_slot, []).append(exercise)
        self.seen: Counter[tuple[MovementSlot, MuscleHead | None]] = Counter()

    def pick(self, slot: Slot, used: set[str]) -> ExerciseInfo | None:
        movement = slot.movement
        if not self.by_movement.get(movement) and slot.fallback is not None:
            movement = slot.fallback
        candidates = sorted(
            self.by_movement.get(movement, []), key=lambda e: _rank(e, slot, self.cap)
        )
        if not candidates:
            return None
        in_level = [e for e in candidates if e.difficulty <= self.cap]
        pool = (in_level or candidates[:1])[: 2 if slot.main else 3]
        key = (slot.movement, slot.prefer)
        turn = self.seen[key]
        self.seen[key] += 1
        for offset in range(len(pool)):
            choice = pool[(turn + offset) % len(pool)]
            if choice.slug not in used:
                return choice
        return next((e for e in candidates if e.slug not in used), None)


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
    weighted = bool(WEIGHTED_KIT & set(exercise.equipment))

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
        group=0,  # set by _group
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


def estimate_seconds(exercises: Sequence[PlannedExercise], fmt: WorkoutFormat) -> float:
    """Main-block time: a set is ~40 s of work plus its rest; a pair shares its rest."""
    if not exercises:
        return 0.0
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


def build_strength_session(
    answers: BuildInputs,
    kind: SessionKind,
    letter: str,
    picker: _Picker,
    finisher: bool = False,
) -> Workout:
    minutes = answers.minutes_per_session
    fmt = workout_format(kind, minutes)
    budget = None if minutes is None else MAIN_BLOCK_MINUTES[minutes] * 60
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

    exercises = _fit(required, fmt, budget)
    for slot, exercise in optional:  # "(if time)" slots: always with no limit, else if they fit
        extra = _plan_exercise(answers, slot, exercise, lead=False)
        if fmt == WorkoutFormat.CIRCUIT:
            extra = replace(extra, sets=exercises[0].sets, rest_seconds=exercises[0].rest_seconds)
        candidate = [*exercises, extra]
        fits = budget is None or estimate_seconds(_group(candidate, fmt), fmt) <= budget
        if fits:
            exercises = candidate

    exercises = _group(exercises, fmt)
    seconds = estimate_seconds(exercises, fmt)
    title = TITLES[kind] + (f" {letter}" if letter else "")
    return Workout(
        kind=kind,
        letter=letter,
        title=title,
        format=fmt,
        exercises=tuple(exercises),
        main_minutes=math.ceil(seconds / 60),
        finisher=finisher,
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
    answers: BuildInputs, routine: Routine, library: Sequence[ExerciseInfo], weeks: int
) -> list[list[Workout]]:
    """Every workout of a training block, week by week, with rotation applied.

    Cardio, HIIT and mobility sessions come back empty for now (stage 2b fills them).
    """
    picker = _Picker(answers, library)
    letter_turns: Counter[SessionKind] = Counter()
    block: list[list[Workout]] = []
    for _ in range(weeks):
        week: list[Workout] = []
        for session in routine.sessions:
            letters = _letters(session.kind, answers, routine)
            letter = letters[letter_turns[session.kind] % len(letters)] if letters else ""
            letter_turns[session.kind] += 1
            if session.kind in STRENGTH_KINDS:
                week.append(
                    build_strength_session(answers, session.kind, letter, picker, session.finisher)
                )
            else:
                fmt = WorkoutFormat.STRAIGHT_SETS
                week.append(Workout(session.kind, "", TITLES[session.kind], fmt, (), 0))
        block.append(week)
    return block
