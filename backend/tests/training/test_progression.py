"""Progression rules (ADR 0019, KB section 10): pure, no database."""

import random
from dataclasses import replace

import pytest

from lock_in_mode_api.models.enums import Equipment, Feedback, MovementSlot, ProgressChange
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.plan_types import is_weighted
from lock_in_mode_api.training.progression import (
    HOLD_TOP,
    Logged,
    Move,
    Planned,
    Served,
    Target,
    after_workout,
    earns_recovery,
    neighbour_rungs,
    serve,
    step_back,
    step_up,
    streak_fires,
    weight_step,
)

C = ProgressChange
E, J, H = Feedback.TOO_EASY, Feedback.JUST_RIGHT, Feedback.TOO_HARD
REPS = Planned(sets=3, reps_min=8, reps_max=12, seconds=None)
HOLD = Planned(sets=2, reps_min=None, reps_max=None, seconds=40)
BODYWEIGHT = Move(timed=False, weight_step=2.5, harder_rung=3, easier_rung=1)
GYM_BODYWEIGHT = Move(timed=False, weight_step=2.5)
DUMBBELL = Move(timed=False, weight_step=2.5)
PLANK = Move(timed=True, weight_step=2.5, harder_rung=3, easier_rung=1)


def _sets(
    count: int, reps: int | None = None, weight: float | None = None, seconds: int | None = None
) -> dict[int, Logged]:
    return {n: Logged(reps, weight, seconds) for n in range(1, count + 1)}


def _after(
    move: Move,
    target: Target | None,
    logged: dict[int, Logged],
    feedback: Feedback | None = None,
    planned: Planned = REPS,
) -> tuple[Target, ProgressChange | None, int | None]:
    step = after_workout(move, target, serve(planned, target), logged, feedback)
    return step.target, step.change, step.rung


# --- serving ----------------------------------------------------------------------------


def test_no_progress_serves_the_plan() -> None:
    assert serve(REPS, None) == Served(3, 8, 12, None, None)


def test_progress_is_added_to_the_plan() -> None:
    served = serve(REPS, Target(weight_kg=22.5, set_change=1, reps_bonus=2))

    assert served == Served(4, 10, 12, None, 22.5)


def test_a_reps_nudge_never_passes_the_top() -> None:
    assert serve(Planned(2, 11, 12, None), Target(reps_bonus=5)).reps_min == 12


def test_holds_use_the_saved_time_and_sets_never_go_below_one() -> None:
    served = serve(Planned(1, None, None, 25), Target(seconds=45, set_change=-1))

    assert (served.sets, served.seconds) == (1, 45)


def test_a_circuit_keeps_its_rounds() -> None:
    assert serve(REPS, Target(set_change=1), circuit=True).sets == 3


# --- step sizes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("equipment", "also_needs", "movement", "step"),
    [
        ([Equipment.DUMBBELLS], None, MovementSlot.SQUAT, 2.5),
        ([Equipment.DUMBBELLS, Equipment.GYM], "Bench", MovementSlot.HORIZONTAL_PUSH, 2.5),
        ([Equipment.GYM], "Barbell, bench", MovementSlot.HORIZONTAL_PUSH, 2.5),
        ([Equipment.GYM], "Barbell, rack", MovementSlot.SQUAT, 5.0),
        ([Equipment.GYM], "Trap bar", MovementSlot.HINGE, 5.0),
        ([Equipment.GYM], "Machine", MovementSlot.LATERAL_RAISE, 5.0),
        ([Equipment.GYM], "Cable, rope", MovementSlot.TRICEPS, 5.0),
        ([Equipment.GYM], "Kettlebell", MovementSlot.HINGE, 4.0),
    ],
)
def test_one_step_is_the_next_weight_a_gym_has(
    equipment: list[Equipment], also_needs: str | None, movement: MovementSlot, step: float
) -> None:
    assert weight_step(equipment, also_needs, movement) == step


