"""Choosing exercises, with planned rotation (ADR 0014, ADR 0015)."""

from collections import Counter
from collections.abc import Callable, Sequence

from lock_in_mode_api.models.enums import HEAD_GROUP, MovementSlot
from lock_in_mode_api.training.exercise_rules import can_do, cautions
from lock_in_mode_api.training.plan_types import LEVEL_MAX_DIFFICULTY, BuildInputs, ExerciseInfo
from lock_in_mode_api.training.templates import Slot


def _slot_rank(exercise: ExerciseInfo, slot: Slot, cap: int) -> tuple[object, ...]:
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


class Picker:
    """Knows what this user may do and takes turns through short ranked pools.

    Only exercises the user **can do** and that carry **no caution** are ever offered
    (ADR 0013). The n-th time a pool is used in a block it gives pool[n % size], so picks
    rotate on a fixed pattern, never randomly.
    """

    def __init__(self, answers: BuildInputs, library: Sequence[ExerciseInfo]) -> None:
        self.answers = answers
        self.cap = LEVEL_MAX_DIFFICULTY[answers.level]
        self.usable = [e for e in library if can_do(e, answers) and not cautions(e, answers)]
        self.by_slug = {e.slug: e for e in self.usable}
        self.by_movement: dict[MovementSlot, list[ExerciseInfo]] = {}
        for exercise in self.usable:
            self.by_movement.setdefault(exercise.movement_slot, []).append(exercise)
        self.turns: Counter[str] = Counter()

    def take_turn(
        self, key: str, ranked: Sequence[ExerciseInfo], size: int, used: set[str]
    ) -> ExerciseInfo | None:
        """The next pick from the top `size` of `ranked`, skipping exercises in `used`."""
        if not ranked:
            return None
        pool = list(ranked[:size])
        turn = self.turns[key]
        self.turns[key] += 1
        for offset in range(len(pool)):
            choice = pool[(turn + offset) % len(pool)]
            if choice.slug not in used:
                return choice
        return next((e for e in ranked if e.slug not in used), None)

    def pick(self, slot: Slot, used: set[str]) -> ExerciseInfo | None:
        """Fill a template slot: big lifts rotate between 2 picks, small moves between 3."""
        movement = slot.movement
        if not self.by_movement.get(movement) and slot.fallback is not None:
            movement = slot.fallback
        ranked = sorted(
            self.by_movement.get(movement, []), key=lambda e: _slot_rank(e, slot, self.cap)
        )
        in_level = [e for e in ranked if e.difficulty <= self.cap] or ranked[:1]
        key = f"slot:{slot.movement.value}:{slot.prefer.value if slot.prefer else ''}"
        return self.take_turn(key, in_level, 2 if slot.main else 3, used)

    def from_list(
        self,
        key: str,
        slugs: Sequence[str],
        used: set[str],
        size: int = 3,
        rank: Callable[[ExerciseInfo], tuple[object, ...]] | None = None,
    ) -> ExerciseInfo | None:
        """Rotate through a named list of moves (warm-ups, HIIT moves), keeping only safe ones."""
        options = [self.by_slug[slug] for slug in slugs if slug in self.by_slug]
        if rank is not None:
            options.sort(key=rank)
        return self.take_turn(key, options, size, used)
