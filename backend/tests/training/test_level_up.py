"""The level-up rules (ADR 0022): good weeks, the three marks with harder moves, the offer.
Pure, with the real library's ladders."""

from datetime import UTC, datetime, timedelta

import pytest

from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location, ShoulderDay
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training import level_up as rules
from lock_in_mode_api.training.level_up import Best, LevelUpReason, WeekShape
from lock_in_mode_api.training.plan_types import BUILD_WEEKS, PlanAnswers
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import build_block

LIBRARY = {e.slug: e for e in load_library().exercises}
HARDER = {slug: e.harder for slug, e in LIBRARY.items()}
TIMED = {slug: e.is_timed for slug, e in LIBRARY.items()}
START = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)
ALL_MARKS = Best(reps={"push-up": 15, "bodyweight-squat": 25}, seconds={"plank": 45})


def _workouts(*per_week: int) -> list[datetime]:
    """`per_week[i]` workouts in week i, on different days of that week."""
    return [
        START + timedelta(days=7 * week + day)
        for week, count in enumerate(per_week)
        for day in range(count)
    ]


# --- good weeks -------------------------------------------------------------------------


def test_no_workouts_no_weeks() -> None:
    assert rules.good_weeks([]) == 0


def test_a_good_week_has_two_workouts() -> None:
    assert rules.good_weeks(_workouts(1, 2, 3, 0, 2)) == 3


def test_gaps_pause_the_count_instead_of_wiping_it() -> None:
    six_on, two_months_off, six_on_again = [2] * 6, [0] * 8, [2] * 6
    assert rules.good_weeks(_workouts(*six_on, *two_months_off, *six_on_again)) == 12


def test_weeks_count_from_the_first_workout_not_the_weekday() -> None:
    # Sunday evening and the next Monday morning are the same 7-day stretch.
    sunday = datetime(2026, 1, 4, 21, 0, tzinfo=UTC)
    assert rules.good_weeks([sunday, sunday + timedelta(hours=11)]) == 1
    assert rules.good_weeks([sunday, sunday + timedelta(days=7)]) == 0


def test_order_doesnt_matter() -> None:
    times = _workouts(2, 2, 2)
    assert rules.good_weeks(reversed(times)) == 3


# --- the marks ------------------------------------------------------------------------------


def test_the_ladders_in_the_library() -> None:
    assert rules.ladder("push-up", HARDER)[:3] == [
        "push-up",
        "close-grip-push-up",
        "decline-push-up",
    ]
    assert rules.ladder("bodyweight-squat", HARDER)[0:2] == ["bodyweight-squat", "tempo-squat"]
    assert rules.ladder("plank", HARDER)[0] == "plank"
    assert "knee-push-up" not in rules.ladder("push-up", HARDER)


def test_all_three_marks_pass() -> None:
    assert rules.passes_all(ALL_MARKS, HARDER, TIMED)


@pytest.mark.parametrize(
    "short",
    [
        Best(reps={"push-up": 14, "bodyweight-squat": 25}, seconds={"plank": 45}),
        Best(reps={"push-up": 15, "bodyweight-squat": 24}, seconds={"plank": 45}),
        Best(reps={"push-up": 15, "bodyweight-squat": 25}, seconds={"plank": 44}),
        Best(reps={"push-up": 15, "bodyweight-squat": 25}, seconds={}),
    ],
)
def test_every_mark_is_needed(short: Best) -> None:
    assert not rules.passes_all(short, HARDER, TIMED)


def test_a_harder_move_counts() -> None:
    harder = rules.ladder("push-up", HARDER)[2]  # decline push-up
    best = Best(reps={harder: 15, "bodyweight-squat": 25}, seconds={"plank": 45})
    assert rules.passes_all(best, HARDER, TIMED)


def test_an_easier_move_doesnt_count() -> None:
    best = Best(reps={"knee-push-up": 40, "bodyweight-squat": 25}, seconds={"plank": 45})
    assert not rules.passes_all(best, HARDER, TIMED)