def test_neighbour_rungs() -> None:
    assert neighbour_rungs(2, [1, 1, 2, 3, 3, 5]) == (1, 3)
    assert neighbour_rungs(5, [1, 5]) == (1, None)
    assert neighbour_rungs(1, []) == (None, None)


# --- double progression ----------------------------------------------------------------


def test_the_top_on_every_set_means_heavier_and_reps_start_again() -> None:
    target, change, _ = _after(DUMBBELL, Target(reps_bonus=2), _sets(3, 12, 20.0))

    assert change == C.HEAVIER
    assert target == Target(weight_kg=22.5)
    assert serve(REPS, target).reps_min == 8  # back to the bottom


def test_one_set_short_of_the_top_is_no_step() -> None:
    logged = _sets(3, 12, 20.0) | {3: Logged(11, 20.0, None)}

    assert _after(DUMBBELL, None, logged)[1] is None


def test_a_missing_set_is_no_step() -> None:
    assert _after(DUMBBELL, None, _sets(2, 12, 20.0))[1] is None


def test_the_lightest_weight_logged_is_the_base() -> None:
    logged = _sets(3, 12, 20.0) | {1: Logged(12, 25.0, None)}

    assert _after(DUMBBELL, None, logged)[0].weight_kg == 22.5


def test_staying_lighter_than_suggested_earns_a_set_instead() -> None:
    """Home dumbbells may not go heavier: hitting the top again gives an extra set."""
    target, change, _ = _after(DUMBBELL, Target(weight_kg=22.5), _sets(3, 12, 20.0))

    assert change == C.EXTRA_SET
    assert target.set_change == 1 and target.weight_kg == 22.5
    assert _after(DUMBBELL, target, _sets(4, 12, 20.0))[1] is None  # nothing left to add


def test_bodyweight_goes_extra_set_then_harder_move() -> None:
    target, change, rung = _after(BODYWEIGHT, None, _sets(3, 12))
    assert (change, rung, target.set_change) == (C.EXTRA_SET, None, 1)

    target, change, rung = _after(BODYWEIGHT, target, _sets(4, 12))
    assert (change, rung, target.set_change) == (C.HARDER_MOVE, 3, 0)


def test_in_the_gym_bodyweight_stops_at_the_extra_set() -> None:
    target, change, _ = _after(GYM_BODYWEIGHT, Target(set_change=1), _sets(4, 12))

    assert change is None and target.set_change == 1


def test_holds_grow_to_60_seconds_then_the_harder_hold() -> None:
    target: Target | None = None
    changes = []
    for _ in range(6):
        held = serve(HOLD, target).seconds
        target, change, rung = _after(PLANK, target, _sets(2, seconds=held), planned=HOLD)
        changes.append((change, target.seconds, rung))

    assert changes == [
        (C.LONGER_HOLD, 45, None),
        (C.LONGER_HOLD, 50, None),
        (C.LONGER_HOLD, 55, None),
        (C.LONGER_HOLD, 60, None),
        (C.HARDER_MOVE, None, 3),
        (C.LONGER_HOLD, 45, None),  # the new hold starts from the plan's time
    ]


def test_a_circuit_skips_the_extra_set() -> None:
    move = replace(BODYWEIGHT, can_change_sets=False)

    assert _after(move, None, _sets(3, 12))[1] == C.HARDER_MOVE


# --- the feedback tap, once ------------------------------------------------------------


def test_too_hard_means_repeat_even_at_the_top() -> None:
    assert _after(DUMBBELL, None, _sets(3, 12, 20.0), H)[1] is None


def test_too_easy_once_aims_two_reps_higher_next_time_only() -> None:
    target, change, _ = _after(BODYWEIGHT, None, _sets(3, 9), E)
    assert change == C.MORE_REPS and serve(REPS, target).reps_min == 10

    target, change, _ = _after(BODYWEIGHT, target, _sets(3, 10), J)
    assert change is None and target.reps_bonus == 0


