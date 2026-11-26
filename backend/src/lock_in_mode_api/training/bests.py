"""New personal bests (ADR 0034): real progress as the headline of the finish screen
("New best: 14 push-ups"), because feeling more capable is what keeps people training.

Per exercise, this workout's best is compared with every earlier workout's:
- a weighted lift: the heaviest weight in a set;
- a move done for reps without weight: the most reps in one set;
- a hold: the longest hold.
Only the main part and finishers count (a warm-up set is not an attempt at a best). The
very first time a move is done is never a "best": there's nothing to beat yet. One best
per exercise, weight first. Pure, no database.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

type BestKind = Literal["weight", "reps", "seconds"]


@dataclass(frozen=True)
class Best:
    weight_kg: float | None = None
    reps: int | None = None  # sets without weight only
    seconds: int | None = None


@dataclass(frozen=True)
class SetValues:
    weight_kg: float | None
    reps: int | None
    seconds: int | None


def _top[T: (int, float)](values: Iterable[T | None]) -> T | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def best_of(sets: Iterable[SetValues]) -> Best:
    rows = list(sets)
    return Best(
        weight_kg=_top(s.weight_kg for s in rows),
        reps=_top(s.reps for s in rows if s.weight_kg is None),
        seconds=_top(s.seconds for s in rows),
    )


def new_best(now: Best, before: Best) -> tuple[BestKind, float, float] | None:
    """(kind, new value, the old best), or None. Weight first, then reps, then holds."""
    pairs: tuple[tuple[BestKind, float | None, float | None], ...] = (
        ("weight", now.weight_kg, before.weight_kg),
        ("reps", now.reps, before.reps),
        ("seconds", now.seconds, before.seconds),
    )
    for kind, value, previous in pairs:
        if value is not None and previous is not None and value > previous:
            return kind, value, previous
    return None