def test_a_hold_counts_only_on_a_timed_move() -> None:
    reps_moves = [s for s in rules.ladder("plank", HARDER) if not TIMED[s]]
    timed_moves = [s for s in rules.ladder("plank", HARDER) if TIMED[s]]
    assert timed_moves
    base = {"push-up": 15, "bodyweight-squat": 25}
    if reps_moves:
        no_hold = Best(reps=base, seconds={reps_moves[0]: 60})
        assert not rules.passes_all(no_hold, HARDER, TIMED)
    hold = Best(reps=base, seconds={timed_moves[-1]: 45})
    assert rules.passes_all(hold, HARDER, TIMED)
    # reps logged on the plank itself don't make a hold
    assert not rules.passes_all(Best(reps=base | {"plank": 60}, seconds={}), HARDER, TIMED)


def test_a_broken_ladder_loop_ends() -> None:
    assert rules.ladder("a", {"a": "b", "b": "a"}) == ["a", "b"]


# --- the offer --------------------------------------------------------------------------------


def test_only_beginners_are_offered() -> None:
    assert rules.offer(FitnessLevel.BEGINNER, 12, False) == LevelUpReason.GOOD_WEEKS
    assert rules.offer(FitnessLevel.BEGINNER, 11, False) is None
    assert rules.offer(FitnessLevel.BEGINNER, 0, True) == LevelUpReason.STRENGTH_MARKS
    assert rules.offer(FitnessLevel.BEGINNER, 12, True) == LevelUpReason.STRENGTH_MARKS
    for level in (FitnessLevel.SOME_EXPERIENCE, FitnessLevel.EXPERIENCED):
        assert rules.offer(level, 50, True) is None


# --- the low-intensity cap (ADR 0022 follow-up) ----------------------------------------------


def _answers(level: FitnessLevel, goal: Goal, days: int, low: bool) -> PlanAnswers:
    return PlanAnswers(
        goal=goal,
        level=level,
        location=Location.HOME,
        equipment=(),
        limits=(),
        days_per_week=days,
        minutes_per_session=45,
        women_home_track=False,
        prefers_bro_split=False,
        shoulder_day=ShoulderDay.PUSH,
        needs_low_intensity=low,
    )


def _hard(answers: PlanAnswers) -> int:
    week = build_block(answers, choose_routine(answers), load_library().exercises, BUILD_WEEKS)[0]
    return rules.week_shape(week).hard_workouts


@pytest.mark.parametrize("level", [FitnessLevel.SOME_EXPERIENCE, FitnessLevel.EXPERIENCED])
@pytest.mark.parametrize("goal", [Goal.BUILD_MUSCLE, Goal.STRENGTH, Goal.LOSE_FAT, Goal.STAMINA])
@pytest.mark.parametrize("days", [4, 5, 6])
def test_low_intensity_means_three_hard_days_at_most_at_any_level(
    level: FitnessLevel, goal: Goal, days: int
) -> None:
    assert _hard(_answers(level, goal, days, low=True)) <= 3


def test_the_cap_is_explained_and_only_for_low_intensity() -> None:
    low = _answers(FitnessLevel.SOME_EXPERIENCE, Goal.BUILD_MUSCLE, 6, low=True)
    assert any(r.startswith("From your safety check: 3 hard") for r in choose_routine(low).reasons)
    normal = _answers(FitnessLevel.SOME_EXPERIENCE, Goal.BUILD_MUSCLE, 6, low=False)
    assert _hard(normal) == 6


# --- what changes -------------------------------------------------------------------------------


def test_what_changes_shows_the_real_numbers() -> None:
    lines = rules.what_changes(WeekShape(3, 42), WeekShape(5, 60), minutes=45, low_intensity=False)
    assert lines[:2] == ["Hard workouts a week: 3 → 5.", "Sets a week: about 42 → 60."]
    assert lines[-1].startswith("Your progress stays")


def test_short_sessions_dont_promise_more_sets() -> None:
    lines = rules.what_changes(WeekShape(3, 24), WeekShape(3, 22), minutes=20, low_intensity=False)
    assert not any("Sets a week" in line for line in lines)
    assert "Your sessions stay 20 minutes" in lines[0]


def test_low_intensity_is_told_the_limits_stay() -> None:
    lines = rules.what_changes(WeekShape(3, 42), WeekShape(3, 52), minutes=45, low_intensity=True)
    assert any(line.startswith("Your safety limits stay") for line in lines)
