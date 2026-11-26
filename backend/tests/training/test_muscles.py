"""The muscle map and the new-bests count (ADR 0036): pure rules, worked examples."""

from lock_in_mode_api.models.enums import HEAD_GROUP, MuscleGroup, MuscleHead
from lock_in_mode_api.training.bests import SetValues, count_bests
from lock_in_mode_api.training.muscles import GroupCount, muscle_map


def _group(groups: list[GroupCount], group: MuscleGroup) -> GroupCount:
    return next(g for g in groups if g.group is group)


def _heads(group: GroupCount) -> dict[str, int]:
    return {h.head.value: h.sets for h in group.heads}


# --- the muscle map ---------------------------------------------------------------------


def test_every_group_and_head_is_listed_even_when_nothing_was_trained() -> None:
    groups = muscle_map([], [])
    assert [g.group for g in groups] == list(MuscleGroup)
    assert [h.head for g in groups for h in g.heads] == sorted(
        MuscleHead,
        key=lambda h: (list(MuscleGroup).index(HEAD_GROUP[h]), list(MuscleHead).index(h)),
    )
    assert all(g.sets == 0 and not g.next_up for g in groups)


def test_a_set_counts_once_per_head_and_once_per_group() -> None:
    bench = ["chest_mid", "chest_upper", "delt_front", "triceps_lateral"]
    groups = muscle_map([bench, bench, ["chest_upper"]], [])

    chest = _group(groups, MuscleGroup.CHEST)
    assert chest.sets == 3  # three sets touched the chest, not five head-hits
    assert _heads(chest) == {"chest_upper": 3, "chest_mid": 2, "chest_lower": 0}
    assert _group(groups, MuscleGroup.SHOULDERS).sets == 2
    assert _heads(_group(groups, MuscleGroup.TRICEPS))["triceps_long"] == 0  # not yet
    assert _group(groups, MuscleGroup.BACK).sets == 0


def test_a_head_listed_twice_in_one_exercise_still_counts_once() -> None:
    groups = muscle_map([["lats", "lats"]], [])
    assert _heads(_group(groups, MuscleGroup.BACK))["lats"] == 1


def test_the_next_workout_marks_its_heads_and_groups() -> None:
    groups = muscle_map([], ["lats", "biceps_long", "hamstrings_knee"])

    back = _group(groups, MuscleGroup.BACK)
    assert back.next_up is True
    assert {h.head.value for h in back.heads if h.next_up} == {"lats"}
    assert _group(groups, MuscleGroup.CHEST).next_up is False


def test_an_unknown_target_is_left_out() -> None:
    groups = muscle_map([["chest_mid", "not_a_muscle"]], ["also_not"])
    assert sum(g.sets for g in groups) == 1
    assert not any(g.next_up for g in groups)


# --- counting new bests -----------------------------------------------------------------


def reps(*values: int) -> list[SetValues]:
    return [SetValues(None, r, None) for r in values]


def test_no_workouts_no_bests() -> None:
    assert count_bests([]) == 0


def test_the_first_time_is_never_a_best() -> None:
    assert count_bests([[{"push-up": reps(10)}]]) == 0


def test_each_beaten_best_counts_once_per_exercise_per_workout() -> None:
    workouts = [
        [{"push-up": reps(8), "squat": reps(20)}],
        [{"push-up": reps(9, 11), "squat": reps(20)}],  # push-up: 1 (not 2 sets); squat: same
        [{"push-up": reps(10)}],  # below 11: not a best
        [{"push-up": reps(12), "squat": reps(21)}],  # 2
    ]
    assert count_bests(workouts) == 3


def test_workouts_finished_at_the_same_moment_dont_count_against_each_other() -> None:
    """The finish screen compares with workouts finished BEFORE, so neither is a best."""
    assert count_bests([[{"push-up": reps(8)}, {"push-up": reps(12)}]]) == 0
    # ...but both count as "before" for the next one.
    assert (
        count_bests([[{"push-up": reps(8)}, {"push-up": reps(12)}], [{"push-up": reps(13)}]]) == 1
    )


def test_weight_and_holds_count_like_the_finish_screen() -> None:
    lift = [SetValues(10, 8, None)]
    heavier = [SetValues(12.5, 5, None)]
    hold = [SetValues(None, None, 30)]
    longer = [SetValues(None, None, 40)]
    assert count_bests([[{"row": lift, "plank": hold}], [{"row": heavier, "plank": longer}]]) == 2
    # Reps done with a weight are never a reps best.
    assert count_bests([[{"row": lift}], [{"row": [SetValues(10, 12, None)]}]]) == 0
