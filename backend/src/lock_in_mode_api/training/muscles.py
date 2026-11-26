"""The muscle map on Home (ADR 0036): which muscles, down to each head, this week's
workouts trained, and which ones the next workout trains.

A set counts once for every head its exercise targets (`Exercise.targets`), and once for
each muscle group those heads belong to. No exercise isolates one head: a target means
"most of the work goes here" (knowledge base, section 5), so the map shows where the
work went, not exact muscle activation. Every group and every head is always listed
(0 sets = "not yet"), so the phone never has to know the list. Pure, no database.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from lock_in_mode_api.models.enums import HEAD_GROUP, MuscleGroup, MuscleHead


@dataclass(frozen=True)
class HeadCount:
    head: MuscleHead
    sets: int
    next_up: bool


@dataclass(frozen=True)
class GroupCount:
    group: MuscleGroup
    sets: int
    next_up: bool
    heads: tuple[HeadCount, ...]


def _heads(targets: Iterable[str]) -> set[MuscleHead]:
    """Known heads only: a target the code doesn't know yet is left out, not an error."""
    known = {h.value for h in MuscleHead}
    return {MuscleHead(t) for t in targets if t in known}


def muscle_map(
    trained_sets: Iterable[Iterable[str]], next_targets: Iterable[str]
) -> list[GroupCount]:
    """`trained_sets`: the targets of each ticked set this week. `next_targets`: the
    targets of the next workout's exercises. Groups and heads in the enums' order."""
    head_sets: Counter[MuscleHead] = Counter()
    group_sets: Counter[MuscleGroup] = Counter()
    for targets in trained_sets:
        hit = _heads(targets)
        head_sets.update(hit)
        group_sets.update({HEAD_GROUP[h] for h in hit})
    upcoming = _heads(next_targets)

    groups: list[GroupCount] = []
    for group in MuscleGroup:
        heads = tuple(
            HeadCount(head=h, sets=head_sets[h], next_up=h in upcoming)
            for h in MuscleHead
            if HEAD_GROUP[h] is group
        )
        if not heads:
            continue
        groups.append(
            GroupCount(
                group=group,
                sets=group_sets[group],
                next_up=any(h.next_up for h in heads),
                heads=heads,
            )
        )
    return groups
