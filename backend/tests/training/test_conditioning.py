"""Stage 2b: warm-ups, cool-downs, finishers, cardio sessions and the strength test (ADR 0016)."""

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from lock_in_mode_api.models.enums import (
    BodyLimit,
    Equipment,
    FitnessLevel,
    Goal,
    Impact,
    Location,
    ShoulderDay,
    WorkoutFormat,
)
from lock_in_mode_api.models.enums import SessionKind as S
from lock_in_mode_api.seed.schema import SeedExercise, load_library
from lock_in_mode_api.training import conditioning
from lock_in_mode_api.training.exercise_rules import can_do, cautions
from lock_in_mode_api.training.plan_types import ALLOWED_IMPACT, Workout, is_weighted
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import build_block

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


def _workouts(answers: Answers, weeks: int = 1, first_block: bool = False) -> list[Workout]:
    block = build_block(answers, choose_routine(answers), LIBRARY, weeks, first_block)
    return [w for week in block for w in week]


def _of_kind(answers: Answers, kind: S) -> Workout:
    return next(w for w in _workouts(answers) if w.kind == kind)


def test_every_named_move_exists_in_the_library() -> None:
    named = [
        *conditioning.PULSE_RAISERS,
        *itertools.chain.from_iterable(conditioning.JOINT_PREP.values()),
        *conditioning.STRETCHES,
        *itertools.chain.from_iterable(conditioning.HIIT_GROUPS.values()),
        *conditioning.STEADY_MOVES,
        *conditioning.MOBILITY_FLOW,
        conditioning.COOL_DOWN_WALK,
    ]

    assert [slug for slug in named if slug not in BY_SLUG] == []


# --- the Knowledge Base's worked examples --------------------------------------------

EXAMPLE_1 = Answers(
    goal=Goal.LOSE_FAT,
    level=FitnessLevel.BEGINNER,
    location=Location.HOME,
    minutes_per_session=20,
    limits=(BodyLimit.KNEES,),
)
EXAMPLE_5 = Answers(
    goal=Goal.STAMINA,
    location=Location.HOME,
    equipment=(Equipment.DUMBBELLS, Equipment.PULL_UP_BAR),
    days_per_week=5,
    minutes_per_session=30,
)


def test_example_1_finisher_is_4_low_impact_rounds_of_20_on_40_off() -> None:
    workout = _workouts(EXAMPLE_1)[0]

    assert sum(m.sets for m in workout.finisher) == 4
    assert all((m.seconds, m.rest_seconds) == (20, 40) for m in workout.finisher)
    assert all(BY_SLUG[m.slug].impact in (Impact.NONE, Impact.LOW) for m in workout.finisher)
    assert workout.total_minutes <= 20


def test_example_5_hiit_is_five_moves_30_on_30_off_three_rounds() -> None:
    hiit = _of_kind(EXAMPLE_5, S.HIIT)

    assert hiit.format == WorkoutFormat.INTERVALS
    assert len(hiit.exercises) == 5
    assert all((m.sets, m.seconds, m.rest_seconds) == (3, 30, 30) for m in hiit.exercises)
    assert hiit.main_minutes == 15
    assert hiit.total_minutes <= 30


def test_example_5_steady_cardio_is_a_walk_at_talking_pace() -> None:
    steady = _of_kind(EXAMPLE_5, S.STEADY_CARDIO)

    assert steady.format == WorkoutFormat.CONTINUOUS
    assert [m.slug for m in steady.exercises] == ["brisk-walk"]
    assert steady.exercises[0].effort == conditioning.STEADY_EFFORT
    assert steady.total_minutes <= 30


# --- warm-up and cool-down (KB section 8) --------------------------------------------


def test_upper_body_days_warm_up_the_shoulders_and_stretch_the_upper_body() -> None:
    upper = _of_kind(Answers(days_per_week=4), S.UPPER)

    assert "arm-circles" in [m.slug for m in upper.warm_up]
    stretched = {BY_SLUG[m.slug].primary_muscle for m in upper.cool_down[1:]}
    assert stretched <= {"chest", "back"}


def test_the_first_lift_gets_practice_sets_but_not_in_10_minutes() -> None:
    long_session = _workouts(Answers())[0]
    short_session = _workouts(Answers(minutes_per_session=10))[0]

    assert long_session.exercises[0].practice_sets >= 1
    assert all(e.practice_sets == 0 for e in short_session.exercises)


def test_easy_walks_and_mobility_need_no_warm_up() -> None:
    answers = Answers(level=FitnessLevel.BEGINNER, days_per_week=6)

    for kind in (S.EASY_CARDIO, S.MOBILITY):
        workout = _of_kind(answers, kind)
        assert workout.warm_up == ()
        assert workout.cool_down == ()