def test_too_easy_with_nothing_logged_still_nudges() -> None:
    assert _after(BODYWEIGHT, None, {}, E)[1] == C.MORE_REPS


def test_too_easy_on_a_hold_adds_five_seconds() -> None:
    target, change, _ = _after(PLANK, None, _sets(2, seconds=30), E, planned=HOLD)

    assert (change, target.seconds) == (C.LONGER_HOLD, 45)


# --- falling short -----------------------------------------------------------------------


def test_short_twice_in_a_row_steps_back() -> None:
    target, change, _ = _after(DUMBBELL, Target(weight_kg=20.0), _sets(3, 5, 20.0))
    assert change is None and target.short_runs == 1

    target, change, _ = _after(DUMBBELL, target, _sets(3, 5, 20.0))
    assert (change, target.weight_kg, target.short_runs) == (C.LIGHTER, 17.5, 0)


def test_a_normal_workout_in_between_resets_the_count() -> None:
    target, _, _ = _after(DUMBBELL, Target(short_runs=1), _sets(3, 8, 20.0))

    assert target.short_runs == 0


def test_only_the_first_set_counts_and_a_missed_exercise_changes_nothing() -> None:
    later_sets_short = _sets(3, 8, 20.0) | {2: Logged(2, 20.0, None)}
    assert _after(DUMBBELL, Target(short_runs=1), later_sets_short)[0].short_runs == 0
    assert _after(DUMBBELL, Target(short_runs=1), {})[0].short_runs == 1


# --- stepping back -------------------------------------------------------------------------


def _back(
    move: Move, target: Target, planned: Planned = REPS, weight: float | None = None
) -> tuple[ProgressChange | None, Target, int | None]:
    step = step_back(move, target, serve(planned, target), weight)
    return step.change, step.target, step.rung


def test_step_back_takes_the_extra_set_first() -> None:
    assert _back(BODYWEIGHT, Target(set_change=1))[:2] == (C.FEWER_SETS, Target())


def test_step_back_a_weight_by_about_ten_percent_and_at_least_one_step() -> None:
    assert _back(DUMBBELL, Target(), weight=100.0)[1].weight_kg == 90.0
    assert _back(DUMBBELL, Target(), weight=20.0)[1].weight_kg == 17.5


def test_the_lightest_weight_steps_back_a_set_instead() -> None:
    change, target, _ = _back(DUMBBELL, Target(weight_kg=2.5), weight=2.5)

    assert change == C.FEWER_SETS and target.set_change == -1


def test_step_back_bodyweight_one_rung_down() -> None:
    assert _back(BODYWEIGHT, Target())[0::2] == (C.EASIER_MOVE, 1)


def test_step_back_a_hold_ten_seconds_then_a_rung() -> None:
    assert _back(PLANK, Target(), HOLD)[:2] == (C.SHORTER_HOLD, Target(seconds=30))
    assert _back(PLANK, Target(seconds=15), HOLD)[0::2] == (C.EASIER_MOVE, 1)


def test_never_below_one_set() -> None:
    change, target, _ = _back(GYM_BODYWEIGHT, Target(set_change=-1), Planned(2, 8, 12, None))
    assert change is None and target.set_change == -1
    assert _back(GYM_BODYWEIGHT, Target(), Planned(1, 8, 12, None))[0] is None


def test_a_set_taken_away_comes_back_first() -> None:
    step = step_up(DUMBBELL, Target(weight_kg=17.5, set_change=-1), serve(REPS, None), 17.5)

    assert (step.change, step.target.set_change, step.target.weight_kg) == (C.EXTRA_SET, 0, 17.5)


# --- whole-plan rules ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answers", "fires"),
    [
        ([], None),
        ([E], None),
        ([E, E], E),
        ([E, E, E], None),  # a third is a nudge again, not a second jump
        ([E, E, E, E], E),
        ([H, H], H),
        ([H, H, E], H),
        ([E, H], None),
        ([J, J], None),
    ],
)
def test_the_same_tap_twice_in_a_row(answers: list[Feedback], fires: Feedback | None) -> None:
    assert streak_fires(answers) == fires


