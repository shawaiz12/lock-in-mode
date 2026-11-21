"""Stage 1 of the plan generator: routine and week layout (ADR 0014, KB sections 4 and 7)."""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest

from lock_in_mode_api.models.enums import (
    Equipment,
    FitnessLevel,
    Goal,
    Location,
    RoutineKind,
    ShoulderDay,
)
from lock_in_mode_api.models.enums import SessionKind as S
from lock_in_mode_api.training.routine import (
    DAYS_IN_WEEK,
    Routine,
    choose_routine,
    hard_muscles,
    is_hard,
)
from lock_in_mode_api.training.routine_rules import bro_split_available

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


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


def _kinds(routine: Routine) -> list[S]:
    return [s.kind for s in routine.sessions]


# --- the Knowledge Base's worked examples (section 12) -------------------------------


def test_example_1_beginner_lose_fat_home_3_days_20_min() -> None:
    routine = choose_routine(
        Answers(
            goal=Goal.LOSE_FAT,
            level=FitnessLevel.BEGINNER,
            location=Location.HOME,
            days_per_week=3,
            minutes_per_session=20,
        )
    )

    assert _kinds(routine) == [S.FULL_BODY] * 3
    assert all(s.finisher for s in routine.sessions)
    assert routine.weekdays == (MON, WED, FRI)


def test_example_2_some_experience_build_muscle_gym_4_days() -> None:
    routine = choose_routine(Answers(days_per_week=4))

    assert routine.kind == RoutineKind.UPPER_LOWER
    assert _kinds(routine) == [S.UPPER, S.LOWER, S.UPPER, S.LOWER]
    assert routine.weekdays == (MON, TUE, THU, FRI)


def test_example_3_experienced_build_muscle_gym_5_days() -> None:
    routine = choose_routine(Answers(level=FitnessLevel.EXPERIENCED, days_per_week=5))

    assert _kinds(routine) == [S.PUSH, S.PULL, S.LEGS, S.UPPER, S.LOWER]
    assert routine.weekdays == (MON, TUE, WED, FRI, SAT)
    assert routine.uses_push_pull_legs


def test_example_3_with_the_bro_split_switched_on() -> None:
    routine = choose_routine(
        Answers(level=FitnessLevel.EXPERIENCED, days_per_week=5, prefers_bro_split=True)
    )

    assert routine.kind == RoutineKind.BRO_SPLIT
    assert _kinds(routine) == [S.BRO_CHEST, S.BRO_BACK, S.BRO_LEGS, S.BRO_SHOULDERS, S.BRO_ARMS]
    assert not routine.uses_push_pull_legs


def test_example_4_beginner_stay_active_home_bands_2_days_10_min() -> None:
    routine = choose_routine(
        Answers(
            goal=Goal.STAY_ACTIVE,
            level=FitnessLevel.BEGINNER,
            location=Location.HOME,
            equipment=(Equipment.RESISTANCE_BANDS,),
            days_per_week=2,
            minutes_per_session=10,
        )
    )

    assert _kinds(routine) == [S.FULL_BODY, S.FULL_BODY]
    assert routine.weekdays == (MON, THU)


def test_example_5_some_experience_stamina_home_5_days() -> None:
    routine = choose_routine(
        Answers(
            goal=Goal.STAMINA,
            location=Location.HOME,
            equipment=(Equipment.DUMBBELLS, Equipment.PULL_UP_BAR),
            days_per_week=5,
            minutes_per_session=30,
        )
    )

    assert _kinds(routine) == [S.CIRCUIT, S.HIIT, S.STEADY_CARDIO, S.CIRCUIT, S.HIIT]


# --- base routine table (KB section 4: days x level) ---------------------------------


@pytest.mark.parametrize(
    ("level", "days", "expected"),
    [
        (FitnessLevel.BEGINNER, 2, [S.FULL_BODY] * 2),
        (FitnessLevel.BEGINNER, 3, [S.FULL_BODY] * 3),
        (FitnessLevel.BEGINNER, 4, [S.FULL_BODY] * 3 + [S.EASY_CARDIO]),
        (FitnessLevel.BEGINNER, 6, [S.FULL_BODY] * 3 + [S.EASY_CARDIO] * 2 + [S.MOBILITY]),
        (FitnessLevel.SOME_EXPERIENCE, 3, [S.FULL_BODY] * 3),
        (FitnessLevel.SOME_EXPERIENCE, 5, [S.UPPER, S.LOWER, S.PUSH, S.PULL, S.LEGS]),
        (FitnessLevel.EXPERIENCED, 6, [S.PUSH, S.PULL, S.LEGS] * 2),
    ],
)
def test_days_and_level_pick_the_routine(level: FitnessLevel, days: int, expected: list[S]) -> None:
    routine = choose_routine(Answers(level=level, days_per_week=days))

    assert sorted(_kinds(routine)) == sorted(expected)


def test_build_strength_never_gets_push_pull_legs() -> None:
    routine = choose_routine(Answers(goal=Goal.STRENGTH, days_per_week=6))

    assert _kinds(routine) == [S.UPPER, S.LOWER] * 3


def test_home_without_pulling_kit_gets_upper_lower_not_ppl() -> None:
    routine = choose_routine(Answers(location=Location.HOME, days_per_week=5))

    assert routine.kind == RoutineKind.UPPER_LOWER
    assert any("pull-up bar" in reason for reason in routine.reasons)


def test_short_sessions_are_full_body_with_easy_days() -> None:
    routine = choose_routine(Answers(days_per_week=5, minutes_per_session=20))

    assert sorted(_kinds(routine)) == sorted([S.FULL_BODY] * 3 + [S.EASY_CARDIO] * 2)