def test_mobility_is_a_gentle_flow_of_twelve_minutes_at_most() -> None:
    mobility = _of_kind(Answers(level=FitnessLevel.BEGINNER, days_per_week=6), S.MOBILITY)

    assert mobility.format == WorkoutFormat.FLOW
    assert mobility.main_minutes <= 12


# --- cardio by level -----------------------------------------------------------------


def test_beginner_hiit_is_low_impact_20_on_40_off() -> None:
    answers = Answers(goal=Goal.STAMINA, level=FitnessLevel.BEGINNER, location=Location.HOME)
    hiit = _of_kind(answers, S.HIIT)

    assert all((m.seconds, m.rest_seconds) == (20, 40) for m in hiit.exercises)
    assert all(BY_SLUG[m.slug].impact in (Impact.NONE, Impact.LOW) for m in hiit.exercises)


def test_experienced_hiit_may_jump() -> None:
    answers = Answers(goal=Goal.STAMINA, level=FitnessLevel.EXPERIENCED, location=Location.HOME)
    hiit = _of_kind(answers, S.HIIT)

    assert any(BY_SLUG[m.slug].impact == Impact.HIGH for m in hiit.exercises)


def test_low_intensity_has_no_hiit_and_walks_instead() -> None:
    answers = Answers(goal=Goal.LOSE_FAT, days_per_week=4, needs_low_intensity=True)
    workouts = _workouts(answers)

    assert S.HIIT not in {w.kind for w in workouts}
    assert all(w.finisher == () for w in workouts)


# --- the first-workout strength test (KB section 2) ----------------------------------


def test_only_the_first_strength_workout_of_the_first_block_is_a_test() -> None:
    first_block = _workouts(Answers(location=Location.HOME), weeks=2, first_block=True)
    later_block = _workouts(Answers(location=Location.HOME), weeks=2)

    tests = [w for w in first_block if any(e.test for e in w.exercises)]
    assert tests == [first_block[0]]
    assert not any(e.test for w in later_block for e in w.exercises)


def test_bodyweight_test_uses_the_standard_moves_with_open_targets() -> None:
    first = _workouts(Answers(location=Location.HOME), first_block=True)[0]
    tested = {e.slug: e for e in first.exercises if e.test}

    assert {"bodyweight-squat", "push-up"} <= set(tested)
    assert all(e.reps_min is None and e.reps_max is None for e in tested.values())


def test_gym_test_keeps_the_reps_and_asks_for_a_starting_weight() -> None:
    first = _workouts(Answers(), first_block=True)[0]
    weighted = [e for e in first.exercises if e.test and is_weighted(BY_SLUG[e.slug])]

    assert weighted
    assert all(e.reps_min is not None for e in weighted)


def test_a_test_move_the_user_should_avoid_is_never_swapped_in() -> None:
    answers = Answers(location=Location.HOME, limits=(BodyLimit.SHOULDERS, BodyLimit.KNEES))
    first = _workouts(answers, first_block=True)[0]

    assert all(not cautions(BY_SLUG[e.slug], answers) for e in first.exercises)


# --- every part of every workout, for many users -------------------------------------

SETUPS: list[tuple[Location, tuple[str, ...]]] = [
    (Location.GYM, ()),
    (Location.HOME, ()),
    (Location.HOME, (Equipment.RESISTANCE_BANDS,)),
    (Location.HOME, (Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.RESISTANCE_BANDS)),
]


@pytest.mark.parametrize("goal", list(Goal))
def test_every_workout_part_is_safe_and_fits_the_total_time(goal: Goal) -> None:
    problems = []
    for level, (location, kit), days, minutes, limits, low in itertools.product(
        FitnessLevel,
        SETUPS,
        [2, 4, 6],
        [10, 20, 45, None],
        [(), (BodyLimit.KNEES, BodyLimit.BACK, BodyLimit.SHOULDERS)],
        [False, True],
    ):
        answers = Answers(goal, level, location, kit, days, minutes, low, limits=limits)
        for workout in _workouts(answers, first_block=True):
            if minutes is not None and workout.total_minutes > minutes:
                problems.append((answers, workout.title, f"{workout.total_minutes} min"))
            if not workout.exercises:
                problems.append((answers, workout.title, "empty"))
            parts = (workout.warm_up, workout.exercises, workout.finisher, workout.cool_down)
            for move in itertools.chain(*parts):
                exercise = BY_SLUG[move.slug]
                if not can_do(exercise, answers) or cautions(exercise, answers):
                    problems.append((answers, workout.title, f"{move.slug} unsafe"))
            jumpy_parts = workout.exercises if workout.kind == S.HIIT else ()
            for move in itertools.chain(workout.finisher, jumpy_parts):
                if BY_SLUG[move.slug].impact not in ALLOWED_IMPACT[level]:
                    problems.append((answers, workout.title, f"{move.slug} too jumpy"))

    assert problems == []