@pytest.mark.parametrize(
    ("too_hard", "workouts", "earned"),
    [(1, 3, False), (2, 3, True), (2, 4, False), (3, 4, True), (1, 2, False), (1, 1, True)],
)
def test_too_hard_on_more_than_half_the_week(too_hard: int, workouts: int, earned: bool) -> None:
    assert earns_recovery(too_hard, workouts) is earned


# --- sweep: every exercise, many plans and histories ------------------------------------

LIBRARY = load_library().exercises
PLANS = [
    Planned(sets, low, high, None)
    for sets in (1, 2, 3, 4)
    for low, high in ((3, 6), (5, 8), (6, 10), (8, 12), (10, 20), (15, 25))
] + [Planned(sets, None, None, seconds) for sets in (1, 2, 3) for seconds in (25, 40, 50, 60)]


def _valid(target: Target) -> None:
    """What the exercise_targets CHECK constraints allow."""
    assert target.weight_kg is None or target.weight_kg > 0
    assert -1 <= target.set_change <= 1
    assert target.seconds is None or 1 <= target.seconds <= 600
    assert 0 <= target.reps_bonus <= 5
    assert target.short_runs >= 0


def test_sweep_random_histories_stay_valid() -> None:
    """30,000+ workouts: random logs and taps never produce a target the database refuses,
    or a served workout that makes no sense."""
    rng = random.Random(19)
    feedback = [None, E, J, H]
    checked = 0
    for exercise in LIBRARY:
        timed = exercise.is_timed
        step = weight_step(exercise.equipment, exercise.also_needs, exercise.movement_slot)
        plans = [p for p in PLANS if (p.seconds is not None) == timed]
        for circuit in (False, True):
            move = Move(timed, step, rng.choice([None, 2, 3]), rng.choice([None, 1]), not circuit)
            planned = rng.choice(plans)
            target: Target | None = None
            for _ in range(60):
                served = serve(planned, target, circuit=circuit)
                assert served.sets >= 1
                assert served.reps_min is None or served.reps_min <= (served.reps_max or 0)
                logged = {
                    n: Logged(
                        None if timed else rng.randint(0, (served.reps_max or 0) + 2),
                        rng.choice([None, 5.0, 20.0]) if is_weighted(exercise) else None,
                        rng.randint(0, 70) if timed else None,
                    )
                    for n in range(1, served.sets + 1)
                    if rng.random() > 0.1
                }
                result = after_workout(move, target, served, logged, rng.choice(feedback))
                _valid(result.target)
                assert (result.rung is None) == (
                    result.change not in {C.HARDER_MOVE, C.EASIER_MOVE}
                )
                target = result.target
                checked += 1
    assert checked > 30_000


def test_sweep_stepping_up_always_ends_at_the_top_or_a_harder_move() -> None:
    """Hitting the top every time never loops forever and never makes it easier."""
    for planned in PLANS:
        for move in (BODYWEIGHT, GYM_BODYWEIGHT, PLANK, replace(BODYWEIGHT, can_change_sets=False)):
            if move.timed != (planned.seconds is not None):
                continue
            target: Target | None = None
            before = serve(planned, None)
            for _ in range(20):
                served = serve(planned, target)
                assert served.sets >= before.sets and (served.seconds or 0) >= (before.seconds or 0)
                before = served
                step = after_workout(
                    move,
                    target,
                    served,
                    _sets(served.sets, served.reps_max, None, served.seconds),
                    None,
                )
                if step.change in (None, C.HARDER_MOVE):
                    break
                target = step.target
            else:
                pytest.fail(f"{move} on {planned} never settled")
            assert (served.seconds or 0) <= max(HOLD_TOP, planned.seconds or 0)