def test_low_intensity_swaps_hiit_and_finishers_for_walks() -> None:
    routine = choose_routine(Answers(goal=Goal.LOSE_FAT, days_per_week=4, needs_low_intensity=True))

    assert S.HIIT not in _kinds(routine)
    assert not any(s.finisher for s in routine.sessions)
    assert any("safety check" in reason for reason in routine.reasons)
    assert not any("finisher" in reason and "ends" in reason for reason in routine.reasons)


def test_shoulders_on_leg_day_still_get_a_valid_week() -> None:
    routine = choose_routine(
        Answers(level=FitnessLevel.EXPERIENCED, days_per_week=6, shoulder_day=ShoulderDay.LEGS)
    )

    assert _kinds(routine) == [S.PUSH, S.PULL, S.LEGS] * 2


def test_same_answers_always_give_the_same_week() -> None:
    answers = Answers(goal=Goal.LOSE_FAT, days_per_week=5)

    assert choose_routine(answers) == choose_routine(replace(answers))


# --- every possible set of answers keeps every rule ----------------------------------

SETUPS: list[tuple[Location, tuple[str, ...]]] = [
    (Location.GYM, ()),
    (Location.HOME, ()),
    (Location.HOME, (Equipment.RESISTANCE_BANDS,)),
    (Location.HOME, (Equipment.DUMBBELLS,)),
    (Location.HOME, (Equipment.PULL_UP_BAR,)),
    (Location.HOME, (Equipment.DUMBBELLS, Equipment.PULL_UP_BAR, Equipment.RESISTANCE_BANDS)),
]
MAX_HIIT = {FitnessLevel.BEGINNER: 2, FitnessLevel.SOME_EXPERIENCE: 2, FitnessLevel.EXPERIENCED: 3}
SPLIT_KINDS = {S.UPPER, S.LOWER, S.PUSH, S.PULL, S.LEGS} | {k for k in S if k.startswith("bro_")}


def _every_answer() -> Iterator[Answers]:
    for goal, level, (location, kit), days, minutes, low, bro, shoulders in itertools.product(
        Goal,
        FitnessLevel,
        SETUPS,
        range(2, 7),
        [10, 20, 30, 45, 60, None],
        [False, True],
        [False, True],
        ShoulderDay,
    ):
        yield Answers(goal, level, location, kit, days, minutes, low, bro, shoulders)


def _broken_rules(a: Answers, routine: Routine) -> list[str]:
    """Every rule from KB sections 4 and 7, checked independently of the generator."""
    kinds = _kinds(routine)
    by_day = dict(zip(routine.weekdays, kinds, strict=True))
    beginner = a.level == FitnessLevel.BEGINNER
    broken: list[str] = []

    def check(ok: bool, rule: str) -> None:
        if not ok:
            broken.append(rule)

    check(len(kinds) == a.days_per_week, "one session per training day")
    check(list(routine.weekdays) == sorted(set(routine.weekdays)), "weekdays in order, no repeats")
    check(len(by_day) < DAYS_IN_WEEK, "at least one full rest day")
    for day, today in by_day.items():
        tomorrow = by_day.get((day + 1) % DAYS_IN_WEEK)
        if tomorrow is None:
            continue
        mine = hard_muscles(today, a.shoulder_day)
        check(not mine & hard_muscles(tomorrow, a.shoulder_day), "no muscle hard 2 days running")
        check(not (beginner and is_hard(today) and is_hard(tomorrow)), "beginners rest after hard")
        check(not (today == S.HIIT and tomorrow == S.HIIT), "no HIIT 2 days running")
        legs_next = "legs" in hard_muscles(tomorrow, a.shoulder_day)
        check(not (today == S.HIIT and legs_next), "no HIIT before legs")
    if beginner:
        check(sum(is_hard(k) for k in kinds) <= 3, "beginners: 3 hard days at most")
    check(kinds.count(S.HIIT) <= MAX_HIIT[a.level], "HIIT cap per level")
    if a.needs_low_intensity:
        check(S.HIIT not in kinds, "low intensity: no HIIT")
        check(not any(s.finisher for s in routine.sessions), "low intensity: no finishers")
    if a.minutes_per_session is not None and a.minutes_per_session <= 20:
        check(not SPLIT_KINDS & set(kinds), "10/20 min: full body only")
    if a.goal == Goal.STRENGTH:
        check(not {S.PUSH, S.PULL, S.BRO_CHEST} & set(kinds), "strength: no PPL or bro split")
    if a.goal == Goal.STAY_ACTIVE:
        check(sum(is_hard(k) for k in kinds) <= 3, "stay active: 2-3 strength days")
    if a.location == Location.HOME and not a.equipment:
        check(S.PULL not in kinds, "no kit at home: no pull day")
    if routine.kind == RoutineKind.BRO_SPLIT:
        check(a.prefers_bro_split and bro_split_available(a), "bro split only when chosen")
    check(routine.reasons[0].startswith(f"{a.days_per_week} days a week"), "reasons start")
    return broken


def test_every_possible_set_of_answers_gets_a_week_that_keeps_every_rule() -> None:
    failures = []
    count = 0
    for answers in _every_answer():
        count += 1
        broken = _broken_rules(answers, choose_routine(answers))
        if broken:
            failures.append((answers, broken))

    assert count == 21_600
    assert failures == []


def test_preview_prints_the_week_and_the_reasons() -> None:
    from lock_in_mode_api.training.preview import main

    text = main(["--goal", "lose_fat", "--location", "home", "--days", "3", "--minutes", "20"])

    assert "Mon  full body + finisher" in text
    assert "Tue  rest" in text
    assert "Why:" in text
