"""Choosing exercises, with planned rotation (ADR 0014, 0015, 0017), the strength-test
placement (ADR 0018) and exercises the user swapped out (ADR 0020)."""

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence

from lock_in_mode_api.models.enums import HEAD_GROUP, Location, MovementSlot
from lock_in_mode_api.training.exercise_rules import can_do, cautions
from lock_in_mode_api.training.plan_types import (
    LEVEL_MAX_DIFFICULTY,
    BuildInputs,
    ExerciseInfo,
    is_weighted,
)
from lock_in_mode_api.training.templates import Slot

BIG_POOL = 2  # big lifts alternate between 2 picks, every block (ADR 0014, 0017)
SMALL_POOL = 3  # small moves cycle through 3 picks...
SMALL_CHOICES = 6  # ...taken from the best 6, a different 3 each block (ADR 0017)


def _slot_rank(exercise: ExerciseInfo, slot: Slot, misfit: int) -> tuple[object, ...]:
    return (
        misfit > 0,  # right for this user first (level cap, or the placed rung)
        misfit,  # if nothing fits, the closest
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

    `block_number` (1, 2, 3, ...) changes the small moves from block to block. Big lifts
    stay, so their progress can be compared across blocks (KB section 10).

    `rungs`: difficulty placed by the strength test, per movement (ADR 0018). At home,
    bodyweight moves of a placed movement are matched to it instead of the level's cap.
    Gym users are placed by the weights they log (KB section 2), so rungs don't apply.

    `excluded`: slugs the user swapped out ("this hurts", ADR 0020). Never offered again,
    like a caution, until they bring one back.
    """

    def __init__(
        self,
        answers: BuildInputs,
        library: Sequence[ExerciseInfo],
        block_number: int = 1,
        rungs: Mapping[MovementSlot, int] | None = None,
        excluded: Collection[str] = (),
    ) -> None:
        self.answers = answers
        self.block_number = block_number
        self.rungs = dict(rungs or {}) if answers.location == Location.HOME else {}
        self.cap = LEVEL_MAX_DIFFICULTY[answers.level]
        self.excluded = frozenset(excluded)
        self.usable = [
            e
            for e in library
            if can_do(e, answers) and not cautions(e, answers) and e.slug not in self.excluded
        ]
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
            self.by_movement.get(movement, []),
            key=lambda e: _slot_rank(e, slot, self.misfit(e)),
        )
        in_level = [e for e in ranked if self.misfit(e) == 0] or ranked[:1]
        key = f"slot:{slot.movement.value}:{slot.prefer.value if slot.prefer else ''}"
        if slot.main:
            return self.take_turn(key, in_level, BIG_POOL, used)
        return self.take_turn(key, self._block_order(in_level), SMALL_POOL, used)

    def misfit(self, exercise: ExerciseInfo) -> int:
        """0 = right for this user. Bodyweight moves of a placed movement: steps away from
        the rung, either way. Everything else: steps over the level's cap.
        """
        rung = self.rungs.get(exercise.movement_slot)
        if rung is not None and not is_weighted(exercise):
            return abs(exercise.difficulty - rung)
        return max(0, exercise.difficulty - self.cap)

    def _block_order(self, ranked: list[ExerciseInfo]) -> list[ExerciseInfo]:
        """Small moves: the best 6, starting 3 further along each block, then the rest.

        Block 1 uses picks 1-3, block 2 picks 4-6, block 3 picks 1-3 again. With fewer
        than 6 options it wraps around. The rest stay at the end as a fallback.
        """
        choices = ranked[:SMALL_CHOICES]
        if not choices:
            return ranked
        start = ((self.block_number - 1) * SMALL_POOL) % len(choices)
        return choices[start:] + choices[:start] + ranked[SMALL_CHOICES:]

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
