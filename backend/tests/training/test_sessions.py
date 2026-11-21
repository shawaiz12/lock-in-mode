"""Stage 2a of the plan generator: strength sessions (ADR 0015), with the real library."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from lock_in_mode_api.models.enums import (
    BodyLimit,
    Equipment,
    FitnessLevel,
    Goal,
    Location,
    MovementSlot,
    ShoulderDay,
    WorkoutFormat,
)
from lock_in_mode_api.models.enums import MovementSlot as M
from lock_in_mode_api.seed.schema import SeedExercise, load_library
from lock_in_mode_api.training.exercise_rules import can_do, cautions
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import MAIN_BLOCK_MINUTES, Workout, build_block
from lock_in_mode_api.training.templates import STRENGTH_KINDS

LIBRARY: Sequence[SeedExercise] = load_library().exercises
BY_SLUG = {e.slug: e for e in LIBRARY}


@dataclass(frozen=True)
class Answers:
    goal: Goal = Goal.BUILD_MUSCLE
    level: FitnessLevel = FitnessLevel.SOME_EXPERIENCE
    location: Location = Location.GYM
    equipment: tuple[str, ...] = ()
    days_per_week: int = 3
    minutes_per_session: int | None = 45
    needs_low_intensity: bool = False
    prefers_bro_split: bool = False
    shoulder_day: ShoulderDay = ShoulderDay.PUSH
    limits: tuple[str, ...] = ()
    women_home_track: bool = False


def _block(answers: Answers, weeks: int = 1) -> list[list[Workout]]:
    return build_block(answers, choose_routine(answers), LIBRARY, weeks)


def _find(block: list[list[Workout]], title: str) -> list[Workout]:
    return [w for week in block for w in week if w.title == title]


def _movements(workout: Workout) -> list[MovementSlot]:
    return [e.movement for e in workout.exercises]


# --- the Knowledge Base's worked examples (section 12) -------------------------------


def test_example_2_upper_a_fits_45_minutes_with_3_sets_on_main_lifts() -> None:
    upper_a = _find(_block(Answers(days_per_week=4)), "Upper body A")[0]

    assert _movements(upper_a) == [
        M.HORIZONTAL_PUSH,
        M.HORIZONTAL_PULL,
        M.VERTICAL_PUSH,
        M.VERTICAL_PULL,
        M.LATERAL_RAISE,
        M.TRICEPS,
        M.BICEPS,
    ]
    assert [e.sets for e in upper_a.exercises] == [3, 3, 3, 3, 2, 2, 2]
    assert upper_a.exercises[0].reps_min == 6  # main lift: 6 to 10
    assert upper_a.format == WorkoutFormat.STRAIGHT_SETS
    assert upper_a.main_minutes <= MAIN_BLOCK_MINUTES[45]


def test_example_3_push_day_keeps_triceps_when_time_is_short() -> None:
    push = _find(_block(Answers(level=FitnessLevel.EXPERIENCED, days_per_week=5)), "Push")[0]

    assert _movements(push) == [
        M.HORIZONTAL_PUSH,
        M.HORIZONTAL_PUSH,
        M.VERTICAL_PUSH,
        M.LATERAL_RAISE,
        M.TRICEPS,
    ]
    assert push.exercises[0].sets == 4  # experienced: 4 sets on the first lift
    assert push.main_minutes <= MAIN_BLOCK_MINUTES[45]


def test_example_1_beginner_lose_fat_home_knees_20_minutes() -> None:
    answers = Answers(
        goal=Goal.LOSE_FAT,
        level=FitnessLevel.BEGINNER,
        location=Location.HOME,
        minutes_per_session=20,
        limits=(BodyLimit.KNEES,),
    )
    week = _block(answers)[0]

    assert [w.title for w in week] == ["Full body A", "Full body B", "Full body A"]
    for workout in week:
        assert workout.format == WorkoutFormat.SUPERSETS
        assert workout.finisher
        assert all(e.sets == 2 and e.reps_in_reserve == 3 for e in workout.exercises)
        assert all(not cautions(BY_SLUG[e.slug], answers) for e in workout.exercises)


def test_example_4_stay_active_10_minutes_is_a_no_rest_circuit() -> None:
    answers = Answers(
        goal=Goal.STAY_ACTIVE,
        level=FitnessLevel.BEGINNER,
        location=Location.HOME,
        equipment=(Equipment.RESISTANCE_BANDS,),
        days_per_week=2,
        minutes_per_session=10,
    )

    for workout in _block(answers)[0]:
        assert workout.format == WorkoutFormat.CIRCUIT
        assert all(e.sets == 2 and e.rest_seconds == 0 for e in workout.exercises)
        assert workout.main_minutes <= MAIN_BLOCK_MINUTES[10]


def test_example_5_stamina_circuit_a() -> None:
    answers = Answers(
        goal=Goal.STAMINA,
        location=Location.HOME,
        equipment=(Equipment.DUMBBELLS, Equipment.PULL_UP_BAR),
        days_per_week=5,
        minutes_per_session=30,
    )
    circuit_a = _find(_block(answers), "Circuit A")[0]

    assert _movements(circuit_a) == [
        M.SQUAT,
        M.HORIZONTAL_PUSH,
        M.HORIZONTAL_PULL,
        M.HINGE,
        M.BRACE,
    ]
    assert all(e.sets == 3 and e.rest_seconds == 30 for e in circuit_a.exercises)


# --- rotation (ADR 0014) -------------------------------------------------------------


def test_main_lifts_alternate_between_two_picks() -> None:
    uppers = _find(_block(Answers(days_per_week=4), weeks=4), "Upper body A")
    first_lift = [w.exercises[0].slug for w in uppers]

    assert first_lift[0] != first_lift[1]
    assert first_lift == [first_lift[0], first_lift[1]] * 2


def test_small_moves_cycle_through_three_picks() -> None:
    uppers = _find(_block(Answers(days_per_week=4), weeks=3), "Upper body A")
    raises = [next(e.slug for e in w.exercises if e.movement == M.LATERAL_RAISE) for w in uppers]

    assert len(set(raises)) == 3


def test_same_answers_give_the_same_block() -> None:
    answers = Answers(days_per_week=5)

    assert _block(answers, weeks=2) == _block(answers, weeks=2)


# --- templates and limits ------------------------------------------------------------


def test_no_pulling_kit_turns_the_vertical_pull_into_a_row() -> None:
    full_body_b = _find(_block(Answers(location=Location.HOME)), "Full body B")[0]

    assert M.VERTICAL_PULL not in _movements(full_body_b)
    assert _movements(full_body_b)[2] == M.HORIZONTAL_PULL


def test_big_muscle_before_helper_on_push_and_pull_days() -> None:
    week = _block(
        Answers(level=FitnessLevel.EXPERIENCED, days_per_week=6, minutes_per_session=None)
    )[0]
    push, pull = week[0], week[1]
    chest = {M.HORIZONTAL_PUSH, M.CHEST_FLY}
    back = {M.VERTICAL_PULL, M.HORIZONTAL_PULL, M.TRAPS, M.REAR_DELT, M.LOWER_BACK}

    last_chest = max(i for i, m in enumerate(_movements(push)) if m in chest)
    first_triceps = min(i for i, m in enumerate(_movements(push)) if m == M.TRICEPS)
    last_back = max(i for i, m in enumerate(_movements(pull)) if m in back)
    first_biceps = min(i for i, m in enumerate(_movements(pull)) if m == M.BICEPS)
    assert last_chest < first_triceps
    assert last_back < first_biceps


def test_no_time_limit_adds_the_optional_slots() -> None:
    limited = _find(_block(Answers(minutes_per_session=30)), "Full body A")[0]
    unlimited = _find(_block(Answers(minutes_per_session=None)), "Full body A")[0]

    assert M.BICEPS not in _movements(limited)
    assert M.BICEPS in _movements(unlimited)


def test_hard_bodyweight_moves_get_lower_reps() -> None:
    upper_b = _find(_block(Answers(days_per_week=4)), "Upper body B")[0]
    chin_up = next(e for e in upper_b.exercises if e.slug == "chin-up")

    assert (chin_up.reps_min, chin_up.reps_max) == (6, 12)


# --- every pick is safe, possible and on time, for many users ------------------------

SETUPS: list[tuple[Location, tuple[str, ...]]] = [
    (Location.GYM, ()),
    (Location.HOME, ()),
    (Location.HOME, (Equipment.RESISTANCE_BANDS,)),
    (Location.HOME, (Equipment.DUMBBELLS,)),
    (Location.HOME, (Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.RESISTANCE_BANDS)),
]


@pytest.mark.parametrize("goal", list(Goal))
def test_every_workout_is_safe_possible_unique_and_on_time(goal: Goal) -> None:
    problems = []
    for level, (location, kit), days, minutes, limits, low in itertools.product(
        FitnessLevel,
        SETUPS,
        [3, 5, 6],
        [10, 30, 45, None],
        [(), (BodyLimit.KNEES, BodyLimit.BACK, BodyLimit.SHOULDERS)],
        [False, True],
    ):
        answers = Answers(goal, level, location, kit, days, minutes, low, limits=limits)
        for workout in (w for week in _block(answers, weeks=2) for w in week):
            if workout.kind not in STRENGTH_KINDS:
                continue  # cardio and mobility: test_conditioning.py
            slugs = [e.slug for e in workout.exercises]
            if len(set(slugs)) != len(slugs):
                problems.append((answers, workout.title, "repeats an exercise"))
            if len(slugs) < 3:
                problems.append((answers, workout.title, "fewer than 3 exercises"))
            for slug in slugs:
                if not can_do(BY_SLUG[slug], answers) or cautions(BY_SLUG[slug], answers):
                    problems.append((answers, workout.title, f"{slug} is unsafe or impossible"))
            if minutes is not None and workout.main_minutes > MAIN_BLOCK_MINUTES[minutes]:
                problems.append((answers, workout.title, f"{workout.main_minutes} min"))

    assert problems == []
